# Định dạng đầu ra chuẩn sau bước 1

## Thời gian xử lý run (artifact `runtime.json` schema `0.3.0`)

Run mới ghi `runtime.json` sau khi hoàn tất Bước 1 và các nhánh OCR/CV–VLM
được bật. File có `schema_version: "0.3.0"`, `scope: "full_pipeline"` và
`elapsed_seconds` là số giây đồng hồ thực đo từ trước khởi tạo model đến sau
enrichment. `core_elapsed_seconds` đo từ trước khởi tạo model đến khi ghi xong
event/clip/manifest; `ocr_elapsed_seconds` và `condition_elapsed_seconds` đo
riêng từng nhánh, bằng `null` khi nhánh tắt. Tổng có thể nhỉnh hơn tổng ba
chặng vì có thời gian điều phối và ghi file giữa chúng. Không gồm chờ trong
queue, thời gian chỉnh sửa/duyệt GT.
Run mới ghi thêm `core_profile_seconds` (nạp detector, giải mã frame,
YOLO+ByteTrack, cập nhật event, hash raw, xuất clip thành phần, xuất clip
final), `ocr_profile_seconds` (nạp model, seek/giải mã frame, phát hiện biển,
OCR) và `condition_profile_seconds` (nạp VLM, seek/giải mã frame, CV/contact
sheet, tiền xử lý+suy luận VLM). Đây là thời gian từng phần *trong* chặng,
không cộng vào tổng lần nữa; phần thời gian chưa phân loại gồm khởi tạo,
đọc/ghi manifest, chọn candidate/fusion và chi phí điều phối. Nhánh tắt có
profile rỗng. Reader cũ chỉ cần các trường tổng vẫn đọc được vì không xóa
trường cũ. Run `0.2.0` không có profile chi tiết.
`run.json.elapsed_seconds` vẫn giữ nghĩa cũ: thời gian lõi phát hiện và xuất
clip, được ghi trước enrichment. Run cũ không có `runtime.json` dùng trường
này với nhãn `step1_core_only`. Schema của `run.json`, event, clip và GT
không đổi.
API `GET /api/runs/{id}/evaluation` trả `runtime` gồm các trường thời gian trên,
`raw_duration_seconds` và `total_to_raw_ratio = elapsed_seconds /
raw_duration_seconds`. Tỷ lệ chỉ tính khi có tổng thời gian toàn pipeline và
video raw dài hơn 0; còn lại là `null`. Run dùng artifact `runtime.json` 0.1.0
vẫn đọc được tổng thời gian; thời gian lõi lấy từ `run.json`, hai nhánh riêng
hiện `null`. Run cũ chỉ có `run.json` chỉ hiện thời gian lõi, không suy tổng.
Khi cả hai artifact đều thiếu, `scope` là `unavailable`.

## Cài đặt web local (API schema `0.1.0`)

`GET/PUT /api/settings` dùng object gồm `schema_version: "0.1.0"`,
`run_defaults` và `evaluation`. `run_defaults` chứa `model`, `image_size`,
`grace_seconds`, `pre_seconds`, `post_seconds`, `merge_gap_seconds`,
`plate_model`, `plate_class_name`, `plate_confidence`, `plate_top_k`,
`plate_min_gap_ms`, `ocr_model`, `condition_vlm_model`, `condition_max_frames`.
`evaluation` chứa `min_temporal_iou` (mặc định 0,30),
`boundary_tolerance_ms` (500) và `coverage_threshold` (0,95). Backend xác
thực giá trị rồi lưu một bản trong `app_settings` của SQLite. Run đã tạo có
snapshot cấu hình trong `runs.config_json`, không đổi khi sửa default. Điểm
evaluation của run đã duyệt dùng **ngưỡng hiện hành tại thời điểm gọi API**,
không phải snapshot ngưỡng tại lúc run được tạo; đổi ngưỡng không viết lại
artifact/GT. Schema artifact Bước 1 và GT không thay đổi.

## Condition Enrichment pilot (artifact schema `0.3.0`, tùy chọn)

Run mới có `schema_version: "0.9.0"`; khi bật phân tích điều kiện,
`run.json.artifacts.condition_suggestions_uri` trỏ tới
`condition_suggestions.jsonl` (một dòng cho mỗi event). Dòng gồm `run_id`,
`event_id`, `source_uri`, `vlm_model`, `evidence_timestamps_ms`,
`cv_metrics` (median_luma, scene_median_luma, scene_dark_fraction,
bright_fraction, laplacian_variance, region và suggested_conditions),
`vlm_result`, `plate_readable`, `condition_status`, `conditions`,
`condition_sources`, `cv_support`, `ocr_readable`, `vlm_readable` và
`suppressed_conditions`.

