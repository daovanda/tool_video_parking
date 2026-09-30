from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from parking_step1.conditions import cv_measure, fuse_conditions, parse_vlm_response, run_condition_analysis
from parking_step1.config import CameraConfig, RunConfig


class FakeVLM:
    def analyze(self, _image):
        return {"plate_readable": False, "conditions": ["lighting_issue"]}


class ConditionTests(unittest.TestCase):
    def test_bicycle_skips_cv_vlm_and_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "raw.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            writer.write(np.zeros((24, 32, 3), dtype=np.uint8)); writer.release()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source), str(root))
            (root / "run.json").write_text(json.dumps({"run_id": "r", "config": config.to_dict(),
                "source": {"uri": str(source), "width": 32, "height": 24}, "artifacts": {}}))
            (root / "events.jsonl").write_text(json.dumps({"event_id": "b1", "track_id": 1,
                "vehicle_type": "bicycle", "start_ms": 0, "end_ms": 0}) + "\n")
            (root / "detections.jsonl").write_text("")
            with patch("parking_step1.conditions.QwenConditionVLM",
                       side_effect=AssertionError("bicycle must skip VLM")):
                record = run_condition_analysis(root, config)[0]
            self.assertEqual(record["condition_status"], "not_applicable")
            self.assertIsNone(record["plate_readable"])
            self.assertIsNone(record["vlm_result"])
            run = json.loads((root / "run.json").read_text())
            run["schema_version"] = "0.10.0"
            (root / "run.json").write_text(json.dumps(run))
            run_condition_analysis(root, config)
            self.assertEqual(json.loads((root / "run.json").read_text())["schema_version"],
                             "0.10.0")

    def test_tensorflow_backend_is_disabled_before_optional_models_load(self):
        self.assertEqual(os.environ.get("USE_TF"), "0")
        self.assertEqual(os.environ.get("TRANSFORMERS_NO_TF"), "1")

    def test_dark_plate_does_not_make_daylight_scene_low_light(self):
        frame = np.full((80, 120, 3), 180, dtype=np.uint8)
        frame[35:55, 40:90] = 20
        metrics = cv_measure(frame, [40, 35, 90, 55], None)
        self.assertNotIn("lighting_issue", metrics["suggested_conditions"])

    def test_reliable_ocr_suppresses_uncorroborated_vlm_tags(self):
        samples = [{"plate_box": [1, 1, 10, 10], "cv": {"suggested_conditions": []}}]
        plate = {"selected_observations": [
            {"ocr_text_normalized": "ABC123", "ocr_confidence": .94},
            {"ocr_text_normalized": "ABC123", "ocr_confidence": .91}]}
        result = fuse_conditions(samples, {"plate_readable": False,
                                          "conditions": ["lighting_issue", "plate_obstruction",
                                                         "capture_blur"]}, plate)
        self.assertEqual(result["conditions"], [])
        self.assertTrue(result["plate_readable"])
        self.assertEqual(result["condition_status"], "good")
        self.assertEqual(set(result["suppressed_conditions"]),
                         {"capture_blur", "plate_obstruction", "lighting_issue"})

    def test_parser_keeps_only_root_conditions_and_readable_forces_good(self):
        parsed = parse_vlm_response('{"plate_readable":false,'
                                    '"conditions":["lighting_issue","glare","made_up"]}')
        self.assertEqual(parsed["conditions"], ["lighting_issue"])
        readable = parse_vlm_response('```json\n{"plate_readable":true,'
                                      '"conditions":["capture_blur"]}\n``` extra')
        self.assertEqual(readable, {"plate_readable": True, "conditions": []})
        with self.assertRaises(ValueError):
            parse_vlm_response('{"plate_readable":false,"conditions":[]}')

    def test_existing_run_preserves_gt_and_writes_event_suggestions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
            self.assertTrue(writer.isOpened())
            for _ in range(5):
                writer.write(np.full((48, 64, 3), 100, dtype=np.uint8))
            writer.release()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source), str(root))
            (root / "run.json").write_text(json.dumps({
                "run_id": "run-1", "config": config.to_dict(),
                "source": {"uri": str(source), "width": 64, "height": 48}, "artifacts": {}}), encoding="utf-8")
            (root / "events.jsonl").write_text(json.dumps({
                "event_id": "event-1", "track_id": 4, "start_ms": 0, "end_ms": 400}) + "\n", encoding="utf-8")
            (root / "detections.jsonl").write_text(json.dumps({
                "frame_index": 1, "timestamp_ms": 100,
                "detections": [{"track_id": 4, "box": [1, 1, 50, 40]}]}) + "\n", encoding="utf-8")
            gt_path = root / "ground_truth_events.jsonl"
            gt_path.write_text('{"conditions": []}\n', encoding="utf-8")
            records = run_condition_analysis(root, config, vlm=FakeVLM())
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["conditions"], ["lighting_issue"])
            self.assertFalse(records[0]["plate_readable"])
            self.assertEqual(records[0]["condition_status"], "unreadable")
            self.assertEqual(records[0]["evidence_timestamps_ms"], [100])
            self.assertEqual(gt_path.read_text(encoding="utf-8"), '{"conditions": []}\n')
            run = json.loads((root / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["schema_version"], "0.9.0")
            self.assertEqual(run["artifacts"]["condition_suggestions_uri"], "condition_suggestions.jsonl")


if __name__ == "__main__":
    unittest.main()
