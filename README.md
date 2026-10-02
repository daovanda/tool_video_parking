# Tool video bãi xe — Bước 1

Bản pilot hiện xử lý **một camera/một làn trong mỗi lần chạy**, với ba lớp
`car`, `motorcycle` và `bicycle`. `lane_id` và `direction` (`ENTRY` hoặc `EXIT`) được
nhập từ camera registry; Bước 1 không ghép lượt vào với lượt ra.

[Slide HTML trình bày kiến trúc và thuật toán](docs/slides_kien_truc.html)
có thể mở trực tiếp trong trình duyệt và dùng phím trái/phải để chuyển slide.

## Chuẩn bị máy mới (Windows PowerShell)

Cần **Python 3.12**, **Node.js 22**, Git, kết nối mạng khi cài thư viện và tải
model. Cấu hình này đã dùng để kiểm thử trên Windows; CPU chạy được nhưng các
nhánh OCR/VLM có thể mất nhiều phút. Nếu repository private, đồng nghiệp cần
được cấp quyền truy cập GitHub trước khi clone. Không commit hoặc gửi kèm
video, dữ liệu review, weights và token; mỗi máy chuẩn bị các file đó riêng.

```powershell
git clone https://github.com/daovanda/tool_video_parking.git
cd tool_video_parking
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

Nếu PowerShell chặn `Activate.ps1`, có thể gọi trực tiếp
`.\.venv\Scripts\python.exe` thay cho `python` trong các lệnh bên dưới.
`requirements.txt` gồm YOLO/ByteTrack, OpenCV, FFmpeg CPU, FastAPI, PyQt và
thư viện xuất Excel. Frontend dùng `frontend/package-lock.json` qua `npm ci`.

Để thử **toàn bộ** các nhánh gợi ý, sau khi cài requirements cơ bản chạy:

```powershell
python -m pip install -r requirements-plate.txt -r requirements-conditions.txt
```

`requirements-plate.txt` cài PaddlePaddle/PaddleOCR và ràng buộc NumPy phù
hợp; `requirements-conditions.txt` cài PyTorch/Transformers/Hugging Face.
Hai nhánh này là tùy chọn: không cài thì phải tắt gợi ý biển số và CV–VLM
trong cấu hình run. Model OCR Latin được Paddle tải/cache ở lần dùng đầu.

## Model và video trên máy mới

Repository chứa mã nguồn, frontend, test, cấu hình mẫu, tài liệu và **một
video mẫu** [`video_test1.mp4`](video_test1.mp4) (17,39 giây; khoảng 48 MB)
để thử Bước 1 ngay sau khi clone. Video raw khác, output của các run,
database local, weights/model và file debug không được đưa lên GitHub. Sau
khi clone:

- Dùng `video_test1.mp4` cho lệnh CLI ví dụ bên dưới, hoặc tải file này lên
  trang **Kho video** để thử web. Với camera khác, đặt video ở đường dẫn riêng
  hoặc tải lên Kho video rồi thay `--source`/chọn lại video tương ứng.
- Tải weights mặc định vào root (cần mạng ở lần đầu):

  ```powershell
  python -c "from ultralytics import YOLO; YOLO('yolo26s.pt'); YOLO('yolov8n-oiv7.pt')"
  ```

  Có thể truyền đường dẫn weights khác qua `--model`/giao diện. Nếu không
  dùng gợi ý biển số thì không cần tải `yolov8n-oiv7.pt`.
- Nếu bật điều kiện CV–VLM, tải Qwen3-VL-2B-Instruct vào đúng vị trí mặc định:

  ```powershell
  hf download Qwen/Qwen3-VL-2B-Instruct --local-dir models/Qwen3-VL-2B-Instruct
  ```

  Lệnh `hf` có sau khi cài `requirements-conditions.txt`. Model lớn; cần đủ
  dung lượng lưu trữ và RAM. Có thể đổi đường dẫn qua cấu hình run.

Các thư mục `outputs/`, `web_data/`, `models/`, `.cache/` và
`frontend/node_modules/` được tạo hoặc tải trên từng máy; chúng không phải
thành phần của source repository. `camera_batch.example.json` là cấu hình
mẫu: đổi `source` sang video của bạn trước khi chạy.

## Chạy web local (khuyến nghị)

**Cách 1 — hai terminal, phù hợp chạy thử và sửa giao diện.** Mở hai cửa sổ
PowerShell tại **thư mục cha** chứa thư mục đã clone, bật `.venv` ở cửa sổ
backend:

```powershell
# Terminal 1: backend
cd tool_video_parking
.\.venv\Scripts\Activate.ps1
python run_web_api.py
```

```powershell
# Terminal 2: frontend
cd tool_video_parking\frontend
npm run dev
```

Mở `http://127.0.0.1:5173/`. FE proxy `/api` tới BE ở
`http://127.0.0.1:8000/`. Hai lệnh cần chạy đồng thời; nhấn `Ctrl+C` ở từng
terminal để dừng. Nếu đã đứng trong thư mục dự án thì bỏ dòng `cd` tương ứng.

**Cách 2 — một terminal, backend phục vụ bản FE đã build:**

Chạy từ thư mục cha chứa repository:

```powershell
cd tool_video_parking
.\.venv\Scripts\Activate.ps1
cd frontend
npm run build
cd ..
python run_web_api.py
```

Mở `http://127.0.0.1:8000`. FastAPI phục vụ bản build frontend và REST API
trên cùng port. Giao diện có **Tổng quan**, **Kho video**, **Chạy phân tích**,
**Kết quả & duyệt**, **Đánh giá**, **Tài liệu** và **Cài đặt**. Dữ liệu local
nằm trong `web_data/` và bị gitignore.

Chi tiết API, worker và storage xem
[`docs/kien_truc_web_local.md`](docs/kien_truc_web_local.md).

Sau khi mở web: vào **Kho video** để tải video raw, vào **Chạy phân tích** để
chọn video, camera/làn/chiều (`ENTRY` hoặc `EXIT`), vẽ ROI/line nếu cần và
chạy. Có thể tắt OCR/CV–VLM khi chưa cài model tùy chọn. Xem event ở **Kết quả
& duyệt**, chỉnh GT và duyệt trước khi xem metric ở **Đánh giá**. Run, GT và
video đã tải nằm trong `web_data/`; output lớn nằm ngoài Git.

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
