from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QAbstractItemView

from parking_step1.gui import MainWindow


class GuiPlaybackTests(unittest.TestCase):
    def test_invalid_drawn_line_is_warned_and_removed_immediately(self):
        window = MainWindow()
        window.canvas.roi = [[.2, .2], [.8, .2], [.8, .8], [.2, .8]]
        window.canvas.line = [[.1, .05], [.9, .05]]
        with patch("parking_step1.gui.QMessageBox.warning") as warning:
            window._validate_drawn_geometry()
        self.assertEqual(window.canvas.line, [])
        warning.assert_called_once()
        self.assertIn("ngoài ROI", window.status.text())
        window.close()

    def test_bicycle_gt_disables_plate_and_conditions(self):
        window = MainWindow()
        window._prefill_gt_from_event({"event_id": "B-1", "track_id": 2,
                                       "start_ms": 0, "end_ms": 100,
                                       "vehicle_type": "bicycle", "crossed": True})
        record = window._collect_gt_record()
        self.assertEqual(record["vehicle_type"], "bicycle")
        self.assertEqual(record["condition_status"], "not_applicable")
        self.assertIsNone(record["plate_readable"])
        self.assertIsNone(record["plate_text"])
        self.assertFalse(window.gt_text.isEnabled())
        self.assertFalse(window.condition_status.isEnabled())
        self.assertFalse(window.gt_readability.isEnabled())
        self.assertEqual(record["annotation_schema_version"], "0.6.0")
        window.gt_events = [record]
        window._load_gt_record(record, 0)
        reopened = window._collect_gt_record()
        self.assertEqual(reopened["condition_status"], "not_applicable")
        self.assertIsNone(reopened["plate_readable"])
        window.gt_type.setCurrentText("car")
        self.assertTrue(window.gt_text.isEnabled())
        self.assertTrue(window.condition_status.isEnabled())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_plate_consensus_prefills_gt_with_provenance(self):
        window = MainWindow()
        window.plate_records = {"EVT-1": {"consensus": {
            "text": "59A12345", "confidence": .85}}}
        window._prefill_gt_from_event({"event_id": "EVT-1", "track_id": 7,
                                       "start_ms": 100, "end_ms": 300,
                                       "vehicle_type": "car", "crossed": True})
        self.assertEqual(window.gt_text.text(), "59A12345")
        self.assertEqual(window.gt_suggestions["plate_text"]["source"], "plate_ocr")

    def test_condition_suggestion_prefills_readability_and_root_cause(self):
        window = MainWindow()
        window.condition_records = {"EVT-1": {
            "conditions": ["lighting_issue"],
            "plate_readable": False,
            "condition_status": "unreadable",
            "evidence_timestamps_ms": [150]}}
        window._prefill_gt_from_event({"event_id": "EVT-1", "track_id": 7,
                                       "start_ms": 100, "end_ms": 300,
                                       "vehicle_type": "car", "crossed": True})
        record = window._collect_gt_record()
        self.assertEqual(record["conditions"], ["lighting_issue"])
        self.assertEqual(record["condition_status"], "unreadable")
        self.assertFalse(record["plate_readable"])
        self.assertEqual(record["plate_readability"], "unreadable")
        self.assertEqual(record["suggestions"]["conditions"]["source"], "cv_vlm")
        window._set_conditions([], "good")
        self.assertEqual(window._collect_gt_record()["conditions"], [])
        self.assertEqual(window._collect_gt_record()["condition_status"], "good")
        self.assertTrue(window._collect_gt_record()["plate_readable"])
        window.gt_readability.setCurrentIndex(window.gt_readability.findData("unreadable"))
        self.assertEqual(window._collect_gt_record()["plate_readability"], "single_frame_readable")
        self.assertTrue(all(not check.isEnabled() for check in window.condition_checks.values()))

    def test_selected_event_overlay_persists_between_sparse_samples(self):
        window = MainWindow()
        window.detection_records = [
            {"timestamp_ms": 0, "detections": [{"track_id": 7, "box": [1, 2, 10, 12]}]},
            {"timestamp_ms": 1000, "detections": [{"track_id": 7, "box": [10, 12, 20, 24]}]},
        ]
        window.active_event = {"event_id": "EVT-1", "track_id": 7,
                               "start_ms": 0, "end_ms": 2000}
        window.plate_records = {"EVT-1": {"observations": [
            {"timestamp_ms": 1000, "plate_box": [4, 5, 8, 7],
             "plate_confidence": .8, "ocr_text_normalized": "59A12345"}]}}
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        window._show_clip_frame(frame, 1750)
        self.assertEqual(window.canvas.overlay_detections[-1]["track_id"], 7)
        self.assertEqual(window.canvas.overlay_detections[-1]["box"], [10, 12, 20, 24])
        self.assertEqual(window.canvas.overlay_plates[0]["ocr_text_normalized"], "59A12345")
        window._show_clip_frame(frame, 2500)
        self.assertFalse(any(item.get("track_id") == 7
                             for item in window.canvas.overlay_detections))
        self.assertEqual(window.canvas.overlay_plates, [])

    def test_event_selection_seeks_embedded_clip_to_event_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip_path = root / "clips" / "CLIP-000001.mp4"
            clip_path.parent.mkdir()
            writer = cv2.VideoWriter(str(clip_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for index in range(10):
                writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
            writer.release()
            source = root / "raw.mp4"
            source.write_bytes(b"placeholder")
            window = MainWindow()
            window.run_result = {
                "run_dir": str(root),
                "run": {"source": {"uri": str(source)},
                        "artifacts": {"detections_uri": "detections.jsonl"}},
            }
            event = {"event_id": "EVT-1", "track_id": 7, "start_ms": 400, "end_ms": 900,
                     "crossed": True,
                     "clip_id": "CLIP-000001",
                     "first_detection": {"timestamp_ms": 400, "track_id": 7,
                                          "vehicle_type": "car", "confidence": .9,
                                          "box": [4, 4, 20, 20]}}
            clip = {"clip_id": "CLIP-000001", "clip_uri": "clips/CLIP-000001.mp4",
                    "start_ms": 0, "end_ms": 1000, "actual_start_ms": 0, "actual_end_ms": 1000}
            (root / "detections.jsonl").write_text(json.dumps({
                "frame_index": 4, "timestamp_ms": 400,
                "detections": [{"track_id": 7, "vehicle_type": "car",
                                "confidence": .9, "box": [4, 4, 20, 20]}]},
                ensure_ascii=False) + "\n", encoding="utf-8")
            window.run_result["events"] = [event]
            window.run_result["clips"] = [clip]
            window.source_info = {"duration_ms": 1000}
            window._load_detection_artifact()
            window._open_selected_clip(0, 0)
            self.assertTrue(window.play_clip_button.isEnabled())
            self.assertAlmostEqual(window.clip_current_ms, 400, delta=100)
            self.assertEqual(window.gt_start, 400)
            self.assertEqual(window.gt_end, 900)
            self.assertEqual(window.annotation_event_id, "EVT-1")
            self.assertIs(window.gt_crossed.currentData(), True)
            self.assertEqual(window.gt_suggestions["crossed"]["value"], True)
            self.assertEqual(window.gt_suggestions["vehicle_type"]["source"], "model1_event")
            self.assertEqual(window.canvas.highlight_track_id, 7)
            self.assertEqual(window.canvas.overlay_detections[0]["track_id"], 7)
            self.assertIn("FRAME ĐẦU EVENT", window.canvas.overlay_title)
            window._add_gt()
            self.assertEqual(len(window.gt_events), 1)
            self.assertEqual(window.gt_events[0]["source_event_id"], "EVT-1")
            self.assertEqual(window.gt_events[0]["start_ms"], 400)
            self.assertIs(window.gt_events[0]["crossed"], True)
            columns = {key: index for index, (key, _label) in enumerate(window.GT_TABLE_COLUMNS)}
            self.assertEqual(window.gt_table.item(0, columns["crossed"]).text(), "True")
            window.close()

    def test_event_and_gt_tables_select_whole_rows(self):
        window = MainWindow()
        self.assertEqual(window.events_table.selectionBehavior(),
                         QAbstractItemView.SelectionBehavior.SelectRows)
        self.assertEqual(window.gt_table.selectionBehavior(),
                         QAbstractItemView.SelectionBehavior.SelectRows)
        window.close()

    def test_gt_table_displays_all_annotation_fields_and_none_for_missing(self):
        window = MainWindow()
        window.gt_events = [{
            "annotation_schema_version": "0.3.0",
            "gt_event_id": "GT-000001",
            "source_event_id": "EVT-1",
            "vehicle_type": "car",
            "start_ms": 100,
            "end_ms": 900,
            "crossed": False,
            "plate_text": "ZPN-720",
            "plate_readability": "single_frame_readable",
            "readable_timestamps_ms": [300, 400],
            "conditions": ["night", "glare"],
            "camera_id": "CAM01",
            "lane_id": "ENTRY_01",
            "direction": "ENTRY",
            "condition_annotation_source": "human",
            "annotation_source": "human",
            "suggestions": {"plate_text": {"value": "ZPN-720", "source": "ocr",
                                               "confidence": 0.96}},
            "source_uri": "video.mp4",
        }]
        window._fill_gt()

        self.assertEqual(window.gt_table.columnCount(), len(window.GT_TABLE_COLUMNS))
        columns = {key: index for index, (key, _label) in enumerate(window.GT_TABLE_COLUMNS)}
        self.assertEqual(window.gt_table.item(0, columns["plate_text"]).text(), "ZPN-720")
        self.assertEqual(window.gt_table.item(0, columns["plate_readability"]).text(),
                         "Đọc được 1 frame")
        self.assertEqual(window.gt_table.item(0, columns["readable_timestamps_ms"]).text(),
                         "300, 400")
        self.assertEqual(window.gt_table.item(0, columns["conditions"]).text(), "night, glare")
        self.assertEqual(window.gt_table.item(0, columns["crossed"]).text(), "False")
        self.assertIn('"source":"ocr"', window.gt_table.item(0, columns["suggestions"]).text())

        # Older/manual GT files can omit any of the newer fields.  They remain
        # visible and explicit instead of producing a misleading blank cell.
        window.gt_events = [{"gt_event_id": "GT-000002", "vehicle_type": "motorcycle"}]
        window._fill_gt()
        self.assertEqual(window.gt_table.item(0, columns["plate_text"]).text(), "None")
        self.assertEqual(window.gt_table.item(0, columns["conditions"]).text(), "None")
        self.assertEqual(window.gt_table.item(0, columns["source_event_id"]).text(), "None")
        self.assertEqual(window.gt_table.item(0, columns["crossed"]).text(), "False")
        window.close()


if __name__ == "__main__":
    unittest.main()