`condition_status` có `good`, `unreadable` hoặc `not_applicable` cho bicycle. Khi `plate_readable=true`,
status bắt buộc là `good` và `conditions=[]`. Khi status là `unreadable`,
`conditions` chỉ được chứa `capture_blur`, `plate_obstruction` và
`lighting_issue`; không còn detail. OCR cùng một chuỗi ở ít nhất hai frame có
confidence từ `0.85` được xem là đọc được. `confidence` OCR chưa được hiệu
chỉnh, nên đây là quy tắc thận trọng của pilot.

Với `vehicle_type="bicycle"`, nhánh không chạy CV/VLM và ghi
`condition_status="not_applicable"`, `plate_readable=null`, `conditions=[]`,
`skip_reason="bicycle_has_no_required_license_plate"`.

GUI lưu GT mới bằng `annotation_schema_version: "0.6.0"`, gồm boolean/null
`plate_readable`, `condition_status`, `conditions` và
`condition_annotation_source: "human"`.
`suggestions.conditions` giữ trạng thái đọc được và nguồn `cv_vlm`. GT cũ vẫn
đọc được, nhưng tag/detail cũ không tự chuyển đổi và cần người gán rà lại.
Run cũ không có artifact này vẫn mở được; dùng `run_conditions.py` để bổ sung.
Khi bổ sung vào run cũ, riêng `run.json.schema_version` tăng lên `0.9.0`;
`events.jsonl`/`clips.jsonl` cũ giữ version gốc vì không bị viết lại.

Web local ghi GT bằng `annotation_schema_version: "0.9.0"`. Mỗi dòng
`ground_truth.jsonl` gồm `gt_event_id`, `source_event_id`, `event_id`, loại
xe, `crossed`, thời gian, biển số/khả năng đọc, trạng thái điều kiện, ba nhãn
nguyên nhân cố định, `annotation_source: "human"` và `updated_at`. SQLite giữ
bản hiện hành để dựng bảng; file JSONL được ghi lại sau mỗi lần cập nhật theo
lô. Hàng GT thủ công có `event_id=gt_event_id="GT-000001"` (tăng tuần tự trong
run), `source_event_id=null`, `camera_id`, `lane_id`, `direction` lấy từ cấu hình
run và thời gian trên timeline raw. Hàng từ model giữ `source_event_id` bằng ID
event gốc. API `PUT /annotations` thay thế toàn bộ trạng thái duyệt của run;
caller gửi đủ các hàng cần giữ. Event dự đoán bị xóa khỏi bảng GT có
`is_valid_event=false` trong SQLite để ghi nhận người dùng đã kiểm tra, nhưng
không được ghi vào `ground_truth.jsonl` hay trả trong `gt_events`. Các dòng GT
cuối cùng đều có `is_valid_event=true`. Run `REVIEWED` khóa chỉnh sửa tới khi
gọi mở lại.
Record web `0.7.0` cũ vẫn được đọc: backend suy ra camera/làn/chiều từ event
nguồn hoặc cấu hình run khi tính metric. Không thay đổi schema của
`events.jsonl`, `clips.jsonl` hay manifest Step 1.

API `GET /api/runs/{id}/evaluation` trả JSON tính tại thời điểm đọc với
`metrics.evaluation_schema_version="0.2.0"`, gồm `events`, `clip`, `ocr`,
`condition_status`, `conditions`, `review_diagnostics`. OCR/điều kiện có
`available` và `end_to_end` riêng; `null` biểu thị mẫu số rỗng hoặc nhánh
chưa chạy, không phải 0%. Đây là response API, không phải artifact ghi lại
trong run. Schema GT và manifest Step 1 không đổi bởi lần nâng evaluator này.

API `GET /api/runs/{id}/result` hiện trả thêm trong mỗi
`events[].suggestion`: `plate_consensus_confidence`, `plate_support_count`,
`plate_analyzed`, `cv_clean_fraction`, `vlm_readable` và
`condition_analyzed`. Các trường này được tính/đọc từ
`plate_observations.jsonl` và `condition_suggestions.jsonl` để giao diện
tính điểm độ dễ; chúng chỉ mở rộng response web, không ghi vào
`events.jsonl` hay thay `schema_version` artifact. Trường null hoặc cờ
`analyzed=false` chỉ nhánh chưa có bằng chứng.

