"""Browser-compatible copies of legacy MP4 clips; original run artifacts stay intact."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import threading

import cv2

_transcode_lock = threading.Lock()
_PREVIEW_MAX_WIDTH = 960


def _open_h264_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    if os.name == "nt":
        writer = cv2.VideoWriter(str(path), cv2.CAP_MSMF, fourcc, fps, size)
        if writer.isOpened():
            return writer
        writer.release()
    return cv2.VideoWriter(str(path), fourcc, fps, size)


def _codec(capture: cv2.VideoCapture) -> str:
    fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((fourcc >> (8 * index)) & 255) for index in range(4)).lower()


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def browser_compatible_mp4(source: Path, run_root: Path) -> Path:
    """Return the source if H.264, otherwise cache an H.264 copy by content hash."""
    if source.suffix.lower() != ".mp4":
        return source
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise RuntimeError("Không mở được video clip")
        if _codec(capture) in {"h264", "avc1", "avc3"}:
            return source
    finally:
        capture.release()

    cache_dir = run_root / ".browser_media"
    target = cache_dir / f"{_sha256(source)}-preview-w{_PREVIEW_MAX_WIDTH}.mp4"
    with _transcode_lock:
        if target.is_file() and target.stat().st_size > 0:
            return target
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache_dir / f"{target.stem}.{os.getpid()}.{threading.get_ident()}.mp4"
        capture = cv2.VideoCapture(str(source))
        fps = capture.get(cv2.CAP_PROP_FPS)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not capture.isOpened() or fps <= 0 or width <= 0 or height <= 0:
            capture.release()
            raise RuntimeError("Không đọc được thông số video clip")
        output_width = max(2, min(width, _PREVIEW_MAX_WIDTH) // 2 * 2)
        output_height = max(2, round(height * output_width / width / 2) * 2)
        writer = _open_h264_writer(temporary, fps, (output_width, output_height))
        if not writer.isOpened():
            writer.release()
            capture.release()
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Máy chưa có bộ mã hóa H.264 để phát clip trên trình duyệt")
        frames = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if (output_width, output_height) != (width, height):
                    frame = cv2.resize(frame, (output_width, output_height),
                                       interpolation=cv2.INTER_AREA)
                writer.write(frame)
                frames += 1
        finally:
            writer.release()
            capture.release()
        probe = cv2.VideoCapture(str(temporary))
        try:
            ok, _ = probe.read()
            if not ok or _codec(probe) not in {"h264", "avc1", "avc3"} or frames == 0:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("Bản clip H.264 không giải mã được")
        finally:
            probe.release()
        temporary.replace(target)
    return target
