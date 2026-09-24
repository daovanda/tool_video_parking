from __future__ import annotations

import json
from pathlib import Path


def load_jsonl(path: str | Path) -> list[dict]:
    result = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def save_jsonl(path: str | Path, records: list[dict]) -> None:
    with Path(path).open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def evaluate_step1(gt_events: list[dict], events: list[dict], clips: list[dict],
                   duration_ms: int, coverage_threshold: float = 0.95) -> dict:
    """Event coverage and readable retention, using GT from the complete raw video."""
    valid_gt = [g for g in gt_events if g["end_ms"] > g["start_ms"]]
    matches = []
    used = set()
    for gt in valid_gt:
        options = []
        for idx, event in enumerate(events):
            if idx in used or event.get("camera_id") != gt.get("camera_id"):
                continue
            if (gt.get("vehicle_type") and event.get("vehicle_type") and
                    gt["vehicle_type"] != event["vehicle_type"]):
                continue
            overlap = overlap_ms(gt["start_ms"], gt["end_ms"], event["start_ms"], event["end_ms"])
            if overlap:
                options.append((overlap, idx))
        if options:
            _, idx = max(options)
            used.add(idx)
            matches.append((gt, events[idx]))
    clip_spans = [(c.get("actual_start_ms", c["start_ms"]), c.get("actual_end_ms", c["end_ms"])) for c in clips]
    retained = 0
    readable_total = readable_retained = 0
    details = []
    for gt in valid_gt:
        length = gt["end_ms"] - gt["start_ms"]
        # Clips are merged and disjoint in planner output.
        covered = sum(overlap_ms(gt["start_ms"], gt["end_ms"], start, end) for start, end in clip_spans)
        ratio = min(1.0, covered / length)
        enough = ratio >= coverage_threshold
        retained += enough
        readable = gt.get("readable_timestamps_ms", [])
        if readable:
            readable_total += 1
            if any(start <= ts < end for ts in readable for start, end in clip_spans):
                readable_retained += 1
        details.append({"gt_event_id": gt["gt_event_id"], "covered_ratio": ratio,
                        "retained": enough, "readable_retained": None if not readable else
                        any(start <= ts < end for ts in readable for start, end in clip_spans)})
    kept_ms = sum(max(0, end - start) for start, end in clip_spans)
    false_clips = sum(not any(overlap_ms(g["start_ms"], g["end_ms"], start, end) for g in valid_gt)
                      for start, end in clip_spans)
    vehicle_types = sorted({str(item.get("vehicle_type")) for item in valid_gt + events
                            if item.get("vehicle_type")})
    by_vehicle_type = {}
    for vehicle_type in vehicle_types:
        gt_count = sum(item.get("vehicle_type") == vehicle_type for item in valid_gt)
        predicted_count = sum(item.get("vehicle_type") == vehicle_type for item in events)
        matched_count = sum(gt.get("vehicle_type") == vehicle_type for gt, _event in matches)
        by_vehicle_type[vehicle_type] = {
            "gt_count": gt_count, "predicted_event_count": predicted_count,
            "matched_event_count": matched_count,
            "event_recall": None if not gt_count else matched_count / gt_count,
            "event_detection_precision": None if not predicted_count else matched_count / predicted_count,
        }
    return {
        "gt_count": len(valid_gt), "predicted_event_count": len(events), "matched_event_count": len(matches),
        "event_recall": None if not valid_gt else retained / len(valid_gt),
        "event_detection_precision": None if not events else len(matches) / len(events),
        "readable_gt_count": readable_total,
        "readable_retention_at_1": None if not readable_total else readable_retained / readable_total,
        "false_clips_per_hour": None if duration_ms <= 0 else false_clips / (duration_ms / 3_600_000),
        "video_reduction": None if duration_ms <= 0 else 1 - kept_ms / duration_ms,
        "coverage_threshold": coverage_threshold, "by_vehicle_type": by_vehicle_type,
        "details": details,
    }
