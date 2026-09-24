from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from parking_web.jobs import RunJobs
from parking_web.storage import WebStorage


class RunJobCancellationTests(unittest.TestCase):
    def test_two_runs_start_in_parallel_and_third_waits(self):
        with TemporaryDirectory() as directory:
            storage = WebStorage(directory)
            video = storage.create_video("raw.mp4", Path(directory) / "raw.mp4", 1,
                                         {"duration_ms": 1000, "fps": 10, "width": 32, "height": 24})
            runs = [storage.create_run(video["id"], {}) for _ in range(3)]
            jobs = RunJobs(storage, max_workers=2)
            both_started = threading.Event()
            release = threading.Event()
            lock = threading.Lock()
            started: list[str] = []

            def fake_pipeline(run_id, **kwargs):
                with lock:
                    started.append(run_id)
                    if len(started) == 2:
                        both_started.set()
                if not release.wait(5):
                    raise TimeoutError("Worker không được giải phóng")
                return {"run_dir": str(storage.runs / run_id),
                        "run": {"run_id": run_id, "event_count": 0, "clip_count": 0}}

            try:
                with patch("parking_web.jobs.run_pipeline", side_effect=fake_pipeline):
                    for run in runs:
                        jobs.submit(run["id"], run["id"])
                    self.assertTrue(both_started.wait(3), "Hai run không bắt đầu đồng thời")
                    self.assertEqual(len(started), 2)
                    self.assertEqual(storage.get_run(runs[2]["id"])["status"], "QUEUED")
                    release.set()
                    jobs.executor.shutdown(wait=True)
                self.assertEqual(len(started), 3)
                self.assertTrue(all(storage.get_run(run["id"])["status"] == "COMPLETED" for run in runs))
            finally:
                release.set()
                jobs.executor.shutdown(wait=True)

    def test_queued_and_late_cancellation_never_complete(self):
        with TemporaryDirectory() as directory:
            storage = WebStorage(directory)
            video = storage.create_video("raw.mp4", Path(directory) / "raw.mp4", 1,
                                         {"duration_ms": 1000, "fps": 10, "width": 32, "height": 24})
            jobs = RunJobs(storage)
            try:
                queued = storage.create_run(video["id"], {})
                queued_flag = threading.Event()
                queued_flag.set()
                with patch("parking_web.jobs.run_pipeline") as pipeline:
                    jobs._execute(queued["id"], None, queued_flag)
                    pipeline.assert_not_called()
                self.assertEqual(storage.get_run(queued["id"])["status"], "CANCELLED")

                running = storage.create_run(video["id"], {})
                flag = threading.Event()

                def finish_after_stop(*args, **kwargs):
                    flag.set()
                    kwargs["on_run_created"]("step1-test", storage.runs / "step1-test")
                    return {"run_dir": str(storage.runs / "step1-test"),
                            "run": {"run_id": "step1-test", "event_count": 1, "clip_count": 1}}

                with patch("parking_web.jobs.run_pipeline", side_effect=finish_after_stop):
                    jobs._execute(running["id"], None, flag)
                saved = storage.get_run(running["id"])
                self.assertEqual(saved["status"], "CANCELLED")
                self.assertEqual(saved["pipeline_run_id"], "step1-test")
                self.assertEqual(saved["run_dir"], str(storage.runs / "step1-test"))
            finally:
                jobs.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
