"""Local technician commissioning service. No recording, uploads or remote roles."""
import hmac
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from pose import PoseBackend


def integer(env, name, default, low, high):
    raw = env.get(name, str(default))
    if not re.fullmatch(r"[0-9]+", raw):
        raise ValueError(f"{name} must be an integer")
    value = int(raw)
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Config:
    token: str
    device: str = "/dev/video0"
    width: int = 640
    height: int = 480
    fps: int = 10
    freshness_ms: int = 2000
    pose_path: str = ""
    keypoint_percent: int = 50

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        token = env.get("EDGE_TOKEN", "")
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("EDGE_TOKEN must contain at least 32 non-whitespace ASCII characters")
        device = env.get("EDGE_CAMERA", "/dev/video0")
        if not re.fullmatch(r"/dev/video[0-9]+", device):
            raise ValueError("EDGE_CAMERA must match /dev/video followed by digits")
        return cls(token, device,
                   integer(env, "EDGE_WIDTH", 640, 160, 1920),
                   integer(env, "EDGE_HEIGHT", 480, 120, 1080),
                   integer(env, "EDGE_FPS", 10, 1, 30),
                   integer(env, "EDGE_FRESHNESS_MS", 2000, 250, 5000),
                   env.get("POSE_ONNX", ""),
                   integer(env, "POSE_KEYPOINT_PERCENT", 50, 1, 100))


class StartOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    width: int | None = Field(default=None, ge=160, le=1920)
    height: int | None = Field(default=None, ge=120, le=1080)
    fps: int | None = Field(default=None, ge=1, le=30)


