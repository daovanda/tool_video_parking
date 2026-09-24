"""Scores for reviewed GT against the original predictions on the raw timeline."""

from __future__ import annotations

import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from parking_step1.evaluation import overlap_ms


CAUSES = frozenset({"capture_blur", "plate_obstruction", "lighting_issue"})


def _scores(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if precision is not None and recall is not None else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _plate(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _plate_truth(gt: dict) -> tuple[bool, str]:
    """Return whether this human plate label can be scored, and its exact text."""
    text = _plate(gt.get("plate_text"))
    readable = gt.get("plate_readable")
    if readable is True and text:
        return True, text
    if readable is False and not text:
        return True, ""
    return False, ""


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted((a, b) for a, b in spans if b > a):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _total(spans: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in spans)


def _intersection(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> int:
    return sum(overlap_ms(x, y, u, v) for x, y in a for u, v in b)


def _clip_metrics(gt: list[dict], clips: list[dict], duration_ms: int,
                  coverage_threshold: float) -> dict:
    valid = [c for c in clips if c.get("quality_status") != "invalid"]
    spans = _merge_spans([
        (max(0, int(c.get("actual_start_ms", c["start_ms"]))),
         min(duration_ms, int(c.get("actual_end_ms", c["end_ms"]))))
        for c in valid
    ])
    gt_spans = _merge_spans([(g["start_ms"], g["end_ms"]) for g in gt])
    covered = [min(1.0, _intersection([(g["start_ms"], g["end_ms"])], spans) /
                   (g["end_ms"] - g["start_ms"])) for g in gt]
    retained = sum(value >= coverage_threshold for value in covered)
    kept_ms = _total(spans)
    foreground_ms = _total(gt_spans)
    useful_ms = _intersection(spans, gt_spans)
    return {
        "gt_count": len(gt), "retained_count": retained,
        "retention_recall": retained / len(gt) if gt else None,
        "mean_gt_coverage": sum(covered) / len(covered) if covered else None,
        "coverage_threshold": coverage_threshold,
        "foreground_precision": useful_ms / kept_ms if kept_ms else None,
        "foreground_recall": useful_ms / foreground_ms if foreground_ms else None,
        "video_reduction": 1 - kept_ms / duration_ms if duration_ms > 0 else None,
        "kept_ms": kept_ms, "invalid_clip_count": len(clips) - len(valid),
    }


def evaluate_review(gt: list[dict], events: list[dict], clips: list[dict] | None = None,
                    duration_ms: int | None = None, *, min_temporal_iou: float = .30,
                    boundary_tolerance_ms: int = 500,
                    ocr_available: bool = True, conditions_available: bool = True,
                    coverage_threshold: float = .95) -> dict:
    """Match events globally; score existence/class, clips, OCR and condition separately."""
    if not 0 < min_temporal_iou <= 1:
        raise ValueError("min_temporal_iou must be in (0, 1]")
    if any(g["end_ms"] <= g["start_ms"] for g in gt):
        raise ValueError("GT intervals must have positive duration")

    # A reviewed rejection is always an FP; do not reuse it to explain a new GT.
    matchable = [(index, event) for index, event in enumerate(events)
                 if not isinstance(event.get("annotation"), dict)
                 or event["annotation"].get("is_valid_event", True)]
    count = len(gt)
    pred_count = len(matchable)
    ious: dict[tuple[int, int], float] = {}
    linked: dict[tuple[int, int], bool] = {}
    for gi, g in enumerate(gt):
        source_id = g.get("source_event_id")
        # Web GT-xxxxxx rows are explicitly added for vehicles missed by Model 1.
        if source_id is None and re.fullmatch(r"GT-\d{6}", str(g.get("event_id", ""))):
            continue
        for pi, (_, e) in enumerate(matchable):
            # Do not reassign a reviewed annotation to a different prediction.
            if source_id and source_id != e.get("event_id"):
                continue
            if any(g.get(k) != e.get(k) for k in ("camera_id", "lane_id", "direction")):
                continue
            overlap = overlap_ms(g["start_ms"], g["end_ms"], e["start_ms"], e["end_ms"])
            if overlap <= 0:
                continue
            union = max(g["end_ms"], e["end_ms"]) - min(g["start_ms"], e["start_ms"])
            iou = overlap / union
            if iou >= min_temporal_iou:
                ious[gi, pi] = iou
                linked[gi, pi] = bool(g.get("source_event_id") and g["source_event_id"] == e.get("event_id"))

    pairs: list[tuple[int, int, float]] = []
    if ious and len({gi for gi, _ in ious}) == len(ious) and len({pi for _, pi in ious}) == len(ious):
        pairs = [(gi, pi, iou) for (gi, pi), iou in ious.items()]
    elif count and pred_count:
        # Dummy columns permit unmatched GT. Cardinality dominates identity/IoU.
        weights = np.zeros((count, pred_count + count), dtype=np.float64)
        weights[:, :pred_count] = -1e9
        cardinality_bonus = 10 * (min(count, pred_count) + 1)
        for (gi, pi), iou in ious.items():
            weights[gi, pi] = cardinality_bonus + (2 if linked[gi, pi] else 0) + iou
        row_ids, column_ids = linear_sum_assignment(weights, maximize=True)
        pairs = [(int(gi), int(pi), ious[int(gi), int(pi)])
                 for gi, pi in zip(row_ids, column_ids) if (int(gi), int(pi)) in ious]
    matched_gt = {gi for gi, _, _ in pairs}
    matched_pred = {pi for _, pi, _ in pairs}
    # Time alone cannot identify two concurrent, otherwise indistinguishable vehicles.
    ambiguous = set()
    for gi, pi, iou in pairs:
        if linked[gi, pi]:
            continue
        if any(other != pi and value >= iou - .05 for (g, other), value in ious.items() if g == gi) or any(
                other != gi and value >= iou - .05 for (other, p), value in ious.items() if p == pi):
            ambiguous.add((gi, pi))

    class_tp = sum(gt[gi]["vehicle_type"] == matchable[pi][1]["vehicle_type"] for gi, pi, _ in pairs)
    event_score = _scores(class_tp, len(events) - class_tp, len(gt) - class_tp)
    start_errors = [abs(gt[gi]["start_ms"] - matchable[pi][1]["start_ms"]) for gi, pi, _ in pairs]
    end_errors = [abs(gt[gi]["end_ms"] - matchable[pi][1]["end_ms"]) for gi, pi, _ in pairs]
    event_score.update({
        "matched": len(pairs), "gt_count": len(gt), "prediction_count": len(events),
        "class_confusions": len(pairs) - class_tp,
        "ambiguous_unlinked_pairs": len(ambiguous),
        "vehicle_type_accuracy": class_tp / len(pairs) if pairs else None,
        "crossed_accuracy": sum(gt[gi].get("crossed") == matchable[pi][1].get("crossed")
                                for gi, pi, _ in pairs) / len(pairs) if pairs else None,
        "mean_temporal_iou": sum(iou for _, _, iou in pairs) / len(pairs) if pairs else None,
        "mean_start_error_ms": sum(start_errors) / len(pairs) if pairs else None,
        "mean_end_error_ms": sum(end_errors) / len(pairs) if pairs else None,
        "within_boundary_tolerance": sum(a <= boundary_tolerance_ms and b <= boundary_tolerance_ms
                                         for a, b in zip(start_errors, end_errors)) / len(pairs) if pairs else None,
        "min_temporal_iou": min_temporal_iou,
        "boundary_tolerance_ms": boundary_tolerance_ms,
    })

    ocr_tp = ocr_fp = ocr_fn = 0
    ocr_all_tp = ocr_all_fp = ocr_all_fn = 0
    ocr_scored = ocr_readable_gt = 0
    ocr_unknown = sum(not _plate_truth(g)[0] for g in gt if g["vehicle_type"] != "bicycle") if ocr_available else 0
    ocr_total_readable_gt = sum(_plate_truth(g)[0] and bool(_plate_truth(g)[1])
                                for g in gt if g["vehicle_type"] != "bicycle") if ocr_available else 0
    status_tp = status_fp = status_fn = 0
    status_all_tp = status_all_fp = status_all_fn = 0
    cause_tp = cause_fp = cause_fn = 0
    cause_all_tp = cause_all_fp = cause_all_fn = 0
    status_correct = status_total = 0
    condition_unknown_gt = sum(g.get("condition_status") not in ("good", "unreadable")
                               for g in gt if g["vehicle_type"] != "bicycle") if conditions_available else 0

    for gi, pi, _ in pairs:
        g, e = gt[gi], matchable[pi][1]
        if g["vehicle_type"] == "bicycle" or (gi, pi) in ambiguous:
            continue
        suggestion = e.get("suggestion") or {}
        if ocr_available:
            known, truth_plate = _plate_truth(g)
            if known:
                ocr_scored += 1
                ocr_readable_gt += bool(truth_plate)
                prediction = _plate(suggestion.get("plate_text"))
                tp = int(bool(prediction) and prediction == truth_plate)
                fp = int(bool(prediction) and prediction != truth_plate)
                fn = int(bool(truth_plate) and prediction != truth_plate)
                ocr_tp += tp
                ocr_fp += fp
                ocr_fn += fn
                ocr_all_tp += tp
                ocr_all_fp += fp
                ocr_all_fn += fn
        if conditions_available and g.get("condition_status") in ("good", "unreadable"):
            predicted_status = suggestion.get("condition_status")
            truth_status = g.get("condition_status")
            status_total += 1
            status_correct += predicted_status == truth_status
            tp = int(predicted_status == "unreadable" and truth_status == "unreadable")
            fp = int(predicted_status == "unreadable" and truth_status != "unreadable")
            fn = int(truth_status == "unreadable" and predicted_status != "unreadable")
            status_tp += tp
            status_fp += fp
            status_fn += fn
            status_all_tp += tp
            status_all_fp += fp
            status_all_fn += fn
            truth_causes = set(g.get("conditions") or []) & CAUSES
            predicted_causes = set(suggestion.get("conditions") or []) & CAUSES
            tp = len(truth_causes & predicted_causes)
            fp = len(predicted_causes - truth_causes)
            fn = len(truth_causes - predicted_causes)
            cause_tp += tp
            cause_fp += fp
            cause_fn += fn
            cause_all_tp += tp
            cause_all_fp += fp
            cause_all_fn += fn

    if ocr_available or conditions_available:
        for gi, g in enumerate(gt):
            if gi in matched_gt or g["vehicle_type"] == "bicycle":
                continue
            if ocr_available:
                known, truth_plate = _plate_truth(g)
                ocr_all_fn += int(known and bool(truth_plate))
            if conditions_available and g.get("condition_status") in ("good", "unreadable"):
                status_all_fn += int(g.get("condition_status") == "unreadable")
                cause_all_fn += len(set(g.get("conditions") or []) & CAUSES)
        for pi, (_, e) in enumerate(matchable):
            if pi in matched_pred:
                continue
            suggestion = e.get("suggestion") or {}
            if ocr_available:
                ocr_all_fp += int(bool(_plate(suggestion.get("plate_text"))))
            if conditions_available:
                status_all_fp += int(suggestion.get("condition_status") == "unreadable")
                cause_all_fp += len(set(suggestion.get("conditions") or []) & CAUSES)
        for e in events:
            if not isinstance(e.get("annotation"), dict) or e["annotation"].get("is_valid_event", True):
                continue
            suggestion = e.get("suggestion") or {}
            if ocr_available:
                ocr_all_fp += int(bool(_plate(suggestion.get("plate_text"))))
            if conditions_available:
                status_all_fp += int(suggestion.get("condition_status") == "unreadable")
                cause_all_fp += len(set(suggestion.get("conditions") or []) & CAUSES)

    ocr = _scores(ocr_tp, ocr_fp, ocr_fn) if ocr_available else _scores(0, 0, 0)
    ocr.update({"available": ocr_available, "scored_matched_events": ocr_scored,
                "unknown_gt_count": ocr_unknown, "eligible_readable_gt": ocr_readable_gt,
                "total_readable_gt": ocr_total_readable_gt,
                "end_to_end": _scores(ocr_all_tp, ocr_all_fp, ocr_all_fn) if ocr_available else _scores(0, 0, 0)})
    status = _scores(status_tp, status_fp, status_fn) if conditions_available else _scores(0, 0, 0)
    status.update({"available": conditions_available,
                   "accuracy": status_correct / status_total if status_total else None,
                   "unknown_gt_count": condition_unknown_gt,
                   "evaluated_matched_events": status_total,
                   "end_to_end": _scores(status_all_tp, status_all_fp, status_all_fn) if conditions_available else _scores(0, 0, 0)})
    causes = _scores(cause_tp, cause_fp, cause_fn) if conditions_available else _scores(0, 0, 0)
    causes.update({"available": conditions_available,
                   "end_to_end": _scores(cause_all_tp, cause_all_fp, cause_all_fn) if conditions_available else _scores(0, 0, 0)})
    source_by_id = {e.get("event_id"): e for e in events}
    linked_gt = [(g, source_by_id[g["source_event_id"]]) for g in gt
                 if g.get("source_event_id") in source_by_id]
    event_unchanged = sum(
        all(g.get(key) == e.get(key) for key in ("start_ms", "end_ms", "vehicle_type", "crossed"))
        for g, e in linked_gt
    )
    review_diagnostics = {
        "linked_gt_count": len(linked_gt),
        "manual_gt_count": len(gt) - len(linked_gt),
        "rejected_prediction_count": len(events) - pred_count,
        "event_fields_unchanged_count": event_unchanged,
        "event_fields_unchanged_ratio": event_unchanged / len(linked_gt) if linked_gt else None,
    }
    return {"evaluation_schema_version": "0.2.0", "events": event_score,
            "clip": _clip_metrics(gt, clips or [], duration_ms or 0, coverage_threshold)
            if clips is not None and duration_ms is not None else None,
            "ocr": ocr, "condition_status": status, "conditions": causes,
            "review_diagnostics": review_diagnostics}