API `POST /api/runs/{id}/export.xlsx` nhận mảng hàng cùng cấu trúc
`AnnotationPayload` của form GT và trả XLSX với content type
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
File gồm các cột Event, Bắt đầu ms, Kết thúc ms, Loại, Crossed, Biển số,
Đọc biển, Trạng thái, Điều kiện, Clip, Video và Frame đại diện có ảnh nhúng.
Ba cột hỗ trợ duyệt trên UI `Detector TB`, `Độ dễ (0–1)`, `Ưu tiên / lý do`
không được xuất. Export không ghi vào schema artifact hay GT đã lưu.

## Plate Enrichment pilot (schema `0.2.0`, tùy chọn)

Khi bật OCR, `run.json.artifacts.plate_observations_uri` trỏ tới
`plate_observations.jsonl`; mỗi dòng ứng với một event và gồm `run_id`,
`event_id`, `clip_id`, `camera_id`, `lane_id`, `direction`, `source_uri`,
`plate_model`, `ocr_model`, `candidate_count`, `observations`,
`selected_observations`, `consensus`. Observation ghi `frame_index`,
`timestamp_ms` theo raw, `vehicle_box` và `plate_box` theo pixel raw,
`plate_confidence`, `quality` (score và thành phần). Observation được chọn
có thêm `ocr_text_raw`, `ocr_text_normalized`, `ocr_confidence`. `consensus`
là `null` hoặc object `{text, confidence, support_count, timestamps_ms}`;
`confidence` ở đây là tỷ phần trọng số phiếu, không phải xác suất đã hiệu
chỉnh. File này bổ sung gợi ý, không sửa event/GT. Run 0.3.0 trước đây có
thể được GUI đọc nhưng không có artifact biển số; chạy `run_plate.py` để
bổ sung artifact nếu raw và detections vẫn còn. GT annotation giữ schema
riêng `0.3.0` ở phiên bản cũ; form hiện tại ghi `0.6.0`.

Event `bicycle` không chạy detector biển hoặc OCR. Artifact vẫn có record với
`plate_applicability="not_applicable"`,
`plate_presence="absent_by_vehicle_type"`, danh sách observation rỗng và
`consensus=null`. Nhờ vậy downstream phân biệt được “không áp dụng” với
“đã chạy nhưng không tìm thấy/không đọc được biển”.

> **Trạng thái schema:** Các mục 1–7 và ví dụ ở mục 8–9 là schema mục tiêu
> đầy đủ cho dataset production. Writer pilot hiện tại tạo subset tối thiểu
> được mô tả ở mục 10, dùng `start_ms/end_ms` trên timeline raw và
> `schema_version: "0.9.0"`; không được hiểu các trường mục tiêu là đã có
> trong file nếu chưa xuất hiện ở mục 10.

## 1. Kết luận thiết kế

Đầu ra bước 1 không nên chỉ là các file MP4. Mỗi lần chạy phải tạo một **gói dữ liệu có phiên bản**, gồm:

```text
step1_output/{dataset_version}/
├── media/
│   ├── clips/                  # video đã giữ
│   └── representative_frames/  # ảnh đại diện do thuật toán chọn, nếu cần
├── manifests/
│   ├── clips.jsonl             # một dòng cho một clip vật lý
│   └── events.jsonl            # một dòng cho một lượt xe dự đoán
├── annotations/
│   └── ground_truth_events.jsonl  # nhãn độc lập từ video raw
├── configs/                    # ROI, lane, threshold, phiên bản cấu hình
├── checksums.sha256            # kiểm tra file bị đổi/hỏng
└── run.json                    # thông tin toàn bộ lần chạy
```

JSONL được khuyến nghị vì có thể đọc từng dòng, nối thêm kết quả và xử lý tập dữ liệu lớn. CSV có thể xuất thêm để người dùng xem nhưng không nên là định dạng chuẩn duy nhất vì một clip có thể chứa nhiều event, nhiều source fragment và nhiều điều kiện.

## 2. Phân biệt clip, event và ground truth

| Đối tượng | Ý nghĩa | Quan hệ |
|---|---|---|
| `clip` | Một khoảng video vật lý được bước 1 giữ lại | Một clip có thể chứa một hoặc nhiều event |
| `event` | Một lần một xe đi qua một làn | Một event thuộc một clip chính; có thể có clip tập trung riêng cho event |
| `ground_truth_event` | Lượt xe đúng do người kiểm duyệt trên raw video | Có thể chưa ghép được với event dự đoán nếu model1 bỏ sót |

Không dùng `track_id` làm khóa lâu dài. Tracker có thể sinh lại ID khác ở lần chạy khác. `event_id` là ID ổn định trong một lần chạy; `gt_event_id` là ID của nhãn chuẩn.

## 3. Thông tin bắt buộc trong mỗi clip

### 3.1 Định danh

