"""Diagnostic CPU-only adapter for raw, non-end-to-end YOLOv8 pose ONNX."""
from pathlib import Path

import cv2
import numpy as np

SIZE = 640
# COCO 17-point topology, zero-based indices.
LIMBS = ((5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11),
         (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16))


def letterbox(image):
    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        raise ValueError("Empty input image")
    scale = min(SIZE / w, SIZE / h)
    nw, nh = round(w * scale), round(h * scale)
    left, top = (SIZE - nw) // 2, (SIZE - nh) // 2
    canvas = np.full((SIZE, SIZE, 3), 114, dtype=np.uint8)
    canvas[top:top + nh, left:left + nw] = cv2.resize(image, (nw, nh))
    # Actual rounded x/y resize ratios give exact coordinate restoration.
    return canvas, (nw / w, nh / h, left, top, w, h)


def restore(points, transform):
    sx, sy, left, top, w, h = transform
    result = np.array(points, dtype=np.float32, copy=True)
    result[..., 0] = np.clip((result[..., 0] - left) / sx, 0, w - 1)
    result[..., 1] = np.clip((result[..., 1] - top) / sy, 0, h - 1)
    return result


def decode(output, transform, score_threshold=0.35, keypoint_threshold=0.5):
    output = np.asarray(output)
    if output.shape != (1, 56, 8400):
        raise ValueError(f"Unsupported pose output shape {output.shape}; require raw [1,56,8400]")
    if not np.isfinite(output).all():
        raise ValueError("Pose output contains non-finite values")
    rows = output[0].T
    if np.any((rows[:, 4] < 0) | (rows[:, 4] > 1)) or np.any(
        (rows[:, 7::3] < 0) | (rows[:, 7::3] > 1)
    ):
        raise ValueError("Expected probability scores, not logits")
    rows = rows[(rows[:, 4] >= score_threshold) & (rows[:, 2] > 0) & (rows[:, 3] > 0)]
    if not len(rows):
        return []
    # NMS before clamping preserves true overlap at the image boundary.
    boxes = np.column_stack((rows[:, 0] - rows[:, 2] / 2,
                             rows[:, 1] - rows[:, 3] / 2, rows[:, 2:4]))
    indices = cv2.dnn.NMSBoxes(boxes.tolist(), rows[:, 4].tolist(), score_threshold, 0.45)
    people = []
    for i in np.asarray(indices, dtype=int).reshape(-1):
        x, y, w, h = boxes[i]
        box = restore([[x, y], [x + w, y + h]], transform)
        if box[1, 0] <= box[0, 0] or box[1, 1] <= box[0, 1]:
            continue
        points = rows[i, 5:].reshape(17, 3).copy()
        # Do not draw keypoints predicted in padding, even after clamping.
        sx, sy, left, top, iw, ih = transform
        inside = ((points[:, 0] >= left) & (points[:, 0] < left + sx * iw)
                  & (points[:, 1] >= top) & (points[:, 1] < top + sy * ih))
        points[:, :2] = restore(points[:, :2], transform)
        confident = (points[:, 2] >= keypoint_threshold) & inside
        people.append((box, points, confident))
    return people


class PoseBackend:
    def __init__(self, path, keypoint_threshold=0.5):
        model = Path(path)
        if not model.is_absolute() or model.suffix.lower() != ".onnx" or not model.is_file():
            raise ValueError("POSE_ONNX must be an absolute existing local .onnx file")
        self.net = cv2.dnn.readNetFromONNX(str(model))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.keypoint_threshold = keypoint_threshold
        # Validate the actual forward contract, not a guessed model filename.
        self._infer(np.zeros((SIZE, SIZE, 3), np.uint8))

    def _infer(self, image):
        padded, transform = letterbox(image)
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (SIZE, SIZE), swapRB=True, crop=False)
        self.net.setInput(blob)
        outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        if len(outputs) != 1:
            raise ValueError("Require one raw YOLOv8 pose output, no end-to-end/NMS export")
        return decode(outputs[0], transform, keypoint_threshold=self.keypoint_threshold)

    def annotate(self, image):
        people = self._infer(image)
        for box, points, confident in people:
            p0, p1 = box.astype(int)
            cv2.rectangle(image, tuple(p0), tuple(p1), (40, 210, 140), 2)
            for a, b in LIMBS:
                if confident[a] and confident[b]:
                    cv2.line(image, tuple(points[a, :2].astype(int)),
                             tuple(points[b, :2].astype(int)), (40, 210, 140), 2)
            for point, visible in zip(points, confident):
                if visible:
                    cv2.circle(image, tuple(point[:2].astype(int)), 3, (0, 210, 255), -1)
        return len(people)
