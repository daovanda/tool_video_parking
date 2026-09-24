# Tool video bãi xe — Bước 1

Bản pilot hiện xử lý **một camera/một làn trong mỗi lần chạy**, với ba lớp
`car`, `motorcycle` và `bicycle`. `lane_id` và `direction` (`ENTRY` hoặc `EXIT`) được
nhập từ camera registry; Bước 1 không ghép lượt vào với lượt ra.

## Lấy mã nguồn và chuẩn bị dữ liệu

```powershell
git clone https://github.com/daovanda/tool_video_parking.git
cd tool_video_parking
python -m pip install -r requirements.txt
```

Repository chỉ chứa **mã nguồn, frontend, test, cấu hình mẫu và tài liệu**.
Video raw, output của các run, database local, weights/model và file debug
không được đưa lên GitHub. Sau khi clone:

- Đặt video của bạn ở đường dẫn riêng hoặc tải lên qua trang **Kho video**.
  Nếu chạy ví dụ CLI bên dưới, thay `video_test1.mp4` bằng đường dẫn video thật.
- Tải weights mặc định vào root (cần mạng ở lần đầu):

  ```powershell
  python -c "from ultralytics import YOLO; YOLO('yolo26s.pt'); YOLO('yolov8n-oiv7.pt')"
  ```

  Có thể truyền đường dẫn weights khác qua `--model`/giao diện. Nếu không
  dùng gợi ý biển số thì không cần tải `yolov8n-oiv7.pt`.
- Nếu bật gợi ý biển số, cài `requirements-plate.txt` và chuẩn bị weights
  `yolov8n-oiv7.pt` như lệnh trên hoặc đổi sang model biển số tương thích.
- Nếu bật điều kiện CV–VLM, cài `requirements-conditions.txt` và tải
  Qwen3-VL-2B-Instruct theo hướng dẫn ở mục dưới.

Các thư mục `outputs/`, `web_data/`, `models/`, `.cache/` và
`frontend/node_modules/` được tạo hoặc tải trên từng máy; chúng không phải
thành phần của source repository. `camera_batch.example.json` là cấu hình
mẫu: đổi `source` sang video của bạn trước khi chạy.

## Chạy web local (khuyến nghị)

Web local gồm backend FastAPI và frontend React tách thư mục. Cài và build:

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python run_web_api.py
```

Mở `http://127.0.0.1:8000`. FastAPI phục vụ bản build frontend và REST API
trên cùng port. Giao diện có **Tổng quan**, **Kho video**, **Chạy phân tích**,
**Kết quả & duyệt**, **Đánh giá**, **Tài liệu** và **Cài đặt**. Dữ liệu local
nằm trong `web_data/` và bị gitignore.

Khi phát triển frontend riêng:

```powershell
python run_web_api.py
cd frontend
npm run dev
```

Mở `http://127.0.0.1:5173`; Vite proxy `/api` sang backend port 8000. Chi
tiết API, worker và storage xem
[`docs/kien_truc_web_local.md`](docs/kien_truc_web_local.md).

## Cài đặt

```powershell
python -m pip install -r requirements.txt
```

Đặt file weights `yolo26s.pt` ở root repository hoặc truyền đường dẫn bằng
`--model`. Ultralytics sẽ dùng GPU nếu môi trường có CUDA; CPU vẫn chạy được
nhưng chậm hơn.

## Chạy giao diện local

```powershell
python run_gui.py
```

Trong giao diện, chọn video raw, thư mục output, camera/làn/chiều, vẽ ROI và
crossing line trên frame bên phải, sau đó chạy Bước 1. Tab **Kết quả & GT** cho
phép bấm event để phát clip ngay trong cửa sổ và tua tới đúng thời điểm bắt
đầu event. Frame đầu event và các frame tiếp theo được vẽ box, lớp,
confidence, track ID của YOLO + ByteTrack từ `detections.jsonl`; bạn cũng có
thể đánh dấu ground truth độc lập trên raw và tính metric pilot. Bảng event và
GT chọn theo toàn hàng khi bấm vào một dòng. Bảng GT hiển thị đầy đủ các trường
annotation/provenance; trường chưa có hiển thị `None` và các trường dài có thể
cuộn ngang. Trường `crossed` trong GT chỉ nhận `True`/`False` và được điền sẵn
theo event Model 1 để người dùng kiểm tra/chỉnh sửa.

## Chạy batch bằng CLI

```powershell
python run_step1.py `
  --source video_test1.mp4 --output outputs\cam01 `
  --camera-id CAM01 --lane-id ENTRY_01 --direction ENTRY `
  --model yolo26s.pt --imgsz 960 --sample-fps 10