- `schema_version`: phiên bản cấu trúc dữ liệu.
- `dataset_version`: phiên bản bộ dữ liệu.
- `run_id`: lần chạy pipeline đã tạo clip.
- `clip_id`: duy nhất trong dataset.
- `clip_uri`: đường dẫn tương đối đến file video.
- `clip_sha256`: checksum sau khi ghi xong.

### 3.2 Camera, bãi và làn

- `site_id`: mã bãi xe.
- `camera_id`: camera tạo video.
- `lane_id`: làn được quan sát.
- `direction`: `ENTRY` hoặc `EXIT`.
- `timezone`: ví dụ `Asia/Ho_Chi_Minh`.
- `camera_config_version`: phiên bản ROI/đường crossing dùng khi chạy.

Mỗi bản ghi clip chỉ gắn với một `lane_id`. Trong phạm vi hiện tại, `camera_id`, `lane_id` và `direction` có ánh xạ một-một từ camera registry; pipeline sao chép các giá trị này vào manifest và không suy luận lại từ hình ảnh.

### 3.3 Thời gian và truy vết về video nguồn

- `capture_start_utc`, `capture_end_utc`: thời gian tuyệt đối dạng ISO 8601 UTC.
- `local_start_time`, `local_end_time`: thời gian địa phương có UTC offset, giúp người vận hành tra cứu.
- `source_fragments`: danh sách file raw tham gia tạo clip. Mỗi phần có:
  - `source_video_id`, `source_uri`, `source_sha256`;
  - `source_start_ms`, `source_end_ms`;
  - `clip_start_ms`, `clip_end_ms`.

Danh sách nguồn cho phép một clip đi qua ranh giới hai file raw. Millisecond được đo trên timeline nguồn/clip tương ứng, tránh dùng riêng `frame_index` vì video có thể có FPS biến đổi hoặc frame bị mất.

### 3.4 Thuộc tính media

- `duration_ms`, `frame_count`.
- `width`, `height`, `pixel_format`.
- `fps_mode`: `constant` hoặc `variable`.
- `nominal_fps` và `average_fps` nếu có.
- `video_codec`, `container`, `bitrate_bps`.
- `has_audio`.
- `rotation_deg` nếu camera/video có metadata xoay.
- `generation_mode`: `stream_copy`, `reencoded` hoặc `virtual_segment`.

`virtual_segment` có thể dùng khi chỉ lưu khoảng thời gian trỏ vào raw thay vì sinh MP4 mới. Nếu Model 2 cần file thật, materialize clip trước khi gọi model.

### 3.5 Thông tin cắt

- `event_ids`: các lượt xe dự đoán nằm trong clip.
- `trigger`: nguyên nhân mở clip, ví dụ `vehicle_track_active`.
- `pre_buffer_ms`, `post_buffer_ms`.
- `merge_reason`: `overlap`, `short_gap`, `none`.
- `is_continuation`, `previous_clip_id`, `next_clip_id` khi một event dài phải chia file.

### 3.6 Kiểm tra chất lượng file

- `status`: `valid`, `warning` hoặc `invalid`.
- `decodable`: giải mã được hay không.
- `timestamp_continuous`: timeline có liên tục hay không.
- `missing_frame_estimate`.
- `truncated_at_source_start`, `truncated_at_source_end`.
- `quality_warnings`: danh sách mã lỗi chuẩn.

Clip `invalid` không được im lặng đưa vào Model 2; cần ghi lỗi và tính vào tỷ lệ lỗi pipeline nếu thuộc phạm vi đánh giá.

## 4. Thông tin của mỗi lượt xe dự đoán

Mỗi dòng `events.jsonl` cần có:

- `event_id`, `clip_id`, `run_id`.
- `site_id`, `camera_id`, `lane_id`, `direction`.
- `track_id`: ID nội bộ của tracker trong camera/run.
- `vehicle_type`: nhận `bicycle`, `motorcycle` hoặc `car` trong phạm vi hiện tại.
- `vehicle_type_confidence` nếu detector cung cấp.
- `event_start_ms`, `event_end_ms`: tương đối trong clip.
- `capture_start_utc`, `capture_end_utc`: thời gian tuyệt đối của event.
- `source_refs`: một hoặc nhiều đoạn trên video nguồn, mỗi đoạn có `source_video_id`, `source_start_ms`, `source_end_ms` và phần tương ứng trong event. Trường này xử lý đúng event đi qua ranh giới file.
- `crossing_time_utc`: thời điểm qua đường/vùng xác nhận, nếu xác định được.
- `event_state`: `complete`, `truncated`, `uncertain`.
- `detection_summary`: confidence min/mean/max, số frame detect và số frame tracker duy trì.
- `representative_frames`: các frame được thuật toán chọn, mỗi frame có `frame_id`, `clip_timestamp_ms`, `source_timestamp_ms`, `image_uri`, tiêu chí chọn và quality score nếu có.
- `track_artifact_uri`: đường dẫn kết quả box/track theo frame nếu cần chẩn đoán; không bắt buộc nhúng toàn bộ box vào manifest chính.