class Camera:
    def __init__(self, config, capture_factory=None, pose_factory=PoseBackend, clock=time.monotonic):
        self.config = config
        self.capture_factory = capture_factory or (lambda path: cv2.VideoCapture(path, cv2.CAP_V4L2))
        self.pose_factory = pose_factory
        self.clock = clock
        self.lock = threading.Lock()
        self.control = threading.Lock()
        self.quit = threading.Event()
        self.thread = None
        self.state = "stopped"
        self.error = None
        self.jpeg = None
        self.timestamp = 0.0
        self.sequence = 0
        self.model_state = "not_loaded" if config.pose_path else "no_model"
        self.model_error = None
        self.frame_model = self.model_state
        self.people = None
        self.actual = None
        self.requested = None

    def _clear(self):
        self.jpeg = None
        self.people = None
        self.actual = None

    def start(self, options):
        with self.control:
            with self.lock:
                if self.thread and self.thread.is_alive():
                    if self.state == "stopping":
                        raise HTTPException(409, "Previous camera worker is still stopping")
                    return
                self.quit.clear()
                self._clear()
                self.state, self.error = "starting", None
                self.model_state = "loading" if self.config.pose_path else "no_model"
                self.model_error = None
                self.requested = {k: getattr(options, k) or getattr(self.config, k)
                                  for k in ("width", "height", "fps")}
                self.thread = threading.Thread(target=self._run, args=(self.requested.copy(),),
                                               name="camera-capture", daemon=True)
                self.thread.start()

    def stop(self):
        with self.control:
            with self.lock:
                self.quit.set()
                self._clear()
                thread = self.thread
                self.state = "stopping" if thread and thread.is_alive() else "stopped"
            if thread:
                thread.join(timeout=5)
            with self.lock:
                if thread and thread.is_alive():
                    self.error = "Camera driver/inference has not returned; waiting for worker release"
                else:
                    self.state, self.error = "stopped", None

    def _run(self, requested):
        cap = None
        try:
            backend = None
            if self.config.pose_path:
                try:
                    backend = self.pose_factory(self.config.pose_path, self.config.keypoint_percent / 100)
                    with self.lock:
                        self.model_state = "ready"
                except Exception as exc:
                    with self.lock:
                        self.model_state = "model_error"
                        self.model_error = (str(exc)[:240] if isinstance(exc, ValueError)
                                            else "ONNX load/forward failed; check local model contract")
            if self.quit.is_set():
                return
            cap = self.capture_factory(self.config.device)
            if not cap.isOpened():
                raise RuntimeError("Cannot open configured V4L2 camera; check node, permissions and ownership")
            for prop, value in ((cv2.CAP_PROP_FRAME_WIDTH, requested["width"]),
                                (cv2.CAP_PROP_FRAME_HEIGHT, requested["height"]),
                                (cv2.CAP_PROP_FPS, requested["fps"]),
                                (cv2.CAP_PROP_BUFFERSIZE, 1)):
                cap.set(prop, value)
            while not self.quit.is_set():
                began = self.clock()
                ok, image = cap.read()
                if not ok or image is None or not image.size:
                    raise RuntimeError("Camera frame read failed")
                captured = self.clock()
                count = None
                if backend is not None:
                    original = image.copy()
                    try:
                        count = backend.annotate(image)
                        with self.lock:
                            self.model_state = "people_detected" if count else "no_people"
                    except Exception:
                        image = original
                        backend = None
                        with self.lock:
                            self.model_state = "model_error"
                            self.model_error = "Pose inference failed; showing unannotated camera only"
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                with self.lock:
                    if self.quit.is_set():
                        break
                    self.jpeg = encoded.tobytes()
                    self.timestamp = captured
                    self.sequence += 1
                    self.people = count
                    self.frame_model = self.model_state
                    self.actual = {"width": image.shape[1], "height": image.shape[0]}
                    self.state = "running"
                self.quit.wait(max(0, 1 / requested["fps"] - (self.clock() - began)))
        except Exception as exc:
            with self.lock:
                self.state = "error"
                self.error = str(exc) if isinstance(exc, RuntimeError) else "Camera operation failed"
                self._clear()
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    with self.lock:
                        self.error = "Camera release failed; restart service and inspect driver"
            with self.lock:
                self._clear()
                if self.quit.is_set():
                    self.state = "stopped"

    def status(self):
        with self.lock:
            age = self.clock() - self.timestamp if self.jpeg is not None else None
            fresh = age is not None and age <= self.config.freshness_ms / 1000
            return {"camera": "stalled" if self.state == "running" and not fresh else self.state,
                    "camera_error": self.error, "frame_fresh": fresh,
                    "frame_age_ms": round(age * 1000) if age is not None else None,
                    "frame_sequence": self.sequence, "requested": self.requested,
                    "actual": self.actual, "model": self.model_state,
                    "model_error": self.model_error, "people": self.people if fresh else None,
                    "backend": "opencv_dnn_cpu_diagnostic" if self.config.pose_path else "none"}

    def snapshot(self):
        with self.lock:
            if (self.state != "running" or self.jpeg is None
                    or self.clock() - self.timestamp > self.config.freshness_ms / 1000):
                raise HTTPException(503, "No fresh frame available")
            return self.jpeg, self.sequence, self.frame_model, self.people


def create_app(config=None, camera=None):
    @asynccontextmanager
    async def lifespan(app):
        settings = config or Config.from_env()  # Missing/weak token fails startup, never opens camera.
        app.state.config = settings
        app.state.camera = camera or Camera(settings)
        try:
            yield
        finally:
            app.state.camera.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        return response

    def authenticate(request: Request):
        value = request.headers.get("authorization", "")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
                token.encode("utf-8"), app.state.config.token.encode("utf-8")):
            raise HTTPException(401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"})
        if request.method == "POST":
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin is not None and origin != expected:
                raise HTTPException(403, "Cross-origin camera control denied")
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise HTTPException(403, "Cross-site camera control denied")

    @app.get("/api/status", dependencies=[Depends(authenticate)])
    def status():
        return app.state.camera.status()

    @app.post("/api/camera/start", dependencies=[Depends(authenticate)])
    def start(options: StartOptions = StartOptions()):
        app.state.camera.start(options)
        return app.state.camera.status()

    @app.post("/api/camera/stop", dependencies=[Depends(authenticate)])
    def stop():
        app.state.camera.stop()
        return app.state.camera.status()

    @app.get("/api/frame", dependencies=[Depends(authenticate)])
    def frame():
        jpeg, seq, model, people = app.state.camera.snapshot()
        return Response(jpeg, media_type="image/jpeg", headers={
            "X-Frame-Sequence": str(seq), "X-Pose-State": model,
            "X-People-Count": "unknown" if people is None else str(people)})

    static = Path(__file__).resolve().parent / "static"
    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app()
