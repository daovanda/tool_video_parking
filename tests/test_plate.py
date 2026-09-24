from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from parking_step1.config import CameraConfig, RunConfig
from parking_step1.plate import consensus, normalize_plate, run_plate_enrichment, select_diverse


class FakePlateDetector:
    def __init__(self):
        self.crop_shapes = []

    def detect(self, crop):
        self.crop_shapes.append(crop.shape)
        return [{"box": [2, 2, 18, 9], "confidence": .8}]


class FakeOCR:
    def recognize(self, crop):
        return "59-A 12345", .9


class PlateTests(unittest.TestCase):
    def test_bicycle_writes_not_applicable_without_detector_or_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "raw.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            writer.write(np.zeros((24, 32, 3), dtype=np.uint8)); writer.release()
            run_dir = root / "run"; run_dir.mkdir()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source), str(root))
            (run_dir / "run.json").write_text(json.dumps({"run_id": "r", "source": {
                "uri": str(source), "width": 32, "height": 24}, "config": config.to_dict()}))
            event = {"event_id": "b1", "clip_id": "c1", "track_id": 1,
                     "vehicle_type": "bicycle", "start_ms": 0, "end_ms": 0,
                     "camera_id": "cam", "lane_id": "lane", "direction": "ENTRY"}
            (run_dir / "events.jsonl").write_text(json.dumps(event) + "\n")
            (run_dir / "detections.jsonl").write_text("")
            with patch("parking_step1.plate.YoloPlateDetector",
                       side_effect=AssertionError("bicycle must skip detector")), \
                 patch("parking_step1.plate.PaddlePlateOCR",
                       side_effect=AssertionError("bicycle must skip OCR")):
                record = run_plate_enrichment(run_dir, config)[0]
            self.assertEqual(record["plate_applicability"], "not_applicable")
            self.assertEqual(record["plate_presence"], "absent_by_vehicle_type")
            self.assertIsNone(record["consensus"])
            updated_run = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(updated_run["schema_version"], "0.9.0")

    def test_normalize_and_consensus(self):
        self.assertEqual(normalize_plate("59-A 123.45"), "59A12345")
        items = [{"timestamp_ms": t, "quality": {"score": q},
                  "ocr_text_normalized": value, "ocr_confidence": .9}
                 for t, q, value in [(0, .8, "59A12345"), (500, .7, "59A12345"),
                                     (800, .4, "59A12346")]]
        self.assertEqual(consensus(items)["text"], "59A12345")
        self.assertEqual(consensus(items)["support_count"], 2)
        self.assertEqual(len(select_diverse(items, 3, 400)), 2)

    def test_enrich_reads_only_event_track_and_maps_plate_box(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (80, 60))
            self.assertTrue(writer.isOpened())
            for _ in range(10):
                writer.write(np.full((60, 80, 3), 100, dtype=np.uint8))
            writer.release()
            run_dir = root / "run"
            run_dir.mkdir()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source), str(root))
            (run_dir / "run.json").write_text(json.dumps({"run_id": "r1", "source": {
                "uri": str(source), "width": 80, "height": 60}, "config": config.to_dict()}))
            event = {"event_id": "e1", "clip_id": "c1", "track_id": 7, "start_ms": 0,
                     "end_ms": 900, "camera_id": "cam", "lane_id": "lane", "direction": "ENTRY"}
            (run_dir / "events.jsonl").write_text(json.dumps(event) + "\n")
            records = [{"frame_index": i, "timestamp_ms": i * 100, "detections": [
                {"track_id": 7, "box": [10, 10, 40, 40]},
                {"track_id": 8, "box": [45, 10, 75, 40]}]} for i in range(10)]
            (run_dir / "detections.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
            detector = FakePlateDetector()
            output = run_plate_enrichment(run_dir, config, detector=detector, ocr=FakeOCR())
            self.assertEqual(len(detector.crop_shapes), 10)
            self.assertEqual(output[0]["consensus"]["text"], "59A12345")
            self.assertEqual(len(output[0]["selected_observations"]), 4)
            self.assertEqual(output[0]["observations"][0]["plate_box"], [8, 8, 24, 15])
            self.assertTrue((run_dir / "plate_observations.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