`representative_frames` là gợi ý của bước 1 và không phải frame ground truth “đẹp nhất”. Tiêu chí chọn phải chỉ dùng thông tin có ở thời điểm chạy, không được xem text đúng.

## 5. Thông tin điều kiện tại thời điểm xe đi qua

`conditions` chỉ mô tả nguyên nhân trực tiếp khiến biển của **từng event**
không đọc được. Không gắn chung theo clip. Cấu trúc hiện hành:

```json
"condition_status": "unreadable",
"conditions": ["lighting_issue", "capture_blur"]
```

Quy ước:

| Trường | Giá trị |
|---|---|
| `condition_status` | `good`, `unreadable`, `not_applicable` (bicycle) |
| `conditions` | `capture_blur`, `plate_obstruction`, `lighting_issue` |

Phân biệt nguồn nhãn:

- `annotation_source: human`: người gán nhãn xác nhận.
- `annotation_source: sensor`: lấy từ cảm biến tin cậy, ví dụ mưa hoặc độ sáng.
- `annotation_source: auto`: thuật toán suy đoán; phải có model/version/confidence.

`good` nghĩa là biển có khả năng đọc được và bắt buộc `conditions=[]`.
`unreadable` nghĩa là không đọc được và cần ít nhất một nguyên nhân. Không
suy ra nguyên nhân chỉ vì OCR/Model 2 đọc sai; người gán phải thấy bằng chứng.

## 6. Ground truth phải lưu riêng

File `ground_truth_events.jsonl` được tạo từ video raw liên tục và phải chứa cả event Model 1 bỏ sót. Một bản ghi nên có:

- `gt_event_id`, `annotation_version`.
- `site_id`, `camera_id`, `lane_id`, `direction`.
- thời gian bắt đầu/kết thúc và crossing time trên raw.
- `vehicle_type`.
- `plate_presence`: `present`, `absent`, `uncertain`, `out_of_view`; bicycle
  dùng `absent_by_vehicle_type` trong artifact enrichment.
- `plate_readability`: `single_frame_readable`, `multi_frame_readable`,
  `partially_readable`, `unreadable`, `out_of_view`, `not_applicable`.
- `plate_text_raw` và `plate_text_normalized` nếu xác minh được.
- `plate_layout`: `one_row`, `two_rows`, `unknown`.
- `readable_intervals` hoặc `readable_frames` trên timeline raw.
- `conditions` theo cấu trúc ở mục 5.
- `evidence`: frame/đoạn video làm bằng chứng.
- `annotation`: người gán, người kiểm duyệt, thời gian gán, trạng thái và ghi chú bất đồng.
- `parking_session_id` tùy chọn nếu đã xác minh lượt vào và lượt ra thuộc cùng phiên; không đưa trường này cho Model 2 trong lúc đánh giá nhận diện.

Không yêu cầu mọi event bước 1 phải có text biển số. Xe không biển, biển ngoài góc nhìn hoặc không thể đọc vẫn phải là event để đánh giá cutter.

## 7. Thông tin không thuộc đầu ra bước 1

Các trường sau chỉ xuất hiện sau khi chạy Model 2 hoặc evaluator:

- biển số dự đoán, confidence OCR;
- ký tự sai/thiếu/thừa và CER;
- kết quả đúng/sai so với ground truth;
- nguyên nhân lỗi được quy cho Model 2;
- kết quả ghép lượt vào–ra bằng biển số;
- metric tổng hợp.

Việc tách này ngăn rò rỉ ground truth vào Model 2 và cho phép chạy lại nhiều phiên bản model trên cùng đầu ra bước 1.

## 8. Ví dụ `clips.jsonl`

