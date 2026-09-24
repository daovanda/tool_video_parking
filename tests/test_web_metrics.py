from __future__ import annotations

import unittest

from parking_web.metrics import evaluate_review


class ReviewMetricsTests(unittest.TestCase):
    def test_event_ocr_and_condition_scores_with_missed_vehicle(self):
        common = {"camera_id": "CAM01", "lane_id": "ENTRY_01", "direction": "ENTRY",
                  "vehicle_type": "car"}
        gt = [
            {**common, "event_id": "EVT-1", "source_event_id": "EVT-1",
             "start_ms": 1000, "end_ms": 2000, "plate_text": "59A-12345",
             "plate_readable": True, "condition_status": "unreadable",
             "conditions": ["lighting_issue"]},
            {**common, "event_id": "GT-000001", "source_event_id": None,
             "start_ms": 4000, "end_ms": 5000, "plate_text": None,
             "plate_readable": False, "condition_status": "good", "conditions": []},
        ]
        events = [{**common, "event_id": "EVT-1", "start_ms": 1100, "end_ms": 2100,
                   "suggestion": {"plate_text": "59A12346", "condition_status": "unreadable",
                                  "conditions": ["capture_blur"]}}]
        result = evaluate_review(gt, events)
        self.assertEqual(result["events"]["recall"], .5)
        self.assertEqual(result["events"]["precision"], 1)
        self.assertEqual(result["events"]["mean_start_error_ms"], 100)
        self.assertEqual((result["ocr"]["tp"], result["ocr"]["fp"], result["ocr"]["fn"]), (0, 1, 1))
        self.assertEqual(result["condition_status"]["accuracy"], 1)
        self.assertEqual((result["conditions"]["tp"], result["conditions"]["fp"], result["conditions"]["fn"]), (0, 1, 1))

    def test_no_overlap_or_tiny_overlap_cannot_become_true_positive(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car"}
        gt = [{**common, "start_ms": 0, "end_ms": 1000, "source_event_id": "E"}]
        for start, end in [(1050, 2050), (990, 1990)]:
            event = {**common, "event_id": "E", "start_ms": start, "end_ms": end}
            result = evaluate_review(gt, [event])
            self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (0, 1, 1))

    def test_rejected_prediction_cannot_match_manual_gt(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car"}
        gt = [{**common, "start_ms": 0, "end_ms": 1000, "source_event_id": None}]
        event = {**common, "event_id": "E", "start_ms": 0, "end_ms": 1000,
                 "annotation": {"is_valid_event": False}}
        result = evaluate_review(gt, [event])
        self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (0, 1, 1))

    def test_manual_missed_vehicle_does_not_borrow_another_prediction(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car",
                  "start_ms": 0, "end_ms": 1000}
        gt = [{**common, "event_id": "GT-000001", "source_event_id": None}]
        event = {**common, "event_id": "E", "annotation": {"is_valid_event": True}}
        result = evaluate_review(gt, [event])
        self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (0, 1, 1))

    def test_source_link_is_not_reassigned_to_another_event(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car"}
        gt = [{**common, "event_id": "E1", "source_event_id": "E1", "start_ms": 1000, "end_ms": 2000}]
        events = [{**common, "event_id": "E1", "start_ms": 3000, "end_ms": 4000},
                  {**common, "event_id": "E2", "start_ms": 1000, "end_ms": 2000}]
        result = evaluate_review(gt, events)
        self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (0, 2, 1))

    def test_global_matching_avoids_greedy_false_negative(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car"}
        gt = [{**common, "start_ms": 0, "end_ms": 100},
              {**common, "start_ms": 50, "end_ms": 150}]
        events = [{**common, "event_id": "E1", "start_ms": 0, "end_ms": 130},
                  {**common, "event_id": "E2", "start_ms": 0, "end_ms": 50}]
        result = evaluate_review(gt, events, min_temporal_iou=.5)
        self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (2, 0, 0))

    def test_ambiguous_unlinked_pair_is_not_used_for_ocr_or_condition(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY",
                  "vehicle_type": "car", "start_ms": 0, "end_ms": 1000,
                  "plate_readable": True, "plate_text": "ABC123",
                  "condition_status": "unreadable", "conditions": ["lighting_issue"]}
        gt = [{**common, "event_id": "A"}, {**common, "event_id": "B"}]
        event = {**common, "event_id": "E", "suggestion": {"plate_text": "ABC123",
                 "condition_status": "unreadable", "conditions": ["lighting_issue"]}}
        result = evaluate_review(gt, [event])
        self.assertEqual(result["events"]["ambiguous_unlinked_pairs"], 1)
        self.assertIsNone(result["ocr"]["recall"])
        self.assertIsNone(result["condition_status"]["accuracy"])

    def test_wrong_vehicle_class_is_false_positive_and_false_negative(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY",
                  "start_ms": 0, "end_ms": 1000}
        gt = [{**common, "vehicle_type": "car"}]
        events = [{**common, "event_id": "E", "vehicle_type": "motorcycle"}]
        result = evaluate_review(gt, events)
        self.assertEqual(result["events"]["matched"], 1)
        self.assertEqual((result["events"]["tp"], result["events"]["fp"], result["events"]["fn"]), (0, 1, 1))

    def test_clip_coverage_uses_union_and_is_separate_from_event_detection(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY",
                  "vehicle_type": "car", "start_ms": 0, "end_ms": 1000}
        gt = [common]
        event = {**common, "event_id": "E"}
        short = evaluate_review(gt, [event], [{"start_ms": 0, "end_ms": 800}], 2000)
        self.assertEqual(short["events"]["f1"], 1)
        self.assertEqual(short["clip"]["retention_recall"], 0)
        merged = evaluate_review(gt, [event], [
            {"start_ms": 0, "end_ms": 800}, {"start_ms": 500, "end_ms": 1200}], 2000)
        self.assertEqual(merged["clip"]["retention_recall"], 1)
        self.assertAlmostEqual(merged["clip"]["foreground_precision"], 1000 / 1200)
        self.assertAlmostEqual(merged["clip"]["video_reduction"], .4)

    def test_unknown_plate_and_disabled_enrichment_do_not_distort_scores(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY",
                  "vehicle_type": "car", "start_ms": 0, "end_ms": 1000}
        gt = [{**common, "plate_readable": True, "plate_text": None,
               "condition_status": "good", "conditions": []}]
        event = {**common, "event_id": "E", "suggestion": {"plate_text": "ABC123", "condition_status": "good", "conditions": []}}
        result = evaluate_review(gt, [event])
        self.assertEqual(result["ocr"]["unknown_gt_count"], 1)
        self.assertIsNone(result["ocr"]["precision"])
        self.assertEqual(result["condition_status"]["accuracy"], 1)
        self.assertIsNone(result["conditions"]["f1"])
        disabled = evaluate_review(gt, [event], ocr_available=False, conditions_available=False)
        self.assertFalse(disabled["ocr"]["available"])
        self.assertIsNone(disabled["ocr"]["recall"])
        self.assertIsNone(disabled["condition_status"]["accuracy"])

    def test_end_to_end_ocr_counts_missed_event(self):
        common = {"camera_id": "cam", "lane_id": "lane", "direction": "ENTRY", "vehicle_type": "car"}
        gt = [{**common, "start_ms": 0, "end_ms": 1000, "plate_readable": True, "plate_text": "ABC123"},
              {**common, "start_ms": 3000, "end_ms": 4000, "plate_readable": True, "plate_text": "DEF456"}]
        event = {**common, "event_id": "E", "start_ms": 0, "end_ms": 1000,
                 "suggestion": {"plate_text": "ABC123"}}
        result = evaluate_review(gt, [event])
        self.assertEqual(result["ocr"]["recall"], 1)
        self.assertEqual(result["ocr"]["end_to_end"]["recall"], .5)


if __name__ == "__main__":
    unittest.main()
