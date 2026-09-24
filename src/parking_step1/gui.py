from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QSlider, QSpinBox, QDoubleSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QVBoxLayout, QWidget,
)

from .config import CameraConfig, RunConfig, line_intersects_roi
from .conditions import CONDITION_TYPES, run_condition_analysis
from .evaluation import evaluate_step1, load_jsonl, save_jsonl
from .pipeline import run_pipeline, video_info


class VideoCanvas(QWidget):
    geometry_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(700, 390)
        self.pixmap = None
        self.roi: list[list[float]] = []
        self.line: list[list[float]] = []
        self.overlay_detections: list[dict] = []
        self.overlay_plates: list[dict] = []
        self.highlight_track_id: int | None = None
        self.overlay_title = ""
        self.mode = "none"
        self.preview_rect = (0, 0, 1, 1)

    def show_frame(self, frame, detections: list[dict] | None = None,
                   highlight_track_id: int | None = None, overlay_title: str = "",
                   plates: list[dict] | None = None) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, channels = rgb.shape
        image = QImage(rgb.data, w, h, channels * w, QImage.Format.Format_RGB888)
        self.pixmap = QPixmap.fromImage(image.copy())
        self.overlay_detections = list(detections or [])
        self.overlay_plates = list(plates or [])
        self.highlight_track_id = highlight_track_id
        self.overlay_title = overlay_title
        self.update()

    def clear_detection_overlay(self) -> None:
        self.overlay_detections = []
        self.overlay_plates = []
        self.highlight_track_id = None
        self.overlay_title = ""
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151a22"))
        if not self.pixmap:
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Chọn video để xem frame đầu")
            return
        width = min(self.width(), self.height() * self.pixmap.width() / self.pixmap.height())
        height = width * self.pixmap.height() / self.pixmap.width()
        left = (self.width() - width) / 2
        top = (self.height() - height) / 2
        self.preview_rect = (left, top, width, height)
        painter.drawPixmap(round(left), round(top), round(width), round(height), self.pixmap)
        for points, color, closed in ((self.roi, QColor("#31d18a"), True), (self.line, QColor("#ffca61"), False)):
            painter.setPen(QPen(color, 3))
            pixels = [(round(left + x * width), round(top + y * height)) for x, y in points]
            for i in range(1, len(pixels)):
                painter.drawLine(*pixels[i - 1], *pixels[i])
            if closed and len(pixels) >= 3:
                painter.drawLine(*pixels[-1], *pixels[0])
            for x, y in pixels:
                painter.drawEllipse(x - 4, y - 4, 8, 8)
        # Detection boxes are drawn in source-frame coordinates and scaled to
        # the displayed pixmap.  The selected event track is emphasized so the
        # first event frame can be inspected without rerunning the model.
        if self.overlay_detections:
            source_width = max(1, self.pixmap.width())
            source_height = max(1, self.pixmap.height())
            for detection in self.overlay_detections:
                box = detection.get("box", [])
                if len(box) != 4:
                    continue
                x1, y1, x2, y2 = [float(value) for value in box]
                px1 = round(left + x1 / source_width * width)
                py1 = round(top + y1 / source_height * height)
                px2 = round(left + x2 / source_width * width)
                py2 = round(top + y2 / source_height * height)
                track_id = detection.get("track_id")
                selected = self.highlight_track_id is not None and track_id == self.highlight_track_id
                color = QColor("#38e08f") if selected else QColor("#62b5ff")
                painter.setPen(QPen(color, 5 if selected else 3))
                painter.drawRect(px1, py1, max(1, px2 - px1), max(1, py2 - py1))
                label = f"{detection.get('vehicle_type', 'vehicle')} | BT #{track_id} | {float(detection.get('confidence', 0.0)):.2f}"
                metrics = painter.fontMetrics()
                label_rect = metrics.boundingRect(label)
                label_top = max(round(top), py1 - label_rect.height() - 4)
                label_box = (px1, label_top, label_rect.width() + 10, label_rect.height() + 4)
                painter.fillRect(*label_box, QColor(21, 26, 34, 220))
                painter.setPen(QPen(color, 1))
                painter.drawText(px1 + 5, label_top + label_rect.height(), label)
        for plate in self.overlay_plates:
            box = plate.get("plate_box", [])
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = [float(v) for v in box]
            px1 = round(left + x1 / self.pixmap.width() * width)
            py1 = round(top + y1 / self.pixmap.height() * height)
            px2 = round(left + x2 / self.pixmap.width() * width)
            py2 = round(top + y2 / self.pixmap.height() * height)
            painter.setPen(QPen(QColor("#ffd54f"), 3))
            painter.drawRect(px1, py1, max(1, px2 - px1), max(1, py2 - py1))
            label = f"Plate {float(plate.get('plate_confidence', 0)):.2f}"
            if plate.get("ocr_text_normalized"):
                label += f" | {plate['ocr_text_normalized']}"
            painter.drawText(px1, max(round(top) + 15, py1 - 5), label)
        if self.overlay_title:
            painter.setPen(QPen(QColor("#ffffff"), 1))
            title_rect = painter.fontMetrics().boundingRect(self.overlay_title)
            painter.fillRect(round(left), round(top), title_rect.width() + 16, title_rect.height() + 10,
                             QColor(21, 26, 34, 220))
            painter.drawText(round(left) + 8, round(top) + title_rect.height() + 3, self.overlay_title)

    def mousePressEvent(self, event) -> None:
        if self.mode not in {"roi", "line"} or not self.pixmap:
            return
        left, top, width, height = self.preview_rect
        x = (event.position().x() - left) / width
        y = (event.position().y() - top) / height
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            return
        point = [round(x, 6), round(y, 6)]
        if self.mode == "roi":
            self.roi.append(point)
        else:
            if len(self.line) >= 2:
                self.line.clear()
            self.line.append(point)
        self.update()
        self.geometry_changed.emit()


class PipelineWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    result_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, config: RunConfig):
        super().__init__()
        self.config = config
        self.cancel_requested = False

    def run(self) -> None:
        try:
            result = run_pipeline(self.config,
                                  lambda percent, message: self.progress_signal.emit(percent, message),
                                  cancel=lambda: self.cancel_requested)
            self.result_signal.emit(result)
        except Exception as exc:
            self.error_signal.emit(f"{type(exc).__name__}: {exc}")


