import unittest
from unittest.mock import Mock, patch

import numpy as np

from pose import PoseBackend, decode, letterbox, restore


class PoseTests(unittest.TestCase):
    def test_letterbox_restore_and_clamp(self):
        image = np.zeros((360, 640, 3), np.uint8)
        padded, transform = letterbox(image)
        self.assertEqual(padded.shape, (640, 640, 3))
        self.assertEqual(transform, (1, 1, 0, 140, 640, 360))
        np.testing.assert_allclose(restore([[100, 190], [-10, 0], [700, 700]], transform),
                                   [[100, 50], [0, 0], [639, 359]])

    def test_rounded_resize_round_trip(self):
        for h, w in ((333, 1001), (1001, 333), (480, 640)):
            _, transform = letterbox(np.zeros((h, w, 3), np.uint8))
            sx, sy, left, top, _, _ = transform
            points = np.array([[0, 0], [w / 2, h / 2], [w - 1, h - 1]])
            encoded = points * [sx, sy] + [left, top]
            np.testing.assert_allclose(restore(encoded, transform), points, atol=0.0002)

    def output(self):
        output = np.zeros((1, 56, 8400), np.float32)
        row = output[0, :, 0]
        row[:5] = [320, 320, 200, 200, 0.9]
        row[5:] = np.tile([320, 320, 0.8], 17)
        return output

    def test_nms_and_keypoint_confidence(self):
        output = self.output()
        output[0, :, 1] = output[0, :, 0]
        output[0, 4, 1] = 0.8
        output[0, 7, 0] = 0.1
        people = decode(output, (1, 1, 0, 0, 640, 640))
        self.assertEqual(len(people), 1)
        box, points, confident = people[0]
        np.testing.assert_allclose(box, [[220, 220], [420, 420]])
        self.assertFalse(confident[0])
        self.assertTrue(confident[1:].all())

    def test_padding_keypoints_not_drawn(self):
        output = self.output()
        output[0, 6, 0] = 20
        people = decode(output, (1, 1, 0, 140, 640, 360))
        self.assertFalse(people[0][2][0])
        self.assertEqual(people[0][1][0, 1], 0)

    def test_invalid_shapes_and_nan(self):
        for shape in ((1, 8400, 56), (1, 57, 8400), (56, 8400), (1, 56, 2100)):
            with self.assertRaisesRegex(ValueError, "Unsupported pose output shape"):
                decode(np.zeros(shape), (1, 1, 0, 0, 640, 640))
        output = self.output()
        output[0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            decode(output, (1, 1, 0, 0, 640, 640))

    def test_no_people(self):
        self.assertEqual(decode(np.zeros((1, 56, 8400)), (1, 1, 0, 0, 640, 640)), [])

    def test_only_confident_limbs_drawn(self):
        backend = PoseBackend.__new__(PoseBackend)
        points = np.tile([100, 100, 0.9], (17, 1))
        confident = np.zeros(17, dtype=bool)
        confident[[5, 7]] = True
        backend._infer = Mock(return_value=[(np.array([[0, 0], [200, 200]]), points, confident)])
        with patch("pose.cv2.line") as line, patch("pose.cv2.circle") as circle:
            self.assertEqual(backend.annotate(np.zeros((240, 320, 3), np.uint8)), 1)
            self.assertEqual(line.call_count, 1)
            self.assertEqual(circle.call_count, 2)

    def test_requires_absolute_local_onnx(self):
        for path in ("relative.onnx", "https://example.com/model.onnx", "/missing-model.onnx"):
            with self.assertRaises(ValueError):
                PoseBackend(path)


if __name__ == "__main__":
    unittest.main()
