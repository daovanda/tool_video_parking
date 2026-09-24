from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.uploads = self.root / "uploads"
        self.runs = self.root / "runs"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "parking_web.sqlite3"
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, stored_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                    fps REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, pipeline_run_id TEXT, video_id TEXT NOT NULL,
                    status TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'DRAFT',
                    progress INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL, run_dir TEXT, event_count INTEGER NOT NULL DEFAULT 0,
                    clip_count INTEGER NOT NULL DEFAULT 0, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES videos(id)
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    run_id TEXT NOT NULL, event_id TEXT NOT NULL, data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(run_id, event_id),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1), data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def get_settings(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data_json FROM app_settings WHERE id=1").fetchone()
        return json.loads(row["data_json"]) if row else None

    def save_settings(self, value: dict) -> dict:
        with self.connect() as db:
            db.execute("""INSERT INTO app_settings (id, data_json, updated_at) VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json,
                updated_at=excluded.updated_at""",
                (json.dumps(value, ensure_ascii=False), utc_now()))
        return value

    def create_video(self, filename: str, stored_path: Path, size_bytes: int, metadata: dict) -> dict:
        video_id = f"VID-{uuid.uuid4().hex[:10].upper()}"
        created_at = utc_now()
        with self.connect() as db:
            db.execute("INSERT INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                video_id, filename, str(stored_path), size_bytes, metadata["duration_ms"],
                metadata["fps"], metadata["width"], metadata["height"], created_at,
            ))
        return self.get_video(video_id)

    def list_videos(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_video(self, video_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return dict(row) if row else None

    def delete_video(self, video_id: str) -> dict | None:
        video = self.get_video(video_id)
        if not video:
            return None
        with self.connect() as db:
            if db.execute("SELECT 1 FROM runs WHERE video_id=? LIMIT 1", (video_id,)).fetchone():
                raise ValueError("Video đã có run nên không thể xóa")
            db.execute("DELETE FROM videos WHERE id=?", (video_id,))
        Path(video["stored_path"]).unlink(missing_ok=True)
        return video

    def create_run(self, video_id: str, config: dict) -> dict:
        run_id = f"WEB-{uuid.uuid4().hex[:10].upper()}"
        now = utc_now()
        with self.connect() as db:
            db.execute("""INSERT INTO runs
                (id, video_id, status, review_status, progress, message, config_json, created_at, updated_at)
                VALUES (?, ?, 'QUEUED', 'DRAFT', 0, 'Đang chờ worker', ?, ?, ?)""",
                (run_id, video_id, json.dumps(config, ensure_ascii=False), now, now))
        return self.get_run(run_id)

    def update_run(self, run_id: str, **values) -> None:
        if not values:
            return
        values["updated_at"] = utc_now()
        columns = ", ".join(f"{key}=?" for key in values)
        with self.connect() as db:
            db.execute(f"UPDATE runs SET {columns} WHERE id=?", (*values.values(), run_id))

    def _run_dict(self, row: sqlite3.Row) -> dict:
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        return value

    def list_runs(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT runs.*, videos.filename AS video_filename
                FROM runs JOIN videos ON videos.id=runs.video_id ORDER BY runs.created_at DESC""").fetchall()
        return [self._run_dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("""SELECT runs.*, videos.filename AS video_filename
                FROM runs JOIN videos ON videos.id=runs.video_id WHERE runs.id=?""", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def delete_run(self, run_id: str) -> None:
        """Remove one terminal run and all of its review rows in one transaction."""
        with self.connect() as db:
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Không tìm thấy run")
            if row["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}:
                raise ValueError("Run đang chờ hoặc đang xử lý, chưa thể xóa")
            db.execute("DELETE FROM annotations WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))

    def save_annotation(self, run_id: str, event_id: str, data: dict) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute("""INSERT INTO annotations(run_id,event_id,data_json,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(run_id,event_id) DO UPDATE SET data_json=excluded.data_json,
                updated_at=excluded.updated_at""",
                (run_id, event_id, json.dumps(data, ensure_ascii=False), now))

    def replace_annotations(self, run_id: str, records: list[dict], *, review_status: str | None = None) -> None:
        """Replace one run's complete GT set in a single SQLite transaction."""
        now = utc_now()
        with self.connect() as db:
            db.execute("DELETE FROM annotations WHERE run_id=?", (run_id,))
            db.executemany(
                "INSERT INTO annotations(run_id,event_id,data_json,updated_at) VALUES(?,?,?,?)",
                [(run_id, row["event_id"], json.dumps(row, ensure_ascii=False), now)
                 for row in records],
            )
            if review_status is not None:
                db.execute("UPDATE runs SET review_status=?, updated_at=? WHERE id=?",
                           (review_status, now, run_id))

    def annotations(self, run_id: str) -> dict[str, dict]:
        with self.connect() as db:
            rows = db.execute("SELECT event_id,data_json FROM annotations WHERE run_id=?", (run_id,)).fetchall()
        return {row["event_id"]: json.loads(row["data_json"]) for row in rows}

    def dashboard(self) -> dict:
        with self.connect() as db:
            videos = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            runs = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            completed = db.execute("SELECT COUNT(*) FROM runs WHERE status='COMPLETED'").fetchone()[0]
            reviewed = db.execute("SELECT COUNT(*) FROM runs WHERE review_status='REVIEWED'").fetchone()[0]
            events = db.execute("SELECT COALESCE(SUM(event_count),0) FROM runs").fetchone()[0]
        return {"video_count": videos, "run_count": runs, "completed_count": completed,
                "reviewed_count": reviewed, "event_count": events}