```

ROI và đường crossing dùng tọa độ chuẩn hóa trong `[0,1]`:
`--roi "0.1,0.2;0.9,0.2;0.9,0.9;0.1,0.9"` và
`--crossing-line "0.5,0.2;0.5,0.9"`. Dùng `--no-clips` để chỉ tạo virtual
segment và manifest, không re-encode MP4. Nếu chỉ vẽ crossing line mà bỏ
trống ROI, `line_gate_margin` (mặc định `0.12`) tự lọc detection vào corridor
quanh line để loại xe nền; có thể chỉnh bằng `--line-gate-margin`.

Event chỉ chuyển từ candidate sang active khi cùng track vừa đủ số lần thấy,
vừa dịch chuyển đủ xa trong cửa sổ xác nhận. Mặc định
`min_motion_distance=0.015` và `motion_window_seconds=1.5`; chỉnh bằng
`--min-motion-distance`/`--motion-window-seconds` hoặc hai trường tương ứng
trong GUI. Khoảng cách là
`sqrt((dx/frame_width)^2 + (dy/frame_height)^2)` của điểm giữa đáy box. Xe
đỗ ổn định bị loại; xe đã active vẫn được phép dừng trong grace period.

Nếu vẽ đồng thời ROI và crossing line, line bắt buộc phải nằm trong, cắt qua
hoặc chạm biên ROI. Line hoàn toàn ngoài ROI bị chặn khi validate cấu hình,
kể cả khi corridor do `line_gate_margin` tạo ra vẫn chạm ROI. Trong GUI,
line sai được cảnh báo và xóa ngay sau khi đặt điểm thứ hai.

Mỗi run tạo `run.json`, `events.jsonl`, `clips.jsonl`, `detections.jsonl` và
thư mục `clips/` (nếu bật materialize). Ngoài từng `CLIP-*.mp4`, pipeline tạo
`clips/clip_final.mp4` bằng cách nối các segment theo `start_ms` tăng dần và
lưu ánh xạ timeline trong `run.json.artifacts.final_clip`. Raw video không bị
sửa. `--no-clips` tắt cả từng MP4 lẫn clip final.

Để chạy nhiều camera/làn tuần tự, dùng file mẫu
[`camera_batch.example.json`](camera_batch.example.json) hoặc tạo JSON dạng
`{"runs": [{"camera": {...}, "source": "...", "output_dir": "..."}, ...]}`
hoặc lưu từ Python bằng `BatchConfig`, rồi chạy:

```powershell
python run_step1.py --batch-config camera_batch.json
```

Mỗi run vẫn có manifest riêng; tracker không dùng chung trạng thái giữa các
camera.

## Kiểm thử logic

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Chi tiết giới hạn và trạng thái triển khai nằm trong
[`docs/trang_thai_trien_khai.md`](docs/trang_thai_trien_khai.md).
# Plate Enrichment (tùy chọn)

Cài thêm `python -m pip install -r requirements-plate.txt`, rồi bật checkbox
**Gợi ý biển số bằng YOLO + PaddleOCR** trong GUI hoặc chạy
`python run_step1.py --source VIDEO --output OUTPUT --plate-ocr`.
Với run đã tạo: `python run_plate.py PATH_TO_RUN`. Mặc định detector biển số
dùng `yolov8n-oiv7.pt` (class `Vehicle registration plate`) và OCR dùng
`latin_PP-OCRv5_mobile_rec`. Có thể thay weights/model qua cấu hình hoặc CLI.
Kết quả nằm ở `plate_observations.jsonl` và chỉ là gợi ý để người kiểm duyệt
xác nhận trong GT.

Xe đạp vẫn được YOLO + ByteTrack tạo event/clip với
`vehicle_type="bicycle"`. Vì xe đạp không thuộc nghiệp vụ biển số, Plate OCR
và Condition Enrichment không chạy cho event đó; artifact ghi
`plate_applicability/condition_status="not_applicable"` để giữ khả năng truy vết.

# Gợi ý điều kiện bằng CV + VLM (tùy chọn)

Cài `python -m pip install -r requirements-conditions.txt` và tải weights
Qwen3-VL-2B-Instruct vào `models/Qwen3-VL-2B-Instruct` bằng
`hf download Qwen/Qwen3-VL-2B-Instruct --local-dir models/Qwen3-VL-2B-Instruct`.
Bật checkbox **Gợi ý điều kiện bằng CV + Qwen3-VL** khi chạy Bước 1, hoặc
chạy `python run_conditions.py PATH_TO_RUN` cho run cũ; trong GUI cũng có nút
**Phân tích điều kiện cho run này**. CLI chạy mới dùng `--conditions` và
`--vlm-model` nếu weights ở nơi khác. Trên CPU, suy luận VLM có thể chậm.

Artifact `condition_suggestions.jsonl` lưu bằng chứng CV và nhãn VLM riêng
cho từng event. Khi chọn event, form GT tự điền trạng thái `good` nếu biển
có khả năng đọc được. Chỉ khi biển không đọc được, form mới gợi ý một hoặc
nhiều nguyên nhân `capture_blur`, `plate_obstruction`, `lighting_issue`;
người gán kiểm tra, sửa và lưu GT. Ground truth không bị nhánh
CV + VLM ghi tự động.
