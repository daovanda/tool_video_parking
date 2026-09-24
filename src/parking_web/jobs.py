from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading

from parking_step1.config import RunConfig
from parking_step1.pipeline import run_pipeline

from .storage import WebStorage


class RunJobs:
    """Bounded local queue; each run owns its model instances and artifacts."""

    def __init__(self, storage: WebStorage, max_workers: int | None = None):
        self.storage = storage
        self.max_workers = max_workers if max_workers is not None else int(os.environ.get("PARKING_WEB_MAX_WORKERS", "2"))
        if self.max_workers < 1:
            raise ValueError("PARKING_WEB_MAX_WORKERS phải >= 1")
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="parking-step1")
        self.cancel_flags: dict[str, threading.Event] = {}

    def submit(self, web_run_id: str, config: RunConfig) -> None:
        flag = threading.Event()
        self.cancel_flags[web_run_id] = flag
        self.executor.submit(self._execute, web_run_id, config, flag)

    def cancel(self, web_run_id: str) -> bool:
        flag = self.cancel_flags.get(web_run_id)
        if not flag:
            return False
        flag.set()
        self.storage.update_run(web_run_id, message="Đang hủy sau frame hiện tại")
        return True

    def _execute(self, web_run_id: str, config: RunConfig, flag: threading.Event) -> None:
        if flag.is_set():
            self.storage.update_run(web_run_id, status="CANCELLED", message="Đã hủy")
            self.cancel_flags.pop(web_run_id, None)
            return
        self.storage.update_run(web_run_id, status="RUNNING", progress=1, message="Đang khởi tạo model")

        def progress(percent: int, message: str) -> None:
            self.storage.update_run(web_run_id, progress=percent, message=message)

        try:
            result = run_pipeline(config, progress=progress, cancel=flag.is_set,
                                  on_run_created=lambda pipeline_id, path: self.storage.update_run(
                                      web_run_id, pipeline_run_id=pipeline_id, run_dir=str(path)))
            run = result["run"]
            if flag.is_set():
                self.storage.update_run(web_run_id, status="CANCELLED", message="Đã hủy")
                return
            self.storage.update_run(
                web_run_id, status="COMPLETED", progress=100, message="Đã xử lý xong",
                pipeline_run_id=run["run_id"], run_dir=result["run_dir"],
                event_count=run["event_count"], clip_count=run["clip_count"], error=None,
            )
        except Exception as exc:
            cancelled = flag.is_set()
            self.storage.update_run(web_run_id, status="CANCELLED" if cancelled else "FAILED",
                                    message="Đã hủy" if cancelled else "Xử lý thất bại", error=str(exc))
        finally:
            self.cancel_flags.pop(web_run_id, None)
