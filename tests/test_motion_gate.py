from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from parking_step1.config import CameraConfig, RunConfig
from parking_step1.events import Detection
from parking_step1.evaluation import load_jsonl
from parking_step1.motion_gate import MotionGate
from parking_step1.pipeline import run_pipeline


class MotionGateTests(unittest.TestCase):
    def test_roi_ignores_motion_outside_and_accepts_motion_inside(self):
        gate = MotionGate(160, 90, [[0, 0], [.5, 0], [.5, 1], [0, 1]],
                          input_width=80, min_area_fraction=.01,
                          warmup_ms=0, hold_ms=0, probe_ms=10000, sample_fps=10)
        blank = np.zeros((90, 160, 3), dtype=np.uint8)
        gate.should_detect(blank, 0, has_open_track=False)
        self.assertFalse(gate.should_detect(blank, 100, has_open_track=False))
        outside = blank.copy()
        outside[20:60, 110:150] = 255
        self.assertFalse(gate.should_detect(outside, 200, has_open_track=False))
        inside = blank.copy()
        inside[20:60, 10:50] = 255
        self.assertTrue(gate.should_detect(inside, 300, has_open_track=False))

    def test_idle_probe_and_open_track_keep_detector_alive(self):
        gate = MotionGate(160, 90, [], input_width=80, min_area_fraction=.01,
                          warmup_ms=300, hold_ms=200, probe_ms=1000, sample_fps=10)
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        decisions = [gate.should_detect(frame, timestamp, has_open_track=False)
                     for timestamp in range(0, 2000, 100)]
        self.assertTrue(all(decisions[:3]))
        self.assertFalse(all(decisions[3:]))
        self.assertTrue(decisions[12])  # one idle heartbeat after the warmup
        self.assertTrue(gate.should_detect(frame, 2100, has_open_track=True))

    def test_moving_vehicle_keeps_event_and_skips_idle_yolo_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "motion.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 90))
            self.assertTrue(writer.isOpened())
            for index in range(100):
                frame = np.zeros((90, 160, 3), dtype=np.uint8)
                if 30 <= index < 60:
                    x = 5 + (index - 30) * 4
                    cv2.rectangle(frame, (x, 40), (x + 22, 69), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()

            class BrightVehicleDetector:
                def __init__(self):
                    self.calls = 0

                def infer(self, frame):
                    self.calls += 1
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    mask = np.uint8(gray > 150)
                    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
                    if count < 2 or stats[1, cv2.CC_STAT_AREA] < 100:
                        return []
                    x, y, w, h, _ = stats[1]
                    return [Detection(1, "car", .9, (float(x), float(y),
                                                       float(x+w), float(y+h)))]

            common = dict(sample_fps=10, candidate_hits=2, min_motion_distance=.01,
                          make_clips=False, pre_seconds=1.5, post_seconds=2)
            camera = CameraConfig("cam", "lane", "ENTRY", crossing_line=[[.5, 0], [.5, 1]])
            baseline_detector = BrightVehicleDetector()
            baseline = run_pipeline(RunConfig(camera, str(source), str(root / "baseline"),
                                              **common), detector=baseline_detector)
            gated_detector = BrightVehicleDetector()
            gated = run_pipeline(RunConfig(camera, str(source), str(root / "gated"),
                                           motion_gate_enabled=True, **common),
                                 detector=gated_detector)
            baseline_events = load_jsonl(Path(baseline["run_dir"]) / "events.jsonl")
            gated_events = load_jsonl(Path(gated["run_dir"]) / "events.jsonl")
            self.assertEqual(len(baseline_events), 1)
            self.assertEqual([(e["start_ms"], e["end_ms"], e["crossed"])
                              for e in baseline_events],
                             [(e["start_ms"], e["end_ms"], e["crossed"])
                              for e in gated_events])
            self.assertEqual(baseline_detector.calls, 100)
            self.assertLess(gated_detector.calls, baseline_detector.calls)
            self.assertEqual(gated["run"]["detector_frames"], gated_detector.calls)
            records = load_jsonl(Path(gated["run_dir"]) / "detections.jsonl")
            self.assertEqual(len(records), 100)
            self.assertEqual(sum(record["detector_skipped"] for record in records),
                             gated["run"]["motion_gate"]["skipped_frames"])
            self.assertTrue(any(record["detector_skipped"] for record in records[:30]))
            self.assertTrue(any(record["detector_skipped"] for record in records[60:]))

    def test_invalid_settings_and_opencv_failure_fall_back_to_yolo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
            for _ in range(20):
                writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.release()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source),
                               str(root / "out"), motion_gate_enabled=True,
                               make_clips=False)
            config.motion_gate_probe_seconds = 0
            with self.assertRaisesRegex(ValueError, "MOG2"):
                config.validate()
            config.motion_gate_probe_seconds = .5
            legacy = config.to_dict()
            for key in list(legacy):
                if key.startswith("motion_gate_"):
                    del legacy[key]
            self.assertFalse(RunConfig.from_dict(legacy).motion_gate_enabled)

            class EmptyDetector:
                calls = 0

                def infer(self, _frame):
                    self.calls += 1
                    return []

            detector = EmptyDetector()
            with patch.object(MotionGate, "should_detect", side_effect=cv2.error("MOG2 failed")):
                result = run_pipeline(config, detector=detector)
            self.assertEqual(detector.calls, 20)
            self.assertEqual(result["run"]["motion_gate"]["skipped_frames"], 0)
            self.assertIn("MOG2 failed", result["run"]["motion_gate"]["fallback_error"])


if __name__ == "__main__":
    unittest.main()