class ConditionWorker(PipelineWorker):
    def __init__(self, run_dir: str, config: RunConfig):
        super().__init__(config)
        self.run_dir = run_dir

    def run(self) -> None:
        try:
            run_condition_analysis(self.run_dir, self.config,
                                   progress=lambda n, m: self.progress_signal.emit(n, m),
                                   cancel=lambda: self.cancel_requested)
            self.result_signal.emit(self.run_dir)
        except Exception as exc:
            self.error_signal.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    GT_TABLE_COLUMNS = (
        ("gt_event_id", "GT ID"),
        ("source_event_id", "Event nguồn"),
        ("vehicle_type", "Loại"),
        ("start_ms", "Bắt đầu ms"),
        ("end_ms", "Kết thúc ms"),
        ("crossed", "Crossed"),
        ("plate_text", "Biển số"),
        ("plate_readable", "Có thể đọc biển"),
        ("plate_readability", "Khả năng đọc"),
        ("readable_timestamps_ms", "Frame đọc được"),
        ("conditions", "Điều kiện"),
        ("condition_status", "Trạng thái điều kiện"),
        ("camera_id", "Camera"),
        ("lane_id", "Lane"),
        ("direction", "Hướng"),
        ("condition_annotation_source", "Nguồn điều kiện"),
        ("annotation_source", "Nguồn nhãn"),
        ("suggestions", "Gợi ý"),
        ("source_uri", "Video raw"),
        ("annotation_schema_version", "Schema GT"),
    )
    READABILITY_LABELS = {
        "unknown": "Chưa xác định",
        "unreadable": "Không đọc được",
        "single_frame_readable": "Đọc được 1 frame",
        "multi_frame_readable": "Đọc được nhiều frame",
        "partially_readable": "Đọc một phần",
        "out_of_view": "Ngoài khung hình",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parking Video — Bước 1")
        self.resize(1400, 850)
        self.source_info = None
        self.source_capture = None
        self.clip_capture = None
        self.clip_path: Path | None = None
        self.clip_fps = 0.0
        self.clip_duration_ms = 0
        self.clip_source_offset_ms = 0
        self.clip_artifact_offset_ms = 0
        self.clip_current_ms = 0
        self.active_event: dict | None = None
        self.detection_records: list[dict] = []
        self.plate_records: dict[str, dict] = {}
        self.condition_records: dict[str, dict] = {}
        self.clip_timer = QTimer(self)
        self.clip_timer.timeout.connect(self._advance_clip)
        self.run_result = None
        self.gt_events: list[dict] = []
        self.gt_start = None
        self.gt_end = None
        self.gt_readable: list[int] = []
        self.gt_edit_index: int | None = None
        self.annotation_event_id: str | None = None
        self.gt_suggestions: dict[str, dict] = {}
        self.worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        splitter.addWidget(left)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._tab_changed)
        left_layout.addWidget(self.tabs)

        setup = QWidget()
        setup_layout = QVBoxLayout(setup)
        self.tabs.addTab(setup, "Cấu hình & chạy")
        source_box = QGroupBox("Video và camera")
        form = QFormLayout(source_box)
        self.source_edit = QLineEdit()
        self.output_edit = QLineEdit(str(Path.cwd() / "outputs"))
        form.addRow("Video raw", self._browse_row(self.source_edit, self._browse_video))
        form.addRow("Đầu ra", self._browse_row(self.output_edit, self._browse_output))
        self.camera_edit = QLineEdit("CAM01")
        self.lane_edit = QLineEdit("ENTRY_01")
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["ENTRY", "EXIT"])
        form.addRow("Camera ID", self.camera_edit)
        form.addRow("Lane ID", self.lane_edit)
        form.addRow("Chiều", self.direction_combo)
        setup_layout.addWidget(source_box)

        roi_box = QGroupBox("Vùng quan sát trên frame bên phải")
        roi_layout = QVBoxLayout(roi_box)
        row = QHBoxLayout()
        for label, fn in (("Vẽ ROI", lambda: self._set_draw_mode("roi")),
                          ("Vẽ crossing line", lambda: self._set_draw_mode("line")),
                          ("Dừng vẽ", lambda: self._set_draw_mode("none")),
                          ("Xóa hình", self._clear_roi)):
            button = QPushButton(label)
            button.clicked.connect(fn)
            row.addWidget(button)
        roi_layout.addLayout(row)
        roi_layout.addWidget(QLabel("ROI: nhấp ≥3 điểm. Crossing line: nhấp 2 điểm. Khi có line, track mới phải vào corridor quanh line; ROI sẽ giới hạn thêm vùng hợp lệ."))
        setup_layout.addWidget(roi_box)

        settings = QGroupBox("Model và cắt clip")
        sf = QFormLayout(settings)
        self.model_edit = QLineEdit("yolo26s.pt")
        self.img_size = QSpinBox(); self.img_size.setRange(320, 1920); self.img_size.setSingleStep(32); self.img_size.setValue(960)
        self.sample_fps = QDoubleSpinBox(); self.sample_fps.setRange(1, 60); self.sample_fps.setValue(10); self.sample_fps.setSuffix(" FPS")
        self.confidence = QDoubleSpinBox(); self.confidence.setRange(0.01, 1); self.confidence.setSingleStep(0.01); self.confidence.setValue(0.12)
        self.hits = QSpinBox(); self.hits.setRange(1, 30); self.hits.setValue(2)
        self.min_motion = QDoubleSpinBox(); self.min_motion.setRange(0, 0.5); self.min_motion.setDecimals(3); self.min_motion.setSingleStep(0.005); self.min_motion.setValue(0.015); self.min_motion.setSuffix(" chuẩn hóa")
        self.motion_window = QDoubleSpinBox(); self.motion_window.setRange(0.1, 30); self.motion_window.setValue(1.5); self.motion_window.setSuffix(" s")
        self.line_gate_margin = QDoubleSpinBox(); self.line_gate_margin.setRange(0, 0.5); self.line_gate_margin.setSingleStep(0.01); self.line_gate_margin.setValue(0.12); self.line_gate_margin.setSuffix(" chuẩn hóa")
        self.grace = QDoubleSpinBox(); self.grace.setRange(0, 30); self.grace.setValue(1.5); self.grace.setSuffix(" s")
        self.pre = QDoubleSpinBox(); self.pre.setRange(0, 30); self.pre.setValue(1.5); self.pre.setSuffix(" s")
        self.post = QDoubleSpinBox(); self.post.setRange(0, 30); self.post.setValue(2); self.post.setSuffix(" s")
        self.make_clips = QCheckBox("Xuất từng MP4 và clip_final.mp4 nối theo thứ tự thời gian"); self.make_clips.setChecked(True)
        self.plate_ocr = QCheckBox("Gợi ý biển số bằng YOLO + PaddleOCR")
        self.plate_model_edit = QLineEdit("yolov8n-oiv7.pt")
        self.ocr_model_edit = QLineEdit("latin_PP-OCRv5_mobile_rec")
        self.condition_analysis = QCheckBox("Gợi ý điều kiện bằng CV + Qwen3-VL")
        self.condition_model_edit = QLineEdit("models/Qwen3-VL-2B-Instruct")
        self.condition_max_frames = QSpinBox(); self.condition_max_frames.setRange(1, 5); self.condition_max_frames.setValue(3)
        for label, widget in (("Weights", self.model_edit), ("Input detector", self.img_size), ("Detector FPS", self.sample_fps),
                              ("Confidence", self.confidence), ("Số lần thấy để xác nhận", self.hits),
                              ("Dịch chuyển tối thiểu", self.min_motion), ("Cửa sổ xác nhận chuyển động", self.motion_window),
                              ("Line gate margin", self.line_gate_margin),
                              ("Grace", self.grace), ("Buffer trước", self.pre), ("Buffer sau", self.post)):
            sf.addRow(label, widget)
        sf.addRow(self.make_clips)
        sf.addRow(self.plate_ocr)
        sf.addRow("Model biển số", self.plate_model_edit)
        sf.addRow("Model OCR", self.ocr_model_edit)
        sf.addRow(self.condition_analysis)
        sf.addRow("Model VLM điều kiện", self.condition_model_edit)
        sf.addRow("Frame điều kiện / event", self.condition_max_frames)
        setup_layout.addWidget(settings)
        run_row = QHBoxLayout()
        for label, fn in (("Lưu cấu hình", self._save_config), ("Mở cấu hình", self._load_config),
                          ("Chạy bước 1", self._start), ("Hủy", self._cancel)):
            button = QPushButton(label)
            button.clicked.connect(fn)
            run_row.addWidget(button)
            if label == "Chạy bước 1":
                self.run_button = button
        setup_layout.addLayout(run_row)
        self.progress = QProgressBar()
        self.status = QLabel("Sẵn sàng")
        setup_layout.addWidget(self.progress)
        setup_layout.addWidget(self.status)
        setup_layout.addStretch()

        review = QWidget()
        rv = QVBoxLayout(review)
        self.tabs.addTab(review, "Kết quả & GT")
        load_run = QPushButton("Mở run đã xử lý")
        load_run.clicked.connect(self._open_run)
        rv.addWidget(load_run)
        self.analyze_conditions_button = QPushButton("Phân tích điều kiện cho run này")
        self.analyze_conditions_button.clicked.connect(self._analyze_existing_run)
        rv.addWidget(self.analyze_conditions_button)
        self.events_table = QTableWidget(0, 6)
        self.events_table.setHorizontalHeaderLabels(["Event", "Loại", "Bắt đầu ms", "Kết thúc ms", "Crossing", "Clip"])
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.events_table.cellClicked.connect(self._open_selected_clip)
        self.events_table.cellDoubleClicked.connect(self._open_selected_clip)
        rv.addWidget(self.events_table)
        rv.addWidget(QLabel("GT độc lập: bấm event để nạp gợi ý, kiểm tra trên video raw/clip rồi chỉnh lại nếu cần. Event bị model bỏ sót có thể tạo thủ công bằng thanh trượt."))
        event_gt_row = QHBoxLayout()
        self.load_event_gt_button = QPushButton("Nạp event vào GT")
        self.load_event_gt_button.clicked.connect(self._load_selected_event_to_gt)
        event_gt_row.addWidget(self.load_event_gt_button)
        event_gt_row.addStretch()
        rv.addLayout(event_gt_row)
        mark_row = QHBoxLayout()
        for label, fn in (("Đặt đầu", self._mark_start), ("Đặt cuối", self._mark_end),
                          ("Frame đọc được", self._mark_readable)):
            button = QPushButton(label); button.clicked.connect(fn); mark_row.addWidget(button)
        self.add_gt_button = QPushButton("Thêm GT")
        self.add_gt_button.clicked.connect(self._add_gt)
        mark_row.addWidget(self.add_gt_button)
        self.update_gt_button = QPushButton("Cập nhật GT")
        self.update_gt_button.clicked.connect(self._update_gt)
        self.update_gt_button.setEnabled(False)
        mark_row.addWidget(self.update_gt_button)
        rv.addLayout(mark_row)
        gt_row = QHBoxLayout()
        self.gt_type = QComboBox(); self.gt_type.addItems(["car", "motorcycle", "bicycle"])
        self.gt_type.currentTextChanged.connect(self._vehicle_type_changed)
        self.gt_text = QLineEdit(); self.gt_text.setPlaceholderText("Biển số (tùy chọn)")
        gt_row.addWidget(self.gt_type); gt_row.addWidget(self.gt_text)
        rv.addLayout(gt_row)
        self.condition_checks = {}
        condition_box = QGroupBox("Khả năng đọc và nguyên nhân không đọc được (người gán xác nhận)")
        condition_layout = QVBoxLayout(condition_box)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Đánh giá:"))
        self.condition_status = QComboBox()
        self.condition_status.addItem("Good — biển số có khả năng đọc được", "good")
        self.condition_status.addItem("Không đọc được", "unreadable")
        self.condition_status.addItem("Không áp dụng — xe đạp không có biển số", "not_applicable")
        self.condition_status.currentIndexChanged.connect(self._condition_status_changed)
        status_row.addWidget(self.condition_status)
        status_row.addStretch()
        condition_layout.addLayout(status_row)
        row = QHBoxLayout()
        labels = {
            "capture_blur": "capture_blur — camera làm mờ",
            "plate_obstruction": "plate_obstruction — vật thể che biển",
            "lighting_issue": "lighting_issue — ánh sáng cản trở",
        }
        for root in CONDITION_TYPES:
            root_check = QCheckBox(root)
            root_check.setText(labels[root])
            self.condition_checks[root] = root_check
            row.addWidget(root_check)
        row.addStretch()
        condition_layout.addLayout(row)
        self.condition_evidence = QLabel("Chưa có gợi ý điều kiện")
        self.condition_evidence.setWordWrap(True)
        condition_layout.addWidget(self.condition_evidence)
        rv.addWidget(condition_box)
        gt_detail_row = QHBoxLayout()
        gt_detail_row.addWidget(QLabel("Khả năng đọc biển:"))
        self.gt_readability = QComboBox()
        for label, value in (("Chưa xác định", "unknown"), ("Không đọc được", "unreadable"),
                             ("Đọc được 1 frame", "single_frame_readable"),
                             ("Đọc được nhiều frame", "multi_frame_readable"),
                             ("Đọc một phần", "partially_readable"),
                             ("Ngoài khung hình", "out_of_view"),
                             ("Không áp dụng — xe đạp", "not_applicable")):
            self.gt_readability.addItem(label, value)
        gt_detail_row.addWidget(self.gt_readability)
        gt_detail_row.addWidget(QLabel("Crossed:"))
        self.gt_crossed = QComboBox()
        self.gt_crossed.addItem("True", True)
        self.gt_crossed.addItem("False", False)
        self.gt_crossed.setCurrentIndex(1)
        gt_detail_row.addWidget(self.gt_crossed)
        gt_detail_row.addStretch()
        rv.addLayout(gt_detail_row)
        self.gt_status = QLabel("GT: chưa đánh dấu")
        rv.addWidget(self.gt_status)
        self.gt_table = QTableWidget(0, len(self.GT_TABLE_COLUMNS))
        self.gt_table.setHorizontalHeaderLabels([label for _, label in self.GT_TABLE_COLUMNS])
        self.gt_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.gt_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.gt_table.cellClicked.connect(self._select_gt_for_edit)
        self.gt_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.gt_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.gt_table.setWordWrap(False)
        rv.addWidget(self.gt_table)
        gt_actions = QHBoxLayout()
        for label, fn in (("Lưu GT", self._save_gt), ("Mở GT", self._load_gt),
                          ("Xóa GT đã chọn", self._delete_gt), ("Đánh giá bước 1", self._evaluate)):
            button = QPushButton(label); button.clicked.connect(fn); gt_actions.addWidget(button)
        rv.addLayout(gt_actions)
        self.metrics = QLabel("Chưa đánh giá")
        self.metrics.setWordWrap(True)
        rv.addWidget(self.metrics)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)
        self.canvas = VideoCanvas()
        self.canvas.geometry_changed.connect(self._validate_drawn_geometry)
        right_layout.addWidget(self.canvas, 1)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.valueChanged.connect(self._show_time)
        right_layout.addWidget(self.seek)
        self.time_label = QLabel("0 ms")
        right_layout.addWidget(self.time_label)

        clip_box = QGroupBox("Trình phát clip / virtual segment")
        clip_layout = QVBoxLayout(clip_box)
        clip_row = QHBoxLayout()
        self.play_clip_button = QPushButton("▶ Phát clip")
        self.pause_clip_button = QPushButton("⏸ Tạm dừng")
        self.stop_clip_button = QPushButton("⏹ Về đầu")
        self.play_clip_button.clicked.connect(self._play_clip)
        self.pause_clip_button.clicked.connect(self._pause_clip)
        self.stop_clip_button.clicked.connect(self._stop_clip_and_reset)
        clip_row.addWidget(self.play_clip_button)
        clip_row.addWidget(self.pause_clip_button)
        clip_row.addWidget(self.stop_clip_button)
        self.clip_label = QLabel("Chọn event để mở clip")
        clip_row.addWidget(self.clip_label, 1)
        clip_layout.addLayout(clip_row)
        self.clip_seek = QSlider(Qt.Orientation.Horizontal)
        self.clip_seek.setRange(0, 0)
        self.clip_seek.valueChanged.connect(self._seek_clip)
        clip_layout.addWidget(self.clip_seek)
        self.clip_time_label = QLabel("Clip: 0.00 s")
        clip_layout.addWidget(self.clip_time_label)
        self.clip_detection_label = QLabel("YOLO + ByteTrack: chưa chọn event")
        self.clip_detection_label.setWordWrap(True)
        clip_layout.addWidget(self.clip_detection_label)
        right_layout.addWidget(clip_box)
        self._set_clip_controls_enabled(False)
        splitter.setSizes([570, 830])

    def _tab_changed(self, index: int) -> None:
        # The configuration tab always shows the raw video on the right.  A
        # selected result event owns the clip player until the user returns to
        # configuration, at which point the raw timeline is restored.
        if index == 0 and self.clip_capture is not None:
            self._close_clip()
            self._show_time(self.seek.value())

    def _browse_row(self, edit, callback):
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit); button = QPushButton("…"); button.clicked.connect(callback); row.addWidget(button)
        return box

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn video raw", "", "Video (*.mp4 *.avi *.mov *.mkv);;All files (*)")
        if path:
            self.source_edit.setText(path)
            self._open_source(path)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục đầu ra")
        if path:
            self.output_edit.setText(path)

    def _load_detection_artifact(self) -> None:
        self.detection_records = []
        self.plate_records = {}
        self.condition_records = {}
        if not self.run_result:
            return
        run_dir = Path(self.run_result["run_dir"])
        run = self.run_result.get("run", {})
        artifact_uri = run.get("artifacts", {}).get("detections_uri", "detections.jsonl")
        path = run_dir / artifact_uri
        if path.is_file():
            try:
                self.detection_records = load_jsonl(path)
            except Exception as exc:
                self.status.setText(f"Không đọc được detection artifact: {exc}")
        plate_uri = run.get("artifacts", {}).get("plate_observations_uri")
        if plate_uri:
            plate_path = run_dir / plate_uri
            if plate_path.is_file():
                self.plate_records = {item["event_id"]: item for item in load_jsonl(plate_path)}
        condition_uri = run.get("artifacts", {}).get("condition_suggestions_uri")
        if condition_uri:
            condition_path = run_dir / condition_uri
            if condition_path.is_file():
                self.condition_records = {item["event_id"]: item for item in load_jsonl(condition_path)}

    def _open_source(self, path):
        self._close_clip()
        self.detection_records = []
        if self.source_capture:
            self.source_capture.release()
        try:
            self.source_info = video_info(path)
            self.source_capture = cv2.VideoCapture(path)
            if not self.source_capture.isOpened():
                raise RuntimeError("OpenCV không mở được video")
        except Exception as exc:
            self.source_info = None
            self.source_capture = None
            self.seek.setRange(0, 0)
            QMessageBox.critical(self, "Video không hợp lệ", str(exc))
            return
        self.seek.setRange(0, self.source_info["duration_ms"])
        self.seek.setValue(0)
        self._show_time(0)

    def _show_time(self, ms):
        # Moving the raw timeline switches the canvas back from the embedded
        # clip player to the source video.
        if self.clip_capture is not None:
            self._close_clip()
        self.time_label.setText(f"{ms / 1000:.2f} s / {(self.source_info or {}).get('duration_ms', 0) / 1000:.2f} s")
        if not self.source_capture or not self.source_info:
            return
        frame_idx = min(self.source_info["frame_count"] - 1, round(ms * self.source_info["fps"] / 1000))
        self.source_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = self.source_capture.read()
        if ok:
            self.canvas.show_frame(frame)

    def _set_clip_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.play_clip_button, self.pause_clip_button, self.stop_clip_button, self.clip_seek):
            widget.setEnabled(enabled)

    def _close_clip(self) -> None:
        self.clip_timer.stop()
        if self.clip_capture is not None:
            self.clip_capture.release()
        self.clip_capture = None
        self.clip_path = None
        self.clip_fps = 0.0
        self.clip_duration_ms = 0
        self.clip_source_offset_ms = 0
        self.clip_artifact_offset_ms = 0
        self.clip_current_ms = 0
        self.active_event = None
        self.clip_seek.blockSignals(True)
        self.clip_seek.setRange(0, 0)
        self.clip_seek.setValue(0)
        self.clip_seek.blockSignals(False)
        self.clip_time_label.setText("Clip: 0.00 s")
        self.clip_label.setText("Chọn event để mở clip")
        self.clip_detection_label.setText("YOLO + ByteTrack: chưa chọn event")
        self.canvas.clear_detection_overlay()
        self._set_clip_controls_enabled(False)

    def _load_clip(self, clip: dict, event: dict) -> None:
        self._close_clip()
        self.active_event = event
        run_dir = Path(self.run_result["run_dir"])
        clip_uri = clip.get("clip_uri")
        is_virtual = not clip_uri
        if is_virtual:
            # A virtual segment is still directly viewable: seek the raw file
            # while exposing only the segment's relative timeline in the UI.
            path = Path(self.run_result["run"]["source"]["uri"])
            source_offset_ms = int(clip["start_ms"])
            artifact_offset_ms = source_offset_ms
            duration_ms = int(clip["end_ms"] - clip["start_ms"])
            label_suffix = "virtual segment trên raw"
        else:
            path = run_dir / clip_uri
            source_offset_ms = 0
            start = clip.get("actual_start_ms", clip["start_ms"])
            end = clip.get("actual_end_ms", clip["end_ms"])
            artifact_offset_ms = int(start)
            duration_ms = int(end - start)
            label_suffix = "MP4"
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            QMessageBox.warning(self, "Mở clip", f"Không mở được clip: {path}")
            return
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            fps = float((self.source_info or {}).get("fps", 30.0))
        if duration_ms <= 0:
            duration_ms = max(1, round(capture.get(cv2.CAP_PROP_FRAME_COUNT) * 1000 / fps))
        self.clip_capture = capture
        self.clip_path = path
        self.clip_fps = fps
        self.clip_duration_ms = duration_ms
        self.clip_source_offset_ms = source_offset_ms
        self.clip_artifact_offset_ms = artifact_offset_ms
        self.clip_seek.setRange(0, duration_ms)
        self._set_clip_controls_enabled(True)
        self.clip_label.setText(f"{clip['clip_id']} — {label_suffix} — {event['event_id']}")
        if is_virtual:
            relative_start = event["start_ms"] - clip["start_ms"]
        else:
            relative_start = event["start_ms"] - clip.get("actual_start_ms", clip["start_ms"])
        self._seek_clip(max(0, min(duration_ms, int(relative_start))))

    def _detections_at_source_time(self, source_ms: int) -> list[dict]:
        if not self.detection_records:
            return []
        record = min(self.detection_records,
                     key=lambda item: abs(int(item.get("timestamp_ms", 0)) - source_ms))
        nearest_delta = abs(int(record.get("timestamp_ms", 0)) - source_ms)
        # Detection artifacts are written at detector sample cadence.  A
        # generous bound keeps the overlay useful while avoiding a stale box
        # when a clip seeks across a long gap in the artifact.
        if nearest_delta > 250:
            return []
        return list(record.get("detections", []))

    def _event_detection_at_source_time(self, source_ms: int, event: dict) -> dict | None:
        """Return the selected event track's nearest sampled box for its span.

        Detector artifacts are sampled less often than the video player.  The
        ordinary overlay intentionally drops stale records, but that makes the
        selected event disappear while scrubbing between sparse samples.  For
        the selected event only, hold the nearest box inside event.start/end;
        this keeps review continuous without extending the box into the clip
        buffer after the event has ended.
        """
        track_id = event.get("track_id")
        if track_id is None:
            return None
        start_ms = int(event.get("start_ms", source_ms))
        end_ms = int(event.get("end_ms", source_ms))
        if not start_ms <= source_ms <= end_ms:
            return None
        candidates: list[tuple[int, dict]] = []
        for record in self.detection_records:
            timestamp_ms = int(record.get("timestamp_ms", 0))
            if not start_ms <= timestamp_ms <= end_ms:
                continue
            for detection in record.get("detections", []):
                if detection.get("track_id") == track_id:
                    candidates.append((abs(timestamp_ms - source_ms), detection))
        first_detection = event.get("first_detection")
        if first_detection and first_detection.get("track_id") == track_id:
            first_ms = int(first_detection.get("timestamp_ms", start_ms))
            if start_ms <= first_ms <= end_ms:
                candidates.append((abs(first_ms - source_ms), first_detection))
        if not candidates:
            return None
        return dict(min(candidates, key=lambda item: item[0])[1])

    def _plates_at_source_time(self, source_ms: int, event: dict) -> list[dict]:
        """Keep the nearest plate observation visible throughout the event."""
        record = self.plate_records.get(event.get("event_id"), {})
        observations = list(record.get("observations", []))
        if not observations:
            return []
        start_ms = int(event.get("start_ms", source_ms))
        end_ms = int(event.get("end_ms", source_ms))
        if start_ms <= source_ms <= end_ms:
            nearest = min(observations,
                          key=lambda item: abs(int(item.get("timestamp_ms", 0)) - source_ms))
            nearest_ms = int(nearest.get("timestamp_ms", source_ms))
            return [item for item in observations
                    if int(item.get("timestamp_ms", 0)) == nearest_ms]
        return [item for item in observations
                if abs(int(item.get("timestamp_ms", 0)) - source_ms) <= 100]

    def _show_clip_frame(self, frame, source_ms: int) -> None:
        detections = self._detections_at_source_time(source_ms)
        event = self.active_event or {}
        persistent_detection = self._event_detection_at_source_time(source_ms, event)
        if persistent_detection is not None:
            # Keep contextual boxes from the current sampled record, but
            # replace the selected track with its nearest event-time box.
            target_id = event.get("track_id")
            detections = [item for item in detections if item.get("track_id") != target_id]
            detections.append(persistent_detection)
        first_detection = event.get("first_detection")
        first_ms = int(first_detection.get("timestamp_ms", event.get("start_ms", source_ms))) if first_detection else None
        if first_detection and abs(source_ms - first_ms) <= 250:
            # Keep the event's first box visible even if an old artifact was
            # generated without this exact timestamp.
            target_id = first_detection.get("track_id")
            if not any(item.get("track_id") == target_id for item in detections):
                detections.append(first_detection)
        at_first = first_ms is not None and abs(source_ms - first_ms) <= 100
        title = f"{event.get('event_id', 'Event')} | source {source_ms} ms"
        if at_first:
            title += " | FRAME ĐẦU EVENT"
        plates = self._plates_at_source_time(source_ms, event)
        self.canvas.show_frame(frame, detections=detections,
                               highlight_track_id=event.get("track_id"),
                               overlay_title=title, plates=plates)
        if detections:
            selected = sum(1 for item in detections if item.get("track_id") == event.get("track_id"))
            marker = "frame đầu event" if at_first else "đang phát"
            self.clip_detection_label.setText(
                f"YOLO + ByteTrack: {len(detections)} box tại {source_ms} ms; "
                f"track event #{event.get('track_id', '?')} ({selected} box) — {marker}")
        else:
            self.clip_detection_label.setText(
                "YOLO + ByteTrack: không có detection artifact gần frame hiện tại")

    def _seek_clip(self, ms: int) -> None:
        if self.clip_capture is None or self.clip_fps <= 0:
            return
        ms = max(0, min(int(ms), self.clip_duration_ms))
        source_ms = self.clip_source_offset_ms + ms
        frame_index = max(0, round(source_ms * self.clip_fps / 1000))
        self.clip_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.clip_capture.read()
        if not ok:
            return
        actual_frame = max(0, int(self.clip_capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        self.clip_current_ms = max(0, min(self.clip_duration_ms,
                                          round(actual_frame * 1000 / self.clip_fps - self.clip_source_offset_ms)))
        self.clip_seek.blockSignals(True)
        self.clip_seek.setValue(self.clip_current_ms)
        self.clip_seek.blockSignals(False)
        self.clip_time_label.setText(f"Clip: {self.clip_current_ms / 1000:.2f} s / {self.clip_duration_ms / 1000:.2f} s")
        self._show_clip_frame(frame, self.clip_artifact_offset_ms + self.clip_current_ms)

    def _advance_clip(self) -> None:
        if self.clip_capture is None or self.clip_fps <= 0:
            self.clip_timer.stop()
            return
        ok, frame = self.clip_capture.read()
        if not ok:
            self.clip_timer.stop()
            return
        actual_frame = max(0, int(self.clip_capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        self.clip_current_ms = max(0, round(actual_frame * 1000 / self.clip_fps - self.clip_source_offset_ms))
        self._show_clip_frame(frame, self.clip_artifact_offset_ms + self.clip_current_ms)
        self.clip_seek.blockSignals(True)
        self.clip_seek.setValue(min(self.clip_duration_ms, self.clip_current_ms))
        self.clip_seek.blockSignals(False)
        self.clip_time_label.setText(f"Clip: {self.clip_current_ms / 1000:.2f} s / {self.clip_duration_ms / 1000:.2f} s")
        if self.clip_current_ms >= self.clip_duration_ms:
            self.clip_timer.stop()

    def _play_clip(self) -> None:
        if self.clip_capture is None:
            return
        if self.clip_current_ms >= self.clip_duration_ms:
            self._seek_clip(0)
        self.clip_timer.start(max(15, round(1000 / self.clip_fps)))

    def _pause_clip(self) -> None:
        self.clip_timer.stop()

    def _stop_clip_and_reset(self) -> None:
        self.clip_timer.stop()
        if self.clip_capture is not None:
            self._seek_clip(0)

    def _set_draw_mode(self, mode):
        self.canvas.mode = mode
        self.status.setText(f"Chế độ vẽ: {mode}")

    def _clear_roi(self):
        self.canvas.roi.clear(); self.canvas.line.clear(); self.canvas.update()

    def _validate_drawn_geometry(self) -> None:
        if len(self.canvas.roi) < 3 or len(self.canvas.line) != 2:
            return
        if line_intersects_roi(self.canvas.line, self.canvas.roi):
            return
        self.canvas.line.clear()
        self.canvas.update()
        self.status.setText("Crossing line ngoài ROI — đã xóa line không hợp lệ")
        QMessageBox.warning(
            self,
            "Crossing line không hợp lệ",
            "Crossing line nằm hoàn toàn ngoài ROI. Line phải cắt qua, nằm trong hoặc chạm biên ROI. "
            "Corridor chạm ROI không được xem là hợp lệ; line vừa vẽ đã được xóa.",
        )

    def _config(self):
        config = RunConfig(
            camera=CameraConfig(self.camera_edit.text().strip(), self.lane_edit.text().strip(),
                                self.direction_combo.currentText(), list(self.canvas.roi), list(self.canvas.line)),
            source=self.source_edit.text().strip(), output_dir=self.output_edit.text().strip(),
            model=self.model_edit.text().strip(), image_size=self.img_size.value(),
            sample_fps=self.sample_fps.value(), confidence=self.confidence.value(),
            candidate_hits=self.hits.value(), min_motion_distance=self.min_motion.value(),
            motion_window_seconds=self.motion_window.value(), line_gate_margin=self.line_gate_margin.value(), grace_seconds=self.grace.value(),
            pre_seconds=self.pre.value(), post_seconds=self.post.value(), make_clips=self.make_clips.isChecked(),
            plate_ocr_enabled=self.plate_ocr.isChecked(), plate_model=self.plate_model_edit.text().strip(),
            ocr_model=self.ocr_model_edit.text().strip(),
            condition_analysis_enabled=self.condition_analysis.isChecked(),
            condition_vlm_model=self.condition_model_edit.text().strip(),
            condition_max_frames=self.condition_max_frames.value(),
        )
        config.validate()
        return config

    def _save_config(self):
        try:
            config = self._config()
            path, _ = QFileDialog.getSaveFileName(self, "Lưu cấu hình", "camera_run.json", "JSON (*.json)")
            if path:
                config.save(path)
        except Exception as exc:
            QMessageBox.warning(self, "Cấu hình", str(exc))

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở cấu hình", "", "JSON (*.json)")
        if not path:
            return
        try:
            config = RunConfig.load(path); config.validate()
            self.source_edit.setText(config.source); self.output_edit.setText(config.output_dir)
            self.camera_edit.setText(config.camera.camera_id); self.lane_edit.setText(config.camera.lane_id)
            self.direction_combo.setCurrentText(config.camera.direction)
            self.canvas.roi = config.camera.roi; self.canvas.line = config.camera.crossing_line
            self.model_edit.setText(config.model); self.img_size.setValue(config.image_size)
            self.sample_fps.setValue(config.sample_fps); self.confidence.setValue(config.confidence)
            self.hits.setValue(config.candidate_hits); self.min_motion.setValue(config.min_motion_distance); self.motion_window.setValue(config.motion_window_seconds); self.line_gate_margin.setValue(config.line_gate_margin); self.grace.setValue(config.grace_seconds)
            self.pre.setValue(config.pre_seconds); self.post.setValue(config.post_seconds)
            self.make_clips.setChecked(config.make_clips)
            self.plate_ocr.setChecked(config.plate_ocr_enabled)
            self.plate_model_edit.setText(config.plate_model)
            self.ocr_model_edit.setText(config.ocr_model)
            self.condition_analysis.setChecked(config.condition_analysis_enabled)
            self.condition_model_edit.setText(config.condition_vlm_model)
            self.condition_max_frames.setValue(config.condition_max_frames)
            self._open_source(config.source)
        except Exception as exc:
            QMessageBox.warning(self, "Cấu hình", str(exc))

    def _start(self):
        try:
            config = self._config()
        except Exception as exc:
            QMessageBox.warning(self, "Cấu hình", str(exc)); return
        self.worker = PipelineWorker(config)
        self.worker.progress_signal.connect(self._progress)
        self.worker.result_signal.connect(self._finished)
        self.worker.error_signal.connect(self._failed)
        self.run_button.setEnabled(False)
        self.progress.setValue(0)
        self.worker.start()

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_requested = True
            self.status.setText("Đang hủy sau frame hiện tại…")

    def _progress(self, value, message):
        self.progress.setValue(value); self.status.setText(message)

    def _finished(self, result):
        self.run_button.setEnabled(True)
        self.run_result = result
        self._load_detection_artifact()
        self._fill_events()
        self.tabs.setCurrentIndex(1)
        self.status.setText(f"Hoàn thành: {result['run_dir']}")

    def _failed(self, message):
        self.run_button.setEnabled(True)
        self.analyze_conditions_button.setEnabled(True)
        self.status.setText(message)
        QMessageBox.critical(self, "Bước 1 thất bại", message)

    def _analyze_existing_run(self):
        if not self.run_result:
            QMessageBox.warning(self, "Điều kiện", "Cần mở một run trước")
            return
        if self.worker and self.worker.isRunning():
            return
        config = RunConfig.from_dict(self.run_result["run"]["config"])
        config.condition_vlm_model = self.condition_model_edit.text().strip()
        config.condition_max_frames = self.condition_max_frames.value()
        self.worker = ConditionWorker(self.run_result["run_dir"], config)
        self.worker.progress_signal.connect(self._progress)
        self.worker.result_signal.connect(self._conditions_finished)
        self.worker.error_signal.connect(self._failed)
        self.analyze_conditions_button.setEnabled(False)
        self.progress.setValue(0)
        self.worker.start()

    def _conditions_finished(self, _run_dir):
        self.analyze_conditions_button.setEnabled(True)
        run_path = Path(self.run_result["run_dir"]) / "run.json"
        self.run_result["run"] = json.loads(run_path.read_text(encoding="utf-8"))
        self._load_detection_artifact()
        row = self.events_table.currentRow()
        if row >= 0:
            self._prefill_gt_from_event(self.run_result["events"][row])
        self.status.setText(f"Đã gợi ý điều kiện cho {len(self.condition_records)} event")

    def _open_run(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn run.json", self.output_edit.text(), "JSON (*.json)")
        if not path:
            return
        try:
            directory = Path(path).parent
            run = json.loads(Path(path).read_text(encoding="utf-8"))
            self.run_result = {"run_dir": str(directory), "run": run,
                               "events": load_jsonl(directory / "events.jsonl"),
                               "clips": load_jsonl(directory / "clips.jsonl")}
            self.source_edit.setText(run["config"]["source"])
            self.camera_edit.setText(run["config"]["camera"]["camera_id"])
            self.lane_edit.setText(run["config"]["camera"]["lane_id"])
            self.direction_combo.setCurrentText(run["config"]["camera"]["direction"])
            self.canvas.roi = run["config"]["camera"].get("roi", [])
            self.canvas.line = run["config"]["camera"].get("crossing_line", [])
            self._open_source(run["config"]["source"])
            self._load_detection_artifact()
            self._fill_events()
            self.tabs.setCurrentIndex(1)
        except Exception as exc:
            QMessageBox.warning(self, "Mở run", str(exc))

    def _fill_events(self):
        events = self.run_result["events"] if self.run_result else []
        self.events_table.setRowCount(len(events))
        for row, event in enumerate(events):
            for col, key in enumerate(("event_id", "vehicle_type", "start_ms", "end_ms", "crossed", "clip_id")):
                self.events_table.setItem(row, col, QTableWidgetItem(str(event.get(key, ""))))
        self.events_table.resizeColumnsToContents()

    def _open_selected_clip(self, row, _column):
        if not self.run_result:
            return
        event = self.run_result["events"][row]
        clip = next((c for c in self.run_result["clips"] if c["clip_id"] == event["clip_id"]), None)
        if not clip:
            return
        self._prefill_gt_from_event(event)
        # Selecting either a cell or the whole row opens the clip and seeks
        # to this event's start on the clip-relative timeline.
        self._load_clip(clip, event)
        self.status.setText(f"Đang xem {event['event_id']} từ {event['start_ms']} ms")

    def _load_selected_event_to_gt(self):
        if not self.run_result:
            QMessageBox.warning(self, "Ground truth", "Cần mở một run trước")
            return
        row = self.events_table.currentRow()
        if row < 0 or row >= len(self.run_result["events"]):
            QMessageBox.warning(self, "Ground truth", "Hãy chọn một event trước")
            return
        self._prefill_gt_from_event(self.run_result["events"][row])

    def _set_gt_edit_controls(self, editing: bool) -> None:
        self.update_gt_button.setEnabled(editing)
        self.add_gt_button.setText("Thêm GT mới" if editing else "Thêm GT")

    def _set_gt_crossed(self, value) -> None:
        normalized = self._coerce_bool(value, False)
        index = self.gt_crossed.findData(normalized)
        self.gt_crossed.setCurrentIndex(index if index >= 0 else 1)

    def _condition_status_changed(self, *_args) -> None:
        status = self.condition_status.currentData()
        good = status == "good"
        issues_enabled = status == "unreadable"
        for check in self.condition_checks.values():
            check.setEnabled(issues_enabled)
            if not issues_enabled:
                check.setChecked(False)
        if hasattr(self, "gt_readability"):
            current = self.gt_readability.currentData()
            if good and current in {None, "unknown", "unreadable", "out_of_view"}:
                self.gt_readability.setCurrentIndex(
                    self.gt_readability.findData("single_frame_readable"))
            elif not good:
                target = "not_applicable" if status == "not_applicable" else "unreadable"
                self.gt_readability.setCurrentIndex(self.gt_readability.findData(target))

    def _vehicle_type_changed(self, vehicle_type: str) -> None:
        bicycle = vehicle_type == "bicycle"
        self.gt_text.setEnabled(not bicycle)
        self.condition_status.setEnabled(not bicycle)
        if hasattr(self, "gt_readability"):
            self.gt_readability.setEnabled(not bicycle)
        if bicycle:
            self.gt_text.clear()
            self._set_conditions([], "not_applicable")
        elif self.condition_status.currentData() == "not_applicable":
            self._set_conditions([], "good")

    def _set_conditions(self, roots, status=None) -> None:
        status = status or ("unreadable" if roots else "good")
        index = self.condition_status.findData(status)
        self.condition_status.setCurrentIndex(max(0, index))
        for root, check in self.condition_checks.items():
            check.setChecked(root in roots)
        self._condition_status_changed()

    def _selected_conditions(self) -> tuple[str, list[str]]:
        status = self.condition_status.currentData() or "good"
        roots = [root for root, check in self.condition_checks.items() if check.isChecked()]
        return status, [] if status == "good" else roots

    def _set_raw_annotation_time(self, timestamp_ms: int) -> None:
        if not self.source_info:
            return
        timestamp_ms = max(0, min(int(timestamp_ms), int(self.source_info["duration_ms"])))
        if self.clip_capture is not None:
            # Do not switch away from the selected clip while editing GT.
            self.seek.blockSignals(True)
            self.seek.setValue(timestamp_ms)
            self.seek.blockSignals(False)
            return
        self.seek.setValue(timestamp_ms)

    def _prefill_gt_from_event(self, event: dict) -> None:
        event_id = event.get("event_id")
        self.annotation_event_id = event_id
        crossed = self._coerce_bool(event.get("crossed"), False)
        crossed_suggestion = {
            "value": crossed, "source": "model1_event", "event_id": event_id,
        }
        self.gt_suggestions = {
            "start_ms": {"value": event.get("start_ms"), "source": "model1_event", "event_id": event_id},
            "end_ms": {"value": event.get("end_ms"), "source": "model1_event", "event_id": event_id},
            "vehicle_type": {"value": event.get("vehicle_type"), "source": "model1_event", "event_id": event_id},
            "crossed": crossed_suggestion,
        }
        self.gt_start = int(event.get("start_ms", 0))
        self.gt_end = int(event.get("end_ms", 0))
        self.gt_readable.clear()
        self.gt_type.setCurrentText(event.get("vehicle_type", "car"))
        self.gt_text.clear()
        plate_record = self.plate_records.get(event_id, {})
        plate_consensus = plate_record.get("consensus")
        if plate_consensus and plate_consensus.get("text"):
            self.gt_text.setText(plate_consensus["text"])
            self.gt_suggestions["plate_text"] = {
                "value": plate_consensus["text"], "source": "plate_ocr",
                "event_id": event_id, "confidence": plate_consensus["confidence"],
            }
        self.gt_readability.setCurrentIndex(self.gt_readability.findData("unknown"))
        condition_record = self.condition_records.get(event_id, {})
        roots = condition_record.get("conditions", [])
        condition_status = condition_record.get(
            "condition_status", "not_applicable" if event.get("vehicle_type") == "bicycle" else
            "good" if not condition_record or condition_record.get("plate_readable") else "unreadable")
        self._set_conditions(roots, condition_status)
        if condition_record:
            self.gt_suggestions["conditions"] = {
                "value": roots, "condition_status": condition_status,
                "plate_readable": condition_record.get("plate_readable"), "source": "cv_vlm",
                "event_id": event_id,
                "evidence_timestamps_ms": condition_record.get("evidence_timestamps_ms", []),
            }
            self.condition_evidence.setText(
                f"Gợi ý CV + VLM; frame: {condition_record.get('evidence_timestamps_ms', [])} ms. "
                "Kiểm tra video và chỉnh nhãn trước khi lưu GT.")
            suggested_readability = ("not_applicable" if condition_status == "not_applicable" else
                                     "multi_frame_readable" if condition_record.get("plate_readable") else "unreadable")
            self.gt_readability.setCurrentIndex(max(0, self.gt_readability.findData(suggested_readability)))
        else:
            self.condition_evidence.setText("Chưa có gợi ý điều kiện cho event này")
        self._set_gt_crossed(crossed)
        existing_index = next((index for index, item in enumerate(self.gt_events)
                               if item.get("source_event_id") == event_id), None)
        if existing_index is not None:
            self._load_gt_record(self.gt_events[existing_index], existing_index)
            # Preserve the current model suggestion when loading a legacy GT
            # record that predates the crossed suggestion.
            self.gt_suggestions.setdefault("crossed", crossed_suggestion)
        else:
            self.gt_edit_index = None
            self._set_gt_edit_controls(False)
            self._set_raw_annotation_time(self.gt_start)
            self.gt_status.setText(
                f"Gợi ý từ {event_id}: đầu={self.gt_start} ms; cuối={self.gt_end} ms; "
                f"crossed={crossed} — "
                "hãy kiểm tra video raw trước khi thêm GT")

    def _load_gt_record(self, event: dict, index: int) -> None:
        self.gt_edit_index = index
        self.annotation_event_id = event.get("source_event_id")
        self.gt_suggestions = dict(event.get("suggestions") or {})
        self.gt_start = int(event.get("start_ms", 0))
        self.gt_end = int(event.get("end_ms", 0))
        self.gt_readable = list(event.get("readable_timestamps_ms", []))
        self.gt_type.setCurrentText(event.get("vehicle_type", "car"))
        self.gt_text.setText(event.get("plate_text") or "")
        self._set_conditions(
            event.get("conditions", []),
            "not_applicable" if event.get("vehicle_type") == "bicycle" else event.get("condition_status"))
        self.condition_evidence.setText("Nhãn GT đã lưu; nguồn: người gán")
        self.gt_readability.setCurrentIndex(
            max(0, self.gt_readability.findData(event.get("plate_readability", "unknown"))))
        self._set_gt_crossed(event.get("crossed", False))
        self._set_gt_edit_controls(True)
        self._set_raw_annotation_time(self.gt_start)
        self._update_gt_status()

    def _current_annotation_ms(self) -> int:
        if self.clip_capture is not None:
            return max(0, int(self.clip_artifact_offset_ms + self.clip_current_ms))
        return int(self.seek.value())

    def _mark_start(self):
        self.gt_start = self._current_annotation_ms(); self._update_gt_status()

    def _mark_end(self):
        self.gt_end = self._current_annotation_ms(); self._update_gt_status()

    def _mark_readable(self):
        self.gt_readable.append(self._current_annotation_ms()); self._update_gt_status()

    def _update_gt_status(self):
        source = f" | đang sửa {self.gt_events[self.gt_edit_index]['gt_event_id']}" \
            if self.gt_edit_index is not None and self.gt_edit_index < len(self.gt_events) else ""
        self.gt_status.setText(
            f"GT đầu={self.gt_start} ms; cuối={self.gt_end} ms; "
            f"frame đọc được={sorted(set(self.gt_readable))}; "
            f"khả năng đọc={self.gt_readability.currentData()}; "
            f"crossed={self.gt_crossed.currentData()}{source}")

    def _collect_gt_record(self, gt_event_id: str | None = None) -> dict:
        condition_status, roots = self._selected_conditions()
        readability = self.gt_readability.currentData() or "unknown"
        if condition_status == "not_applicable":
            readability = "not_applicable"
        elif condition_status == "good" and readability not in {
                "single_frame_readable", "multi_frame_readable", "partially_readable"}:
            readability = "single_frame_readable"
        elif condition_status == "unreadable":
            readability = "unreadable"
        return {
            "annotation_schema_version": "0.6.0",
            "gt_event_id": gt_event_id or f"GT-{len(self.gt_events) + 1:06d}",
            "source_event_id": self.annotation_event_id,
            "source_uri": self.source_edit.text().strip(), "camera_id": self.camera_edit.text().strip(),
            "lane_id": self.lane_edit.text().strip(), "direction": self.direction_combo.currentText(),
            "vehicle_type": self.gt_type.currentText(), "start_ms": self.gt_start, "end_ms": self.gt_end,
            "crossed": self._coerce_bool(self.gt_crossed.currentData(), False),
            "readable_timestamps_ms": sorted(set(x for x in self.gt_readable if self.gt_start <= x <= self.gt_end)),
            "plate_readability": readability,
            "plate_readable": None if condition_status == "not_applicable" else condition_status == "good",
            "plate_text": None if condition_status == "not_applicable" else self.gt_text.text().strip() or None,
            "condition_status": condition_status,
            "conditions": roots,
            "suggestions": dict(self.gt_suggestions),
            "condition_annotation_source": "human",
            "annotation_source": "human",
        }

    def _add_gt(self):
        if not self.source_info or self.gt_start is None or self.gt_end is None or self.gt_end <= self.gt_start:
            QMessageBox.warning(self, "Ground truth", "Cần đánh dấu đầu và cuối hợp lệ trên video raw")
            return
        if self.condition_status.currentData() == "unreadable" and not any(
                check.isChecked() for check in self.condition_checks.values()):
            QMessageBox.warning(self, "Ground truth", "Biển không đọc được cần chọn ít nhất một trong ba nguyên nhân")
            return
        self.gt_events.append(self._collect_gt_record())
        self._reset_gt_form()
        self._fill_gt()

    def _update_gt(self):
        if self.gt_edit_index is None or self.gt_edit_index >= len(self.gt_events):
            QMessageBox.warning(self, "Ground truth", "Chưa chọn GT để cập nhật")
            return
        if not self.source_info or self.gt_start is None or self.gt_end is None or self.gt_end <= self.gt_start:
            QMessageBox.warning(self, "Ground truth", "Cần đánh dấu đầu và cuối hợp lệ trên video raw")
            return
        if self.condition_status.currentData() == "unreadable" and not any(
                check.isChecked() for check in self.condition_checks.values()):
            QMessageBox.warning(self, "Ground truth", "Biển không đọc được cần chọn ít nhất một trong ba nguyên nhân")
            return
        gt_event_id = self.gt_events[self.gt_edit_index]["gt_event_id"]
        self.gt_events[self.gt_edit_index] = self._collect_gt_record(gt_event_id)
        self._reset_gt_form()
        self._fill_gt()

    def _reset_gt_form(self) -> None:
        self.gt_start = self.gt_end = None
        self.gt_readable.clear()
        self.gt_text.clear()
        self._set_conditions([], "good")
        self.condition_evidence.setText("Chưa có gợi ý điều kiện")
        self.gt_type.setCurrentText("car")
        self.gt_readability.setCurrentIndex(self.gt_readability.findData("unknown"))
        self._set_gt_crossed(False)
        self.gt_edit_index = None
        self.annotation_event_id = None
        self.gt_suggestions = {}
        self.gt_table.clearSelection()
        self._set_gt_edit_controls(False)
        self._update_gt_status()

    def _format_gt_value(self, event: dict, key: str) -> str:
        """Return a readable value for every GT column.

        The table is also used to audit annotation provenance.  Missing values
        therefore stay visible as the literal ``None`` instead of becoming an
        empty cell that could be mistaken for an omitted column or an
        annotation that was not loaded.
        """
        value = event.get(key)
        if key == "crossed":
            # crossed is an explicit HITL boolean.  Legacy GT records without
            # this field are normalized to False when displayed/edited.
            return str(self._coerce_bool(value, False))
        if value is None:
            return "None"
        if isinstance(value, str) and not value:
            return "None"
        if isinstance(value, (list, tuple, set, dict)) and not value:
            return "None"
        if key == "plate_readability":
            return self.READABILITY_LABELS.get(str(value), str(value))
        if isinstance(value, (list, tuple, set)):
            values = [self._format_gt_scalar(item) for item in value]
            return ", ".join(values) if values else "None"
        if isinstance(value, dict):
            # Keep nested suggestion/provenance data in one cell while making
            # it easy to inspect with the tooltip or copy from the table.
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return self._format_gt_scalar(value)

    @staticmethod
    def _coerce_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "crossed"}:
                return True
            if normalized in {"false", "0", "no", "n", "not_crossed"}:
                return False
        return default

    @staticmethod
    def _format_gt_scalar(value) -> str:
        if value is None or value == "":
            return "None"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _fill_gt(self):
        self.gt_table.setRowCount(len(self.gt_events))
        for row, event in enumerate(self.gt_events):
            for col, (key, _label) in enumerate(self.GT_TABLE_COLUMNS):
                value = self._format_gt_value(event, key)
                item = QTableWidgetItem(value)
                raw_value = event.get(key)
                item.setToolTip(value if raw_value is None else str(raw_value))
                self.gt_table.setItem(row, col, item)
        self.gt_table.resizeColumnsToContents()
        # Keep long provenance fields usable without making the whole window
        # wider than the screen.  The table's horizontal scrollbar exposes
        # the remaining columns.
        for key, width in (("suggestions", 280), ("source_uri", 260)):
            column = next((index for index, (name, _label) in enumerate(self.GT_TABLE_COLUMNS)
                           if name == key), None)
            if column is not None:
                self.gt_table.setColumnWidth(column, width)

    def _select_gt_for_edit(self, row, _column):
        if 0 <= row < len(self.gt_events):
            self._load_gt_record(self.gt_events[row], row)

    def _delete_gt(self):
        row = self.gt_table.currentRow()
        if row >= 0:
            self.gt_events.pop(row)
            self._reset_gt_form()
            self._fill_gt()

    def _save_gt(self):
        if not self.gt_events:
            QMessageBox.warning(self, "Ground truth", "Chưa có event GT")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu ground truth", "ground_truth_events.jsonl", "JSONL (*.jsonl)")
        if path:
            save_jsonl(path, self.gt_events)

    def _load_gt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở ground truth", "", "JSONL (*.jsonl)")
        if path:
            try:
                self.gt_events = load_jsonl(path)
                self._reset_gt_form()
                self._fill_gt()
            except Exception as exc:
                QMessageBox.warning(self, "Ground truth", str(exc))

    def _evaluate(self):
        if not self.run_result or not self.gt_events:
            QMessageBox.warning(self, "Đánh giá", "Cần mở run và ground truth")
            return
        source = self.run_result["run"]["config"]["source"]
        gt = [event for event in self.gt_events if event.get("source_uri") == source]
        if not gt:
            QMessageBox.warning(self, "Đánh giá", "GT không khớp đường dẫn video nguồn của run")
            return
        result = evaluate_step1(gt, self.run_result["events"], self.run_result["clips"],
                                self.run_result["run"]["source"]["duration_ms"])
        path = Path(self.run_result["run_dir"]) / "step1_evaluation.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        def percent(value):
            return "N/A" if value is None else f"{value * 100:.1f}%"
        self.metrics.setText(
            f"GT {result['gt_count']} | Event recall {percent(result['event_recall'])} | "
            f"Readable@1 {percent(result['readable_retention_at_1'])} | "
            f"Video reduction {percent(result['video_reduction'])} | "
            f"False clips/hour {result['false_clips_per_hour'] or 0:.2f}\nLưu tại {path}"
        )

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_requested = True
            self.worker.wait(3000)
            if self.worker.isRunning():
                event.ignore()
                return
        if self.source_capture:
            self.source_capture.release()
        self._close_clip()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
