from __future__ import annotations

import unittest

from parking_web.export_excel import _best_frame


class ExportFrameSelectionTests(unittest.TestCase):
    def test_plate_frame_prefers_combined_detection_quality_and_ocr(self):
        event = {"event_id": "EVT-1", "track_id": 7}
        plate = {"observations": [
            {"timestamp_ms": 100, "plate_confidence": .9,
             "quality": {"score": .1}, "plate_box": [1, 1, 2, 2]},
            {"timestamp_ms": 200, "plate_confidence": .8,
             "quality": {"score": .9}, "ocr_confidence": .9,
             "vehicle_box": [0, 0, 8, 8], "plate_box": [3, 3, 5, 5]},
            {"timestamp_ms": 900, "plate_confidence": 1,
             "quality": {"score": 1}},
        ]}
        self.assertEqual(_best_frame(event, 0, 500, plate, []),
                         (200, [0, 0, 8, 8], [3, 3, 5, 5]))

    def test_without_plate_uses_same_track_and_manual_uses_midpoint(self):
        event = {"event_id": "EVT-1", "track_id": 7}
        detections = [
            {"timestamp_ms": 100, "detections": [
                {"track_id": 7, "confidence": .4, "box": [1, 1, 2, 2]},
                {"track_id": 8, "confidence": .99, "box": [9, 9, 9, 9]}]},
            {"timestamp_ms": 200, "detections": [
                {"track_id": 7, "confidence": .8, "box": [3, 3, 4, 4]}]},
        ]
        self.assertEqual(_best_frame(event, 0, 500, None, detections),
                         (200, [3, 3, 4, 4], None))
        self.assertEqual(_best_frame(None, 0, 500, None, detections),
                         (250, None, None))


if __name__ == "__main__":
    unittest.main()