```json
{
  "schema_version": "1.0.0",
  "dataset_version": "parking-pilot-2026-09-v1",
  "run_id": "step1-run-20260916-001",
  "clip_id": "SITE01-CAM03-20260916T010014Z-000123",
  "clip_uri": "media/clips/SITE01-CAM03-20260916T010014Z-000123.mp4",
  "clip_sha256": "<sha256>",
  "site_id": "SITE01",
  "camera_id": "CAM03",
  "lane_id": "ENTRY_02",
  "direction": "ENTRY",
  "timezone": "Asia/Ho_Chi_Minh",
  "camera_config_version": "CAM03-v2",
  "capture_start_utc": "2026-09-16T01:00:14.000Z",
  "capture_end_utc": "2026-09-16T01:00:23.000Z",
  "local_start_time": "2026-09-16T08:00:14.000+07:00",
  "local_end_time": "2026-09-16T08:00:23.000+07:00",
  "source_fragments": [
    {
      "source_video_id": "CAM03-20260916T010000Z",
      "source_uri": "raw/CAM03-20260916T010000Z.mp4",
      "source_sha256": "<sha256>",
      "source_start_ms": 14000,
      "source_end_ms": 23000,
      "clip_start_ms": 0,
      "clip_end_ms": 9000
    }
  ],
  "media": {
    "duration_ms": 9000,
    "frame_count": 225,
    "width": 1920,
    "height": 1080,
    "pixel_format": "yuv420p",
    "fps_mode": "constant",
    "nominal_fps": 25,
    "average_fps": 25.0,
    "video_codec": "h264",
    "container": "mp4",
    "bitrate_bps": 6000000,
    "has_audio": false,
    "rotation_deg": 0,
    "generation_mode": "reencoded"
  },
  "cut": {
    "event_ids": ["EVT-000001", "EVT-000002"],
    "trigger": "vehicle_track_active",
    "pre_buffer_ms": 1500,
    "post_buffer_ms": 2000,
    "merge_reason": "short_gap",
    "is_continuation": false,
    "previous_clip_id": null,
    "next_clip_id": null
  },
  "quality_control": {
    "status": "valid",
    "decodable": true,
    "timestamp_continuous": true,
    "missing_frame_estimate": 0,
    "truncated_at_source_start": false,
    "truncated_at_source_end": false,
    "quality_warnings": []
  }
}
```

## 9. Ví dụ `events.jsonl`

```json
{
  "schema_version": "1.0.0",
  "dataset_version": "parking-pilot-2026-09-v1",
  "run_id": "step1-run-20260916-001",
  "event_id": "EVT-000001",
  "clip_id": "SITE01-CAM03-20260916T010014Z-000123",
  "site_id": "SITE01",
  "camera_id": "CAM03",
  "lane_id": "ENTRY_02",
  "direction": "ENTRY",
  "track_id": "CAM03-27",
  "vehicle_type": "car",
  "vehicle_type_confidence": 0.96,
  "event_start_ms": 1500,
  "event_end_ms": 6800,
  "capture_start_utc": "2026-09-16T01:00:15.500Z",
  "capture_end_utc": "2026-09-16T01:00:20.800Z",
  "source_refs": [
    {
      "source_video_id": "CAM03-20260916T010000Z",
      "source_start_ms": 15500,
      "source_end_ms": 20800,
      "event_start_ms": 0,
      "event_end_ms": 5300
    }
  ],
  "crossing_time_utc": "2026-09-16T01:00:18.120Z",
  "event_state": "complete",
  "detection_summary": {
    "confidence_min": 0.53,
    "confidence_mean": 0.88,
    "confidence_max": 0.97,
    "detected_frame_count": 119,
    "tracked_frame_count": 132
  },
  "representative_frames": [
    {
      "frame_id": "EVT-000001-F01",
      "clip_timestamp_ms": 4100,
      "source_timestamp_ms": 18100,
      "image_uri": "media/representative_frames/EVT-000001-F01.jpg",
      "selection_method": "largest_sharp_vehicle_crop",
      "quality_score": 0.84
    }
  ],
  "track_artifact_uri": "artifacts/tracks/EVT-000001.jsonl"
}
```

## 10. Ví dụ `ground_truth_events.jsonl`

```json
{
  "schema_version": "1.0.0",
  "dataset_version": "parking-pilot-2026-09-v1",
  "annotation_version": "gt-v1.1",
  "gt_event_id": "GT-CAM03-000001",
  "site_id": "SITE01",
  "camera_id": "CAM03",
  "lane_id": "ENTRY_02",
  "direction": "ENTRY",
  "source_video_id": "CAM03-20260916T010000Z",
  "source_start_ms": 15420,
  "source_end_ms": 20920,
  "crossing_time_utc": "2026-09-16T01:00:18.150Z",
  "vehicle_type": "car",
  "plate": {
    "presence": "present",
    "readability": "single_frame_readable",
    "text_raw": "30A-123.45",
    "text_normalized": "30A12345",
    "layout": "one_row",
    "readable_frames": [
      {"source_timestamp_ms": 18020, "evidence_uri": "annotations/evidence/GT-CAM03-000001-F01.jpg"},
      {"source_timestamp_ms": 18100, "evidence_uri": "annotations/evidence/GT-CAM03-000001-F02.jpg"}
    ]
  },
  "condition_status": "unreadable",
  "conditions": ["lighting_issue", "capture_blur"],
  "condition_annotation_source": "human",
  "evidence": {
    "source_clip_start_ms": 14500,
    "source_clip_end_ms": 21500
  },
  "annotation": {
    "annotator_id": "ANN-01",
    "reviewer_id": "REV-02",
    "status": "approved",
    "annotated_at_utc": "2026-09-16T06:00:00Z",
    "notes": null
  },
  "parking_session_id": null
}
```

