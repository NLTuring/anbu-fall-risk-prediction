"""Hardware-free lifecycle and API tests. Run from edge/ with unittest discovery."""
import threading
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from service import Camera, Config, StartOptions, create_app

TOKEN = "test-token-" + "x" * 40
AUTH = {"Authorization": "Bearer " + TOKEN}


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("Worker condition timed out")


class FakeCapture:
    def __init__(self, opened=True):
        self.opened = opened
        self.released = False
        self.fail = False
        self.settings = []

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.settings.append((prop, value))
        return True

    def read(self):
        return (False, None) if self.fail else (True, np.zeros((48, 64, 3), np.uint8))

    def release(self):
        self.released = True


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(TOKEN, fps=30)
        self.capture = FakeCapture()
        self.factory = Mock(return_value=self.capture)
        self.camera = Camera(self.config, self.factory)
        self.client = TestClient(create_app(self.config, self.camera))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def start(self):
        response = self.client.post("/api/camera/start", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        wait_until(lambda: self.camera.status()["frame_fresh"])

    def test_authentication_all_apis_and_public_static(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for path in ("/api/status", "/api/frame"):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["cache-control"], "no-store")
        for path in ("/api/camera/start", "/api/camera/stop"):
            self.assertEqual(self.client.post(path).status_code, 401)
        self.assertEqual(self.client.get("/api/status?token=" + TOKEN).status_code, 401)
        self.factory.assert_not_called()

    def test_no_model_start_stop_and_snapshot(self):
        state = self.client.get("/api/status", headers=AUTH).json()
        self.assertEqual(state["camera"], "stopped")
        self.assertEqual(state["model"], "no_model")
        self.factory.assert_not_called()
        self.assertEqual(self.client.get("/api/frame", headers=AUTH).status_code, 503)
        self.start()
        self.client.post("/api/camera/start", headers=AUTH)
        self.factory.assert_called_once_with("/dev/video0")
        response = self.client.get("/api/frame", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-pose-state"], "no_model")
        image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape, (48, 64, 3))
        self.client.post("/api/camera/stop", headers=AUTH)
        self.assertTrue(self.capture.released)
        self.assertIsNone(self.camera.jpeg)
        self.assertEqual(self.camera.status()["camera"], "stopped")
        self.assertEqual(self.client.get("/api/frame", headers=AUTH).status_code, 503)

    def test_cross_origin_denied_and_same_origin_allowed(self):
        for headers in ({"Origin": "https://attacker.invalid"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.client.post("/api/camera/start", headers=AUTH | headers).status_code, 403)
        self.factory.assert_not_called()
        self.assertEqual(self.client.post("/api/camera/start", headers=AUTH | {"Origin": "http://testserver"}).status_code, 200)

    def test_cors_not_enabled(self):
        response = self.client.options("/api/camera/start", headers={"Origin": "https://evil.invalid",
                                                                               "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_invalid_requested_bounds(self):
        for payload in ({"fps": 31}, {"width": 4000}, {"height": 1}, {"fps": "10"}, {"device": "/tmp/x"}):
            self.assertEqual(self.client.post("/api/camera/start", headers=AUTH, json=payload).status_code, 422)
        self.factory.assert_not_called()

    def test_read_failure_clears_last_frame(self):
        self.start()
        self.capture.fail = True
        wait_until(lambda: self.camera.status()["camera"] == "error")
        self.assertTrue(self.capture.released)
        self.assertIsNone(self.camera.jpeg)
        self.assertEqual(self.client.get("/api/frame", headers=AUTH).status_code, 503)

    def test_open_failure_is_honest(self):
        self.capture.opened = False
        self.client.post("/api/camera/start", headers=AUTH)
        wait_until(lambda: self.camera.status()["camera"] == "error")
        self.assertTrue(self.capture.released)
        self.assertFalse(self.camera.status()["frame_fresh"])

    def test_stale_frame_is_not_served(self):
        # Deterministic clock and state, no worker/hardware involved.
        self.camera.clock = lambda: 100
        with self.camera.lock:
            self.camera.state = "running"
            self.camera.jpeg = b"old JPEG"
            self.camera.timestamp = 97
        self.assertEqual(self.camera.status()["camera"], "stalled")
        self.assertEqual(self.client.get("/api/frame", headers=AUTH).status_code, 503)

    def test_shutdown_releases_worker(self):
        self.start()
        self.client.__exit__(None, None, None)
        self.assertTrue(self.capture.released)
        self.assertFalse(self.camera.thread.is_alive())
        # Re-enter for balanced teardown; no camera is reopened.
        self.client.__enter__()

    def test_blocked_read_stop_clears_frame_and_prevents_second_worker(self):
        entered, unblock = threading.Event(), threading.Event()
        original = self.capture.read

        def blocked_read():
            entered.set()
            unblock.wait(3)
            return original()

        self.capture.read = blocked_read
        self.client.post("/api/camera/start", headers=AUTH)
        self.assertTrue(entered.wait(1))
        try:
            with patch.object(self.camera.thread, "join"):
                response = self.client.post("/api/camera/stop", headers=AUTH)
            self.assertEqual(response.json()["camera"], "stopping")
            self.assertIsNone(self.camera.jpeg)
            self.assertEqual(self.client.get("/api/frame", headers=AUTH).status_code, 503)
            self.assertEqual(self.client.post("/api/camera/start", headers=AUTH).status_code, 409)
            self.factory.assert_called_once()
        finally:
            unblock.set()
            self.camera.thread.join(2)
        self.assertTrue(self.capture.released)
        self.assertEqual(self.camera.status()["camera"], "stopped")

    def test_snapshot_metadata_belongs_to_published_frame(self):
        with self.camera.lock:
            self.camera.state = "running"
            self.camera.jpeg = b"published"
            self.camera.timestamp = self.camera.clock()
            self.camera.frame_model = "no_people"
            self.camera.model_state = "model_error"  # Next inference failed before publication.
            self.camera.people = 0
        snapshot = self.camera.snapshot()
        self.assertEqual(snapshot[2:], ("no_people", 0))

    def test_default_factory_forces_v4l2(self):
        with patch("service.cv2.VideoCapture", return_value=self.capture) as video:
            camera = Camera(self.config)
            try:
                camera.start(StartOptions())
                wait_until(lambda: camera.status()["frame_fresh"])
            finally:
                camera.stop()
            video.assert_called_once_with("/dev/video0", cv2.CAP_V4L2)

    def test_pose_model_error_vs_no_people(self):
        for factory, expected in ((Mock(side_effect=ValueError("Unsupported pose output shape")), "model_error"),
                                  (Mock(return_value=Mock(annotate=Mock(return_value=0))), "no_people"),
                                  (Mock(return_value=Mock(annotate=Mock(side_effect=RuntimeError()))), "model_error")):
            camera = Camera(Config(TOKEN, pose_path="/local/pose.onnx"), lambda _: FakeCapture(), factory)
            try:
                camera.start(StartOptions())
                wait_until(lambda: camera.status()["frame_fresh"])
                self.assertEqual(camera.status()["model"], expected)
                self.assertTrue(camera.snapshot()[0])
            finally:
                camera.stop()


class ConfigTests(unittest.TestCase):
    def test_fail_closed_startup(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "EDGE_TOKEN"):
                with TestClient(create_app()):
                    pass

    def test_config_validation(self):
        self.assertEqual(Config.from_env({"EDGE_TOKEN": TOKEN}).device, "/dev/video0")
        for override in ({"EDGE_TOKEN": "short"}, {"EDGE_TOKEN": " " * 32},
                         {"EDGE_CAMERA": "/dev/video0/../etc"}, {"EDGE_CAMERA": "http://camera"},
                         {"EDGE_WIDTH": "1921"}, {"EDGE_FPS": "0"}, {"EDGE_FPS": "1.5"},
                         {"EDGE_FRESHNESS_MS": "10000"}, {"POSE_KEYPOINT_PERCENT": "101"}):
            with self.assertRaises(ValueError):
                Config.from_env({"EDGE_TOKEN": TOKEN} | override)


if __name__ == "__main__":
    unittest.main()
