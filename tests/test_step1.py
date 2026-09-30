from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from parking_step1.config import CameraConfig, RunConfig
from parking_step1.batch import BatchConfig, run_batch
from parking_step1.events import Detection, EventEngine, in_line_corridor, plan_segments
from parking_step1.evaluation import evaluate_step1, load_jsonl
from parking_step1.pipeline import COCO_VEHICLE_CLASSES, materialize_clip, materialize_final_clip, run_pipeline, video_info
from parking_step1.video_frames import SequentialFrameReader


class SyntheticDetector:
    """A deterministic detector used to test the pipeline without model weights."""

    def __init__(self, detections: list[Detection]):
        self.detections = detections

    def infer(self, _frame):
        return self.detections


class Step1LogicTests(unittest.TestCase):
    def test_pipeline_grabs_unsampled_frames_without_changing_detector_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sampled.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30, (32, 24))
            for index in range(30):
                writer.write(np.full((24, 32, 3), index * 8, dtype=np.uint8))
            writer.release()
            self.assertTrue(source.is_file())

            class RecordingDetector(SyntheticDetector):
                def __init__(self):
                    super().__init__([Detection(1, "car", .9, (4, 4, 20, 20))])
                    self.frames = []

                def infer(self, frame):
                    self.frames.append(frame.copy())
                    return super().infer(frame)

            original_capture = cv2.VideoCapture
            capture_spies = []

            class CaptureSpy:
                def __init__(self, path):
                    self.capture = original_capture(path)
                    self.grab_calls = 0
                    capture_spies.append(self)

                def grab(self):
                    self.grab_calls += 1
                    return self.capture.grab()

                def __getattr__(self, name):
                    return getattr(self.capture, name)

            for sample_fps, expected_indices in ((10, list(range(0, 30, 3))),
                                                 (60, list(range(30)))):
                with self.subTest(sample_fps=sample_fps):
                    detector = RecordingDetector()
                    config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source),
                                       str(root / f"out-{sample_fps}"), sample_fps=sample_fps,
                                       candidate_hits=1, min_motion_distance=0, make_clips=False)
                    with patch("parking_step1.pipeline.cv2.VideoCapture", side_effect=CaptureSpy):
                        result = run_pipeline(config, detector=detector)
                    self.assertEqual(capture_spies[-1].grab_calls, 30 - len(expected_indices))
                    self.assertEqual(result["run"]["decoded_frames"], 30)
                    self.assertEqual(result["run"]["sampled_frames"], len(expected_indices))
                    records = load_jsonl(Path(result["run_dir"]) / "detections.jsonl")
                    self.assertEqual([row["frame_index"] for row in records], expected_indices)
                    self.assertEqual([row["timestamp_ms"] for row in records],
                                     [round(index * 1000 / 30) for index in expected_indices])
                    direct = cv2.VideoCapture(str(source))
                    try:
                        for index in range(30):
                            ok, frame = direct.read()
                            self.assertTrue(ok)
                            if index in expected_indices:
                                np.testing.assert_array_equal(detector.frames[expected_indices.index(index)], frame)
                    finally:
                        direct.release()

    def test_sequential_reader_returns_same_frames_as_direct_seek(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "frames.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            for index in range(30):
                writer.write(np.full((24, 32, 3), index * 7, dtype=np.uint8))
            writer.release()
            direct = cv2.VideoCapture(str(source))
            sequential = cv2.VideoCapture(str(source))
            reader = SequentialFrameReader(sequential)
            try:
                for index in (0, 3, 6, 20, 23, 8, 11, 29):
                    direct.set(cv2.CAP_PROP_POS_FRAMES, index)
                    ok_direct, expected = direct.read()
                    ok_sequential, actual = reader.read(index)
                    self.assertTrue(ok_direct and ok_sequential)
                    np.testing.assert_array_equal(actual, expected)
            finally:
                direct.release()
                sequential.release()

    def test_coco_vehicle_class_mapping_includes_bicycle(self):
        self.assertEqual(COCO_VEHICLE_CLASSES, {1: "bicycle", 2: "car", 3: "motorcycle"})

    def test_batch_config_keeps_camera_and_lane_ids_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"placeholder")
            first = RunConfig(CameraConfig("cam-1", "lane-1", "ENTRY"), str(source), directory)
            second = RunConfig(CameraConfig("cam-2", "lane-2", "EXIT"), str(source), directory)
            batch = BatchConfig([first, second])
            batch.validate()
            loaded = BatchConfig.from_dict(batch.to_dict())
            self.assertEqual(len(loaded.runs), 2)
            duplicate = BatchConfig([first, RunConfig(CameraConfig("cam-1", "lane-3", "EXIT"), str(source), directory)])
            with self.assertRaises(ValueError):
                duplicate.validate()

    def test_run_batch_invokes_each_camera_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"placeholder")
            batch = BatchConfig([
                RunConfig(CameraConfig("cam-1", "lane-1", "ENTRY"), str(source), directory),
                RunConfig(CameraConfig("cam-2", "lane-2", "EXIT"), str(source), directory),
            ])
            fake = lambda config, progress=None, cancel=None: {
                "run_dir": str(Path(directory) / config.camera.camera_id),
                "run": {"event_count": 1, "clip_count": 1},
            }
            with patch("parking_step1.batch.run_pipeline", side_effect=fake) as run:
                result = run_batch(batch)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(result["event_count"], 2)
            self.assertEqual(result["clip_count"], 2)

    def test_camera_config_and_round_trip(self):
        camera = CameraConfig("cam-1", "lane-1", "ENTRY", [[0, 0], [1, 0], [1, 1]], [[.5, 0], [.5, 1]])
        camera.validate()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"placeholder")
            config = RunConfig(camera, str(source), directory)
            path = Path(directory) / "config.json"
            config.save(path)
            loaded = RunConfig.load(path)
            self.assertEqual(loaded.to_dict(), config.to_dict())

    def test_invalid_crossing_line_is_rejected(self):
        with self.assertRaises(ValueError):
            CameraConfig("cam", "lane", "ENTRY", crossing_line=[[.5, .5]]).validate()
        with self.assertRaises(ValueError):
            CameraConfig("cam", "lane", "ENTRY", crossing_line=[[.5, .5], [.5, .5]]).validate()

    def test_line_must_intersect_or_lie_inside_roi(self):
        roi = [[.2, .2], [.8, .2], [.8, .8], [.2, .8]]
        CameraConfig("cam", "lane", "ENTRY", roi, [[.1, .5], [.9, .5]]).validate()
        CameraConfig("cam", "lane", "ENTRY", roi, [[.3, .3], [.7, .7]]).validate()
        CameraConfig("cam", "lane", "ENTRY", roi, [[.1, .2], [.2, .2]]).validate()
        with self.assertRaisesRegex(ValueError, "hoàn toàn ngoài ROI"):
            CameraConfig("cam", "lane", "ENTRY", roi, [[.1, .05], [.9, .05]]).validate()

    def test_event_engine_detects_crossing_and_closes(self):
        engine = EventEngine([], [[.5, 0], [.5, 1]], 100, 100, candidate_hits=2, grace_ms=100,
                              line_gate_margin=1.0)
        engine.update(0, [Detection(7, "car", .8, (10, 10, 30, 30))])
        engine.update(100, [Detection(7, "car", .9, (70, 10, 90, 30))])
        engine.update(250, [])
        event = engine.flush()[0]
        self.assertEqual(event["state"], "CLOSED")
        self.assertTrue(event["crossed"])
        self.assertEqual(event["crossing_ms"], 100)
        self.assertAlmostEqual(event["confidence_mean"], .85)

    def test_line_corridor_filters_background_tracks_when_roi_is_empty(self):
        line = [[.2, .6], [.8, .6]]
        self.assertTrue(in_line_corridor((50, 60), line, 100, 100, .12))
        self.assertFalse(in_line_corridor((5, 60), line, 100, 100, .12))
        self.assertFalse(in_line_corridor((50, 20), line, 100, 100, .12))
        engine = EventEngine([], line, 100, 100, candidate_hits=1, grace_ms=100, line_gate_margin=.12)
        engine.update(0, [Detection(1, "car", .9, (40, 50, 60, 60)),
                         Detection(2, "car", .9, (-5, 50, 5, 60))])
        self.assertEqual(len(engine.open), 1)
        # The corridor gates new tracks only; an opened track remains visible
        # while it departs from the line so its event is not cut short.
        engine.update(100, [Detection(1, "car", .9, (40, 10, 60, 20))])
        self.assertEqual(engine.open[1]["end_ms"], 100)

    def test_roi_and_line_use_intersection_as_opening_gate(self):
        roi = [[0, 0], [1, 0], [1, 1], [0, 1]]
        line = [[.2, .6], [.8, .6]]
        engine = EventEngine(roi, line, 100, 100, candidate_hits=1, grace_ms=100,
                             line_gate_margin=.1, min_motion_distance=0)
        engine.update(0, [Detection(1, "car", .9, (40, 10, 60, 20)),
                          Detection(2, "car", .9, (40, 50, 60, 60))])
        self.assertNotIn(1, engine.open)
        self.assertIn(2, engine.open)

    def test_stationary_vehicle_is_discarded_with_full_frame_roi_and_roi_line(self):
        configurations = [
            ([], []),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], []),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], [[.5, 0], [.5, 1]]),
        ]
        for roi, line in configurations:
            with self.subTest(roi=bool(roi), line=bool(line)):
                engine = EventEngine(roi, line, 100, 100, candidate_hits=2, grace_ms=100,
                                     min_motion_distance=.02, motion_window_ms=500)
                for timestamp in (0, 100, 200, 300):
                    engine.update(timestamp, [Detection(1, "car", .9, (20, 20, 40, 40))])
                engine.update(500, [])
                self.assertEqual(engine.flush(), [])

    def test_moving_vehicle_activates_then_may_stop_without_splitting_event(self):
        roi = [[0, 0], [1, 0], [1, 1], [0, 1]]
        engine = EventEngine(roi, [], 100, 100, candidate_hits=2, grace_ms=300,
                             min_motion_distance=.02, motion_window_ms=500)
        engine.update(0, [Detection(1, "car", .8, (10, 20, 30, 40))])
        engine.update(100, [Detection(1, "car", .9, (20, 20, 40, 40))])
        engine.update(200, [Detection(1, "car", .9, (20, 20, 40, 40))])
        engine.update(300, [Detection(1, "car", .9, (20, 20, 40, 40))])
        engine.update(700, [])
        event = engine.flush()[0]
        self.assertTrue(event["motion_confirmed"])
        self.assertGreaterEqual(event["motion_distance"], .1)
        self.assertEqual(event["start_ms"], 0)
        self.assertEqual(event["end_ms"], 300)

    def test_plan_segments_merges_only_nearby_spans(self):
        events = [{"event_id": "EVT-1", "start_ms": 1000, "end_ms": 2000},
                  {"event_id": "EVT-2", "start_ms": 2300, "end_ms": 2600},
                  {"event_id": "EVT-3", "start_ms": 5000, "end_ms": 5200}]
        segments = plan_segments(events, 10_000, 100, 100, 500)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["event_ids"], ["EVT-1", "EVT-2"])
        self.assertEqual(segments[0]["clip_id"], "CLIP-000001")

    def test_evaluation_metrics_have_expected_denominators(self):
        gt = [{"gt_event_id": "GT-1", "camera_id": "cam-1", "start_ms": 100, "end_ms": 900,
               "readable_timestamps_ms": [500]}]
        events = [{"event_id": "EVT-1", "camera_id": "cam-1", "start_ms": 120, "end_ms": 850}]
        clips = [{"clip_id": "CLIP-1", "start_ms": 0, "end_ms": 1000}]
        result = evaluate_step1(gt, events, clips, 2000)
        self.assertEqual(result["matched_event_count"], 1)
        self.assertEqual(result["event_recall"], 1.0)
        self.assertEqual(result["event_detection_precision"], 1.0)
        self.assertEqual(result["readable_retention_at_1"], 1.0)

    def test_evaluator_matches_and_reports_bicycle_separately(self):
        gt = [{"gt_event_id": "GT-B", "camera_id": "cam", "vehicle_type": "bicycle",
               "start_ms": 0, "end_ms": 1000, "readable_timestamps_ms": []}]
        events = [
            {"event_id": "E-C", "camera_id": "cam", "vehicle_type": "car",
             "start_ms": 0, "end_ms": 1000},
            {"event_id": "E-B", "camera_id": "cam", "vehicle_type": "bicycle",
             "start_ms": 0, "end_ms": 1000},
        ]
        result = evaluate_step1(gt, events, [{"start_ms": 0, "end_ms": 1000}], 1000)
        self.assertEqual(result["matched_event_count"], 1)
        self.assertEqual(result["by_vehicle_type"]["bicycle"]["event_recall"], 1.0)
        self.assertEqual(result["by_vehicle_type"]["car"]["matched_event_count"], 0)

    def test_pipeline_preserves_bicycle_event_and_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bicycle.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            for _ in range(3):
                writer.write(np.zeros((24, 32, 3), dtype=np.uint8))
            writer.release()
            config = RunConfig(CameraConfig("cam", "lane", "ENTRY"), str(source), str(root / "out"),
                               candidate_hits=1, min_motion_distance=0, make_clips=False,
                               plate_ocr_enabled=True, condition_analysis_enabled=True)
            result = run_pipeline(config, detector=SyntheticDetector(
                [Detection(5, "bicycle", .41, (3, 3, 22, 22))]))
            self.assertEqual(result["events"][0]["vehicle_type"], "bicycle")
            detections = load_jsonl(Path(result["run_dir"]) / "detections.jsonl")
            self.assertEqual(detections[0]["detections"][0]["vehicle_type"], "bicycle")
            self.assertEqual(result["plate_observations"][0]["plate_applicability"], "not_applicable")
            self.assertEqual(result["condition_suggestions"][0]["condition_status"], "not_applicable")
            runtime = json.loads((Path(result["run_dir"]) / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["schema_version"], "0.4.0")
            self.assertIsNotNone(runtime["ocr_elapsed_seconds"])
            self.assertIsNotNone(runtime["condition_elapsed_seconds"])
            self.assertGreaterEqual(runtime["elapsed_seconds"], runtime["core_elapsed_seconds"])
            self.assertIn("decode_seconds", runtime["core_profile_seconds"])
            self.assertIn("frame_seek_decode_seconds", runtime["ocr_profile_seconds"])
            self.assertIn("vlm_generation_seconds", runtime["condition_profile_seconds"])

    def test_pipeline_writes_decodable_clip_and_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for index in range(10):
                writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
            writer.release()
            config = RunConfig(CameraConfig("cam-1", "lane-1", "ENTRY"), str(source), str(root / "out"),
                               sample_fps=10, candidate_hits=1, min_motion_distance=0,
                               grace_seconds=.2, pre_seconds=.1,
                               post_seconds=.1, make_clips=True)
            result = run_pipeline(config, detector=SyntheticDetector(
                [Detection(1, "car", .9, (4, 4, 20, 20))]))
            run_dir = Path(result["run_dir"])
            self.assertEqual(result["run"]["event_count"], 1)
            self.assertTrue((run_dir / "run.json").is_file())
            runtime = json.loads((run_dir / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["scope"], "full_pipeline")
            self.assertGreaterEqual(runtime["elapsed_seconds"], 0)
            self.assertIsNone(runtime["ocr_elapsed_seconds"])
            self.assertIsNone(runtime["condition_elapsed_seconds"])
            events = load_jsonl(run_dir / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["track_artifact_uri"], "detections.jsonl")
            self.assertEqual(events[0]["first_detection"]["track_id"], 1)
            detections = load_jsonl(run_dir / "detections.jsonl")
            self.assertEqual(len(detections), 10)
            self.assertEqual(detections[0]["detections"][0]["track_id"], 1)
            run_manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["artifacts"]["detections_uri"], "detections.jsonl")
            self.assertEqual(run_manifest["artifacts"]["final_clip"]["uri"], "clips/clip_final.mp4")
            self.assertEqual(run_manifest["artifacts"]["final_clip"]["clip_count"], 1)
            self.assertTrue((run_dir / "clips" / "clip_final.mp4").is_file())
            self.assertEqual((run_dir / "clips" / "clip_final.mp4").read_bytes(),
                             (run_dir / "clips" / "CLIP-000001.mp4").read_bytes())
            clips = load_jsonl(run_dir / "clips.jsonl")
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]["quality_status"], "valid")
            cap = cv2.VideoCapture(str(run_dir / clips[0]["clip_uri"]))
            self.assertTrue(cap.isOpened())
            self.assertTrue(cap.read()[0])
            cap.release()
            self.assertGreater(video_info(source)["duration_ms"], 0)
            json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    def test_final_clip_concatenates_segments_in_source_time_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for index in range(50):
                color = (0, 0, 220) if index < 20 else (0, 220, 0)
                writer.write(np.full((24, 32, 3), color, dtype=np.uint8))
            writer.release()
            segments = [
                {"clip_id": "CLIP-000002", "start_ms": 3000, "end_ms": 4000},
                {"clip_id": "CLIP-000001", "start_ms": 500, "end_ms": 1500},
            ]
            result = materialize_final_clip(source, root / "clip_final.mp4", segments, video_info(source))
            self.assertEqual(result["quality_status"], "valid")
            self.assertEqual(result["frame_count"], 20)
            self.assertEqual([item["clip_id"] for item in result["timeline_mapping"]],
                             ["CLIP-000001", "CLIP-000002"])
            self.assertEqual(result["timeline_mapping"][0]["final_start_ms"], 0)
            self.assertEqual(result["timeline_mapping"][1]["final_start_ms"], 1000)
            capture = cv2.VideoCapture(str(root / "clip_final.mp4"))
            colors = []
            for frame_index in (0, 10):
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                self.assertTrue(ok)
                colors.append(frame.mean(axis=(0, 1)))
            capture.release()
            self.assertGreater(colors[0][2], colors[0][1])
            self.assertGreater(colors[1][1], colors[1][2])

    def test_ffmpeg_partial_clips_concat_without_reencoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            for index in range(50):
                writer.write(np.full((24, 32, 3), index * 4, dtype=np.uint8))
            writer.release()
            info = video_info(source)
            segments = [
                {"clip_id": "late", "start_ms": 3000, "end_ms": 4000},
                {"clip_id": "early", "start_ms": 500, "end_ms": 1500},
            ]
            files = {}
            for segment in segments:
                path = root / f"{segment['clip_id']}.mp4"
                result = materialize_clip(source, path, segment["start_ms"], segment["end_ms"], info)
                self.assertEqual(result["encoder"], "ffmpeg_libx264")
                self.assertEqual(result["frame_count"], 10)
                segment["output_frame_count"] = result["frame_count"]
                files[segment["clip_id"]] = path
            final = root / "final.mp4"
            result = materialize_final_clip(source, final, segments, info, segment_files=files)
            self.assertEqual(result["frame_count"], 20)
            self.assertEqual([item["clip_id"] for item in result["timeline_mapping"]],
                             ["early", "late"])
            cap = cv2.VideoCapture(str(final))
            self.assertEqual(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 20)
            self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FPS), 10, places=2)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, first = cap.read()
            self.assertTrue(ok)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 10)
            ok, second = cap.read()
            self.assertTrue(ok)
            cap.release()
            self.assertLess(first.mean(), second.mean())

    def test_clip_export_falls_back_when_ffmpeg_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            for index in range(20):
                writer.write(np.full((24, 32, 3), index * 5, dtype=np.uint8))
            writer.release()
            with patch("parking_step1.pipeline._ffmpeg_executable", return_value=None):
                result = materialize_clip(source, root / "partial.mp4", 500, 1500,
                                          video_info(source))
            self.assertEqual(result["encoder"], "opencv_mp4v")
            self.assertEqual(result["frame_count"], 10)
            self.assertTrue(result["decodable"])

    def test_clip_export_stops_when_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            for _ in range(10):
                writer.write(np.zeros((24, 32, 3), dtype=np.uint8))
            writer.release()
            info = video_info(source)
            with self.assertRaisesRegex(RuntimeError, "Đã hủy xuất clip"):
                materialize_clip(source, root / "clip.mp4", 0, 1000, info, cancel=lambda: True)
            with self.assertRaisesRegex(RuntimeError, "Đã hủy xuất clip final"):
                materialize_final_clip(source, root / "final.mp4",
                    [{"clip_id": "CLIP-000001", "start_ms": 0, "end_ms": 1000}], info,
                    cancel=lambda: True)


if __name__ == "__main__":
    unittest.main()