## 11. Quy tắc giao clip cho Model 2

Nếu Model 2 nhận được nhiều xe và trả mỗi kết quả kèm timestamp/box/track, có thể gửi clip chứa nhiều event. Nếu Model 2 chỉ trả một biển số cho một video, cần sinh thêm **event-focused clip**, mỗi clip tập trung một event với buffer thống nhất.

Event-focused clip phải giữ liên kết:

```json
{
  "event_id": "EVT-000001",
  "parent_clip_id": "SITE01-CAM03-20260916T010014Z-000123",
  "focused_clip_uri": "media/event_clips/EVT-000001.mp4",
  "parent_start_ms": 500,
  "parent_end_ms": 7800
}
```

Không crop chỉ vùng xe hoặc biển ở baseline nếu đầu vào thực tế của Model 2 là toàn frame. Mọi biến đổi đầu vào phải được ghi lại để so sánh công bằng.

## 12. Trường tối thiểu và trường khuyến nghị

### Bắt buộc để chạy Model 2 và truy vết

- File clip đọc được.
- `clip_id`, `event_id`.
- `camera_id`, `lane_id`, `direction`.
- timestamp UTC và offset trong video nguồn.
- source URI/hash và clip hash.
- FPS, độ phân giải, codec, duration.
- event start/end trong clip.
- phiên bản pipeline/config.
- trạng thái kiểm tra chất lượng.

### Bắt buộc để đánh giá tốt

- Ground truth từ raw video liên tục, gồm event bị bỏ sót.
- readable frame/interval.
- trạng thái biển và text nếu xác minh được.
- nhãn điều kiện theo event.
- thông tin người gán/kiểm duyệt và phiên bản nhãn.

### Khuyến nghị để chẩn đoán sâu

- Track artifact và representative frames.
- confidence thống kê của detector.
- plate box/polygon trên một tập chẩn đoán.
- liên kết `parking_session_id` trong GT khi đánh giá ghép vào–ra.
- checksum toàn bộ file và manifest lần chạy.

Thiết kế này đủ để chạy lại nhiều phiên bản Model 2, đánh giá Model 1 độc lập, truy lỗi về đúng camera/timestamp, phân tích theo điều kiện và mở rộng sang ghép phiên gửi xe sau này.

## 13. Schema đang được writer pilot xuất

Mỗi run thực tế nằm trong `outputs/<run-group>/step1-<UTC>/`:

`run.json` có `schema_version`, `run_id`, bản sao `config`, metadata nguồn
(`uri`, `sha256`, `fps`, `frame_count`, `width`, `height`, `duration_ms`), số
frame đã decode/sample và `timestamp_basis`.
Run hiện có thêm `artifacts.detections_uri` trỏ tới `detections.jsonl` và
`artifacts.detection_record_count`.

Một dòng `events.jsonl` hiện có các trường:

```json
{
  "schema_version": "0.4.0",
  "run_id": "step1-...",
  "event_id": "EVT-000001",
  "track_id": 12,
  "vehicle_type": "car",
  "start_ms": 1200,
  "end_ms": 3650,
  "hits": 25,
  "confidence_mean": 0.81,
  "confidence_max": 0.94,
  "crossed": true,
  "crossing_ms": 2450,
  "first_detection": {
    "timestamp_ms": 1200,
    "track_id": 12,
    "vehicle_type": "car",
    "confidence": 0.87,
    "box": [120, 80, 540, 420]
  },
  "track_artifact_uri": "detections.jsonl",
  "state": "CLOSED",
  "clip_id": "CLIP-000001",
  "camera_id": "CAM01",
  "lane_id": "ENTRY_01",
  "direction": "ENTRY",
  "source_uri": "D:/raw/CAM01.mp4"
}
```

`start_ms/end_ms/crossing_ms` là timestamp trên raw source. Một dòng
`clips.jsonl` có `start_ms`, `end_ms`, `event_ids`, `clip_id`, `run_id`, camera
registry, `source_uri`, `source_sha256`, `clip_uri` (null với virtual segment)
và `quality_status` (`virtual`, `valid` hoặc `invalid`). Khi materialize,
writer bổ sung `actual_start_ms`, `actual_end_ms`, `clip_sha256` và
`output_frame_count`; codec hiện dùng `mp4v`, không có audio.

