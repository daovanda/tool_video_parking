"""Sequential multi-camera orchestration for the Step 1 pilot.

Each item is still an independent :class:`RunConfig`.  This keeps tracker and
event state isolated per camera while allowing an operator to process many
lanes from one command.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from .config import RunConfig
from .pipeline import run_pipeline


@dataclass
class BatchConfig:
    runs: list[RunConfig]

    def validate(self) -> None:
        if not self.runs:
            raise ValueError("Batch cần ít nhất một camera")
        camera_ids: set[str] = set()
        lane_ids: set[str] = set()
        for run in self.runs:
            run.validate()
            camera_id = run.camera.camera_id
            lane_id = run.camera.lane_id
            if camera_id in camera_ids:
                raise ValueError(f"camera_id bị lặp trong batch: {camera_id}")
            if lane_id in lane_ids:
                raise ValueError(f"lane_id bị lặp trong batch: {lane_id}")
            camera_ids.add(camera_id)
            lane_ids.add(lane_id)

    def to_dict(self) -> dict:
        return {"runs": [run.to_dict() for run in self.runs]}

    @classmethod
    def from_dict(cls, value: dict | list[dict]) -> "BatchConfig":
        raw_runs = value if isinstance(value, list) else value.get("runs")
        if not isinstance(raw_runs, list):
            raise ValueError("Batch JSON cần field runs là một mảng")
        return cls([RunConfig.from_dict(item) for item in raw_runs])

    @classmethod
    def load(cls, path: str | Path) -> "BatchConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def run_batch(config: BatchConfig, progress: Callable[[int, str], None] | None = None,
              cancel: Callable[[], bool] | None = None) -> dict:
    """Run cameras sequentially and return all per-camera results.

    Sequential execution avoids sharing tracker IDs or GPU state between
    cameras in this pilot.  A future worker pool can replace this function
    without changing each camera's manifest contract.
    """
    config.validate()
    results = []
    total = len(config.runs)
    for index, run_config in enumerate(config.runs):
        if cancel and cancel():
            raise RuntimeError("Đã hủy batch xử lý")
        camera = run_config.camera.camera_id

        def child_progress(percent: int, message: str, *, index=index, camera=camera) -> None:
            if progress:
                progress(round((index * 100 + percent) / total), f"[{camera}] {message}")

        results.append(run_pipeline(run_config, progress=child_progress, cancel=cancel))
    summary = {
        "run_count": total,
        "event_count": sum(item["run"]["event_count"] for item in results),
        "clip_count": sum(item["run"]["clip_count"] for item in results),
        "results": results,
    }
    if progress:
        progress(100, f"Hoàn thành batch: {summary['event_count']} lượt, {summary['clip_count']} clip")
    return summary