Web API giữ nguyên artifact MP4 này khi gọi `GET /api/runs/{id}/media/{path}`.
Giao diện dùng cùng endpoint với `?preview=true`: backend tạo/cache bản H.264
tối đa 960 px rộng trong `.browser_media` của run để trình duyệt phát được.
Bản xem trước không thay đổi `clip_uri`, manifest, timeline hay file MP4 gốc.

Event schema `0.9.0` thêm `motion_confirmed` và `motion_distance`.
`motion_distance` là dịch chuyển anchor lớn nhất so với baseline candidate,
chuẩn hóa theo kích thước frame. Chỉ event có `motion_confirmed=true` mới
được ghi vào `events.jsonl`; ngưỡng và cửa sổ nằm trong config tại
`min_motion_distance` và `motion_window_seconds`.

Khi `make_clips=true` và có ít nhất một segment, writer còn tạo
`clips/clip_final.mp4`. Đây là media tổng hợp, không phải một event hoặc một
segment liên tục trên raw. Các clip thành phần được sắp theo `start_ms` tăng
dần và nối liền, nên thời gian trống giữa hai clip không xuất hiện trong file
final. Metadata nằm tại `run.json.artifacts.final_clip`:

```json
{
  "uri": "clips/clip_final.mp4",
  "quality_status": "valid",
  "frame_count": 130,
  "duration_ms": 13000,
  "clip_count": 2,
  "timeline_mapping": [
    {"clip_id": "CLIP-000001", "source_start_ms": 8500,
     "source_end_ms": 15000, "final_start_ms": 0,
     "final_end_ms": 6500, "frame_count": 65},
    {"clip_id": "CLIP-000002", "source_start_ms": 38500,
     "source_end_ms": 45000, "final_start_ms": 6500,
     "final_end_ms": 13000, "frame_count": 65}
  ]
}
```

Object còn có `schema_version` và `sha256`. Khi `make_clips=false` hoặc không
có segment, `run.json.artifacts.final_clip` là `null`.

GT tạo từ GUI có thêm `condition_status`, `conditions` và
`condition_annotation_source: "human"`. Không còn tag chi tiết.
`line_gate_margin` nằm trong `config`; khi có crossing line, nó giới hạn
anchor detector vào corridor trước khi mở event. Nếu có ROI, anchor phải đồng
thời nằm trong ROI. Track đã mở vẫn được cập nhật khi rời corridor để giữ đủ
khoảng video của event.

`detections.jsonl` là artifact pilot, mỗi dòng tương ứng một frame đã sample:

```json
{
  "frame_index": 36,
  "timestamp_ms": 1200,
  "detections": [
    {"track_id": 12, "vehicle_type": "car", "confidence": 0.87,
     "box": [120, 80, 540, 420]}
  ]
}
```

GUI dùng timestamp nguồn và `track_id` để chọn box đúng event, highlight box
đó ở frame đầu event và cập nhật overlay khi phát clip. Artifact này chưa phải
track artifact production đầy đủ qua ranh giới nhiều file.

GT pilot hiện do GUI tạo có `annotation_schema_version: "0.6.0"`, cùng các trường
`source_event_id` (nếu được nạp từ event Model 1), `crossed`,
`plate_readable`, `plate_readability`, `readable_timestamps_ms`, `plate_text`,
`condition_status`, `conditions` và
`suggestions`. `crossed` là boolean HITL chỉ nhận `true` hoặc `false`; khi nạp
event Model 1, GUI điền sẵn giá trị đó và ghi lại gợi ý tại
`suggestions.crossed` với nguồn `model1_event`. Các trường top-level là giá
trị người dùng xác nhận; `suggestions` chỉ là gợi ý có nguồn, ví dụ:

```json
"suggestions": {
  "crossed": {"value": true, "source": "model1_event", "event_id": "EVT-000001"},
  "plate_text": {"value": "ZPN720", "source": "plate_ocr", "event_id": "EVT-000001", "confidence": 0.96},
  "conditions": {"value": [], "condition_status": "good", "plate_readable": true,
                 "source": "cv_vlm", "event_id": "EVT-000001",
                 "evidence_timestamps_ms": [1200, 1400]}
}
```

Detector biển số và OCR pilot hiện có thể điền `plate_text`; nhánh CV + VLM
có thể gợi ý `condition_status` và ba nguyên nhân cấp cao khi bật tùy chọn. Chúng
không tự thay thế annotation người dùng và không được đưa vào Model 2 như
ground truth chưa xác nhận.

Các trường production như `site_id`, UTC capture, `source_fragments`, media
probe đầy đủ và ảnh representative frames chưa được writer pilot tạo.
