# Đặc tả bước 1: phát hiện lượt xe và cắt video

## Bộ lọc chuyển động MOG2 tùy chọn trước detector (triển khai 29/09/2026)

`motion_gate_enabled=false` mặc định. Khi bật, MOG2 quan sát các frame ở
`sample_fps` sau khi thu nhỏ; chỉ foreground trong ROI được tính, không có
ROI thì dùng toàn frame. YOLO phải chạy ở giai đoạn khởi động, trong khoảng
giữ sau chuyển động, khi EventEngine còn track mở, và mỗi chu kỳ dò kể cả
không thấy chuyển động. Frame bị gate bỏ qua được ghi là
`detector_skipped=true`, không được xem là một lần YOLO dự đoán rỗng.
`sampled_frames` vẫn là số frame đưa qua tầng lấy mẫu; `detector_frames` là
số frame thực sự gọi YOLO. Video raw, timestamp và quy tắc clip không đổi.

Ngưỡng mặc định: ảnh MOG2 rộng 320 px, diện tích tiền cảnh tối thiểu 0,2%
của vùng xét; khởi động 1 giây, giữ sau chuyển động 1,5 giây và dò lại mỗi
0,5 giây. Các tham số này nằm trong `RunConfig`; có thể chỉnh qua JSON/API,
CLI có cờ `--motion-gate`, web và GUI có checkbox. Khi MOG2 lỗi OpenCV,
pipeline tiếp tục bằng YOLO cho tất cả frame còn lại và ghi lỗi fallback
trong `run.json`. Đây là bộ lọc ưu tiên recall, không bảo đảm không bỏ sót ở
mọi camera; trước khi bật mặc định cần đối chiếu với GT từ video thực có
nhiều đoạn yên, xe đi chậm, thay đổi sáng và bóng.

## Hủy run web local

Run `QUEUED` hoặc `RUNNING` có thể nhận tín hiệu hủy từ web. Worker kiểm tra
cờ trước khi chạy, trong vòng đọc frame, khi ghi clip/clip final và trước
các nhánh OCR/CV–VLM. Nhánh enrichment tiếp tục kiểm tra trong vòng xử lý
event. Khi hủy, run chuyển `CANCELLED`, không được báo `COMPLETED`; artifact
dở dang thuộc thư mục run vẫn được liên kết để người dùng có thể xóa run.

## Bổ sung pilot: gợi ý điều kiện theo event

Sau khi có event, nhánh tùy chọn chọn tối đa 1–5 frame từ raw video của đúng
track. Ưu tiên frame chất lượng trong artifact biển số; nếu chưa chạy OCR thì
lấy mẫu từ `detections.jsonl`. CV đo sáng tối, vùng cháy sáng và phương sai
Laplacian ở crop biển/xe; nhãn thiếu sáng dùng thống kê toàn cảnh để tránh
coi vùng nền màu tối của biển là cảnh thiếu sáng. Qwen3-VL-2B-Instruct nhìn
contact sheet gồm cảnh, xe và biển.

Quyết định gồm hai tầng. Tầng đầu đánh giá `plate_readable`. Nếu biển có khả
năng đọc được, `condition_status="good"` và `conditions=[]`, kể cả khi có lỗi
nhẹ nhưng không cản trở việc đọc. Chỉ khi không đọc được mới phân loại một
hoặc nhiều nguyên nhân cấp cao: `capture_blur` (camera/lấy nét/chuyển động làm
mờ), `plate_obstruction` (vật thể che biển), `lighting_issue` (ánh sáng làm
mất khả năng đọc). Không còn detail. Không gợi ý `plate_obstruction` nếu không
có box biển. OCR cùng chuỗi ở ít nhất hai frame với confidence ≥ 0.85 là bằng
chứng đọc được và buộc trạng thái `good`. Kết quả chỉ là gợi ý, không đi vào
Model 2 hoặc sửa GT. Người gán kiểm tra rồi lưu GT với nguồn `human`.

## 1. Mục tiêu

Bước 1 nhận video gốc liên tục từ nhiều camera và tạo ra các đoạn video chứa xe đi qua làn. Trong phạm vi hiện tại, mỗi làn có đúng một camera và mỗi camera gắn với đúng một `lane_id`; mỗi làn có hướng cố định `ENTRY` hoặc `EXIT` đã được khai báo trong cấu hình. Bước này xử lý độc lập từng camera/làn, nhận ba lớp `car`, `motorcycle`, `bicycle`, và chưa ghép lượt vào với lượt ra. `bicycle` tạo event/clip nhưng không đi qua các nhánh biển số.

Ưu tiên cao nhất là **không bỏ sót lượt xe và không cắt mất những frame có thể đọc biển số**. Giảm thời lượng video và dung lượng lưu trữ là mục tiêu thứ hai.

```text
Raw video nhiều camera
    → chuẩn hóa metadata và timeline
    → detector xe
    → tracker trong từng camera
    → kiểm tra xe đi vào vùng nghiệp vụ
    → mở/duy trì/đóng khoảng cần giữ
    → thêm buffer đầu và cuối
    → gộp khoảng gần nhau
    → xuất pre-video + manifest sự kiện
```

## 2. Đầu vào và đầu ra

Định dạng trường, cấu trúc thư mục và ví dụ JSON hoàn chỉnh được quy định trong [`dinh_dang_dau_ra_buoc_1.md`](dinh_dang_dau_ra_buoc_1.md).
Kiến trúc triển khai và cách giảm tải được chốt trong [`kien_truc_cuoi_buoc_1.md`](kien_truc_cuoi_buoc_1.md).

### Đầu vào bắt buộc

- File hoặc stream video gốc, không mất timestamp.
- `camera_id`, `lane_id`, `direction` (`ENTRY` hoặc `EXIT`).
- FPS, độ phân giải, codec, thời điểm bắt đầu video và timezone.
- Cấu hình theo camera: vùng nghiệp vụ `event_roi`, vùng có cơ hội đọc biển `readable_roi`, các vùng bỏ qua và đường/vùng xác nhận xe đi qua.

Ánh xạ `camera_id → lane_id → direction` là một-một và được đọc trực tiếp từ cấu hình camera. Model không cần suy luận xe thuộc làn nào hoặc làn là `ENTRY` hay `EXIT`. Mỗi camera vẫn có ROI nghiệp vụ riêng để loại chuyển động ngoài vùng cần xử lý.

### Đầu ra bắt buộc

1. **Pre-video** chứa đủ khoảng xe xuất hiện và phần đệm trước/sau.
2. **Manifest clip** dạng JSON/CSV, tối thiểu có:
   - `clip_id`, đường dẫn video nguồn và hash;
   - `camera_id`, `lane_id`, `direction`;
   - `source_start_ms`, `source_end_ms`;
   - đường dẫn clip, FPS và độ phân giải đầu ra;
   - danh sách `event_id` nằm trong clip;
   - phiên bản detector/tracker/config;
   - trạng thái xử lý, cảnh báo mất frame hoặc lỗi encode.
3. **Manifest lượt xe**, tối thiểu có:
   - `event_id`, `camera_id`, `lane_id`, `direction`;
   - `event_start_ms`, `event_end_ms`, `track_id`;
   - loại xe và confidence nếu có;
   - clip chứa sự kiện và khoảng thời gian tương đối trong clip;
   - ảnh đại diện hoặc các frame tốt được chọn bằng tiêu chí không dùng ground truth.

Một clip có thể chứa nhiều sự kiện khi các xe đi sát nhau hoặc xuất hiện đồng thời. Không ép một clip tương ứng đúng một xe.

## 3. Định nghĩa một lượt xe

Một `event` là một lần một xe đi vào vùng nghiệp vụ của một làn và hoàn thành việc đi qua hoặc rời vùng. Các quy tắc phải được chốt trước khi gán nhãn:

- Xe dừng chờ barrier vẫn là cùng một event.
- Detector hụt vài frame không tạo event mới.
- Xe lùi rồi tiến lại trong cùng vùng được giữ cùng event nếu chưa thỏa điều kiện kết thúc.
- Xe rời hoàn toàn rồi quay lại sau thời gian tái nhập đã định có thể tạo event mới.
- Xe đỗ hoặc chạy ở nền ngoài ROI không phải event của làn.
- Người đi bộ, barrier chuyển động, bóng và đèn thay đổi không phải event.
- Hai xe đi sát nhau vẫn phải là hai event nếu có thể phân biệt được.
- Sự kiện bắt đầu trước hoặc kết thúc sau ranh giới file được gắn `truncated`; nối qua file theo timestamp nếu dữ liệu liên tục.

## 4. Các module cần xây

> **Đối chiếu triển khai:** Pilot hiện đã có phiên bản tối giản của các mục
> 4.2–4.6 trong `src/parking_step1/`: cấu hình JSON, ROI/line trên GUI,
> YOLO26s + ByteTrack, EventEngine, segment planner, manifest và MP4
> materializer. Pilot nhận một file raw cho một camera/làn mỗi run; ingest
> nhiều file, `readable_roi` riêng, timeline VFR và các trường production
> giàu hơn vẫn là thiết kế mục tiêu. Xem
> [`trang_thai_trien_khai.md`](trang_thai_trien_khai.md) để biết bằng chứng
> chạy thực tế.

Tab kết quả của GUI cho phép chọn hoặc double-click một event để phát clip
ngay trong cửa sổ và tua theo timeline clip tới `event.start_ms`. Frame đầu
event được vẽ box, lớp, confidence và track ID từ `detections.jsonl`; khi phát,
GUI tiếp tục vẽ các detection gần timestamp hiện tại. Box của track event đang
chọn được giữ theo detection gần nhất trong toàn khoảng `event.start_ms` đến
`event.end_ms`, nên không biến mất khi tua giữa các frame detector đã lấy mẫu;
box không được giữ sang phần buffer ngoài event. Với clip ảo, player đọc
trực tiếp khoảng tương ứng trên raw; không tạo file tạm.

### 4.1 Ingest và chuẩn hóa thời gian

- Đọc metadata, kiểm tra video hỏng, khoảng mất frame và timestamp không liên tục.
- Tạo timeline theo millisecond của video nguồn; mọi clip phải ánh xạ ngược chính xác về nguồn.
- Ghép logic các file liên tiếp của cùng camera để xe ở ranh giới file không bị đếm hai lần.
- Không đổi tỷ lệ khung hình; hạn chế encode lại. Nếu encode lại thì giữ nguyên độ phân giải/FPS ở baseline và ghi cấu hình.

### 4.2 Cấu hình camera và làn

- UI hoặc file cấu hình để vẽ `event_roi`, `readable_roi`, vùng bỏ qua và đường/vùng crossing.
- Cấu hình bắt buộc ánh xạ một `camera_id` tới đúng một `lane_id` và một `direction`; không cho phép một camera/làn được khai báo mâu thuẫn.
- Lưu phiên bản cấu hình; cùng một lần đánh giá phải dùng cấu hình bất biến.
- Cấu hình riêng theo camera vì góc nhìn và kích thước xe khác nhau.

### 4.3 Phát hiện và theo dõi xe

Baseline đề xuất:

- Detector chỉ giữ ba lớp COCO `bicycle`, `car`, `motorcycle`; mọi lớp khác bị loại khỏi logic tạo event.
- ByteTrack hoặc tracker tương đương chạy riêng cho từng camera.
- Pilot đọc tuần tự mọi vị trí frame để giữ timeline; ở vị trí được chọn theo
  `sample_fps` dùng OpenCV `read()` lấy ảnh BGR cho detector, còn vị trí bỏ qua
  dùng `grab()` để tiến decoder mà không tạo ảnh BGR. Lịch lấy mẫu và timestamp
  vẫn tính từ frame index/FPS nguồn; video xuất cho bước sau giữ FPS và kích
  thước nguồn. Đây không phải MOG2 hoặc bộ lọc khoảng trước YOLO.
- Không dùng biển số để tạo event ở bước 1 vì biển nhỏ/bẩn/tối có thể làm mất cả lượt xe trước khi tới model dev.
- Giữ detection confidence tương đối thấp ở bước tạo candidate; tracker và ROI giúp loại nhiễu. Ngưỡng phải chọn trên validation.

Cần lưu detection/track trung gian đủ để xem lại nguyên nhân bỏ sót, nhưng không nhất thiết giữ kết quả từng frame vĩnh viễn sau khi hoàn thành đánh giá.

#### Ý nghĩa kích thước input detector

`imgsz=960` nghĩa là frame được resize để đưa qua detector với kích thước xử lý mục tiêu 960 pixel. Ví dụ frame nguồn 1920×1080 có thể được thu về khoảng 960×540 rồi padding/căn chỉnh theo yêu cầu model. Tỷ lệ hình phải được giữ để xe không bị méo. Tọa độ box sau inference phải được đổi ngược về hệ tọa độ 1920×1080.

Thông số này chỉ áp dụng cho bản sao frame dùng phát hiện xe. Video raw và clip giao Model 2 vẫn giữ FPS/độ phân giải nguồn. `960` là điểm bắt đầu để benchmark, không phải giá trị đã chốt:

- 640: nhanh hơn nhưng xe máy nhỏ/xa dễ mất chi tiết.
- 960: cân bằng tốc độ và chi tiết cho pilot.
- 1280: giữ nhiều chi tiết hơn nhưng tốn GPU và thời gian hơn.

Chọn bằng event recall/readable retention trên validation thay vì mặc định kích thước lớn nhất.

### 4.4 Máy trạng thái sự kiện

Mỗi track có các trạng thái gợi ý:

```text
OUTSIDE → CANDIDATE → ACTIVE → LEAVING → CLOSED
```

- `CANDIDATE`: xe mới chạm ROI, chờ đủ số frame/thời gian để loại nhiễu.
- `ACTIVE`: xe đã được xác nhận; hệ thống giữ video, kể cả khi xe dừng.
- `LEAVING`: tạm mất xe hoặc xe rời ROI; chờ grace period để tránh cắt do hụt detection.
- `CLOSED`: xe đã rời đủ lâu; đóng event.

Diễn giải chi tiết:

- `OUTSIDE`: chưa có track `car`/`motorcycle`/`bicycle` hợp lệ trong event ROI; chưa mở event.
- `CANDIDATE`: detector vừa thấy một phương tiện nhưng chưa đủ bằng chứng. Nếu phương tiện tồn tại đủ số frame/thời gian thì xác nhận; nếu biến mất ngay thì coi là nhiễu và quay lại `OUTSIDE`.
- `ACTIVE`: lượt xe đã được xác nhận. Hệ thống mở event, giữ video và tiếp tục giữ khi xe dừng trước barrier.
- `LEAVING`: xe vừa rời ROI hoặc tạm mất detection. Hệ thống chưa đóng ngay mà chờ grace period để xử lý che khuất/hụt detection.
- `CLOSED`: hết grace period mà xe không quay lại; chốt event. `event_end` là thời điểm xe được thấy hợp lệ lần cuối, còn clip kết thúc tại `event_end + post_buffer`. Thời gian chờ grace period không được cộng trùng lần nữa vào post-buffer.

Ví dụ bình thường:

```text
t=0.0s  OUTSIDE: chưa có xe
t=1.0s  CANDIDATE: thấy car lần đầu
t=1.3s  ACTIVE: car được xác nhận, mở event
t=4.0s  ACTIVE: car dừng trước barrier, vẫn giữ video
t=7.0s  LEAVING: car rời ROI
t=8.5s  CLOSED: hết grace period, chốt event
```

Nếu detector hụt ngắn, event đi `ACTIVE → LEAVING → ACTIVE`. Xe xuất hiện lại trong grace period vẫn giữ cùng `event_id`; không tạo hai lượt. Detection giả hoặc xe đỗ đứng yên thường ở `CANDIDATE` rồi bị loại, không tạo event hoàn chỉnh.

`CANDIDATE → ACTIVE` cần đồng thời đủ `candidate_hits` và đủ chuyển động.
Chuyển động dùng anchor là điểm giữa đáy bounding box, với khoảng cách chuẩn
hóa `sqrt((dx/frame_width)^2 + (dy/frame_height)^2)`. Mặc định cần đạt
`0.015` trong cửa sổ `1.5 s`. Nếu một candidate đứng yên quá cửa sổ, baseline
và thời điểm bắt đầu candidate được cuộn tới hiện tại; nhờ vậy xe đỗ lâu rồi
rời chỗ không tạo clip bắt đầu từ nhiều phút trước. Sau khi active, motion
gate không áp dụng lại nên xe dừng trước barrier vẫn thuộc cùng event.

Các tham số như số frame xác nhận candidate, grace period và buffer phải đo trên validation. Giá trị thử ban đầu có thể là xác nhận sau 2–3 detection liên tiếp và grace period 1–3 giây; đây chưa phải ngưỡng nghiệm thu.

Logic `presence` để giữ video cần tách khỏi logic `crossing` để đếm event. Xe dừng trước barrier vẫn phải giữ video dù chưa cắt qua đường ảo.

- `event_roi`: vùng mà khi xe xuất hiện, hệ thống cần giữ video.
- `crossing_line` hoặc crossing zone: mốc dùng xác nhận xe thực sự đi qua làn và tránh đếm chuyển động ngoài luồng.
- `presence=true`: xe đang ở vùng cần quan sát; dùng mở/duy trì clip.
- `crossed=true`: tâm hoặc điểm neo của track đã đi qua mốc theo quy tắc cấu hình; dùng xác nhận lượt.

Trong bước cắt, `presence` trong ROI được ưu tiên để không bỏ mất video.
Nếu có line, pilot dùng corridor quanh line làm cổng mở event;
`line_gate_margin` điều chỉnh bán kính corridor. Khi có cả ROI và line, anchor
mới phải nằm trong phần giao `ROI ∩ corridor`. `crossing` vẫn chỉ ghi nhận
trạng thái đã cắt qua line và không làm hệ thống ngừng giữ video khi xe đang
đứng chờ sau khi event đã active.

Trước khi chạy, nếu cấu hình có cả ROI và line, đoạn line phải có ít nhất một
điểm nằm trong ROI hoặc giao/chạm một cạnh ROI. Line hoàn toàn ngoài ROI bị
từ chối, kể cả khi corridor quanh line giao một phần với ROI. Quy tắc dùng
chính đoạn line, không dùng độ rộng corridor để hợp thức hóa hình học sai.

### 4.5 Tạo khoảng video cần giữ

- Khi event mở, lấy thêm `pre_buffer` từ bộ đệm vòng hoặc từ file nguồn.
- Khi event đóng, giữ thêm `post_buffer`.
- Gộp các khoảng chồng lấn hoặc cách nhau ít hơn `merge_gap`; không xuất nhiều lần cùng dữ liệu.
- Không làm mất metadata khi clip chứa nhiều xe.
- Nếu sự kiện dài bất thường, chia file vật lý để dễ xử lý nhưng giữ cùng event và timeline liên tục.
- Sau khi xuất, kiểm tra file đọc được, duration, frame đầu/cuối và ánh xạ timestamp.
- Nếu bật xuất MP4 và có ít nhất một segment, nối các segment theo
  `start_ms` tăng dần thành `clips/clip_final.mp4`. Không chèn thời gian trống
  giữa các segment; lưu ánh xạ `final_start_ms/final_end_ms` về
  `source_start_ms/source_end_ms` và `clip_id` trong `run.json`.

Thông số pilot nên thử, chưa phải giá trị chốt: 5 FPS, 10 FPS và FPS gốc cho detector; `pre_buffer`/`post_buffer` 1–2 giây; grace period 1–3 giây. Chọn bằng validation.

### 4.6 Ground truth cho bước 1

Ground truth phải được tạo từ **các khoảng video raw liên tục**, gồm cả phần model không giữ lại. Mỗi event GT cần:

- `gt_event_id`, camera/làn/hướng;
- thời điểm xe bắt đầu và kết thúc trong ROI;
- trạng thái `crossed` là boolean `true` hoặc `false` xác nhận xe đã qua
  crossing line; giá trị Model 1 chỉ là gợi ý để người gán kiểm tra;
- loại xe;
- các khoảng hoặc keyframe có thể đọc biển số;
- trạng thái `readable`, `partially_readable`, `unreadable`, `no_plate`, `out_of_view`;
- nhãn ca khó: tối, chói, mưa, che khuất, xe đi sát, dừng lâu, đi lùi;
- trạng thái `truncated` hoặc video lỗi.

Không cần gán text biển số cho mọi event để đánh giá cutter. Text sẽ cần cho bước 2; ở bước 1 chỉ cần biết liệu cơ hội đọc biển trong raw có còn nằm trong clip được giữ hay không.

Trong GUI pilot, người dùng có thể chọn một event Model 1 để nạp thời gian,
loại xe và `crossed` làm **gợi ý**, sau đó xem raw/clip, chỉnh lại và bấm thêm
hoặc cập nhật GT. Event Model 1 bỏ sót vẫn phải được tạo thủ công từ raw. Giá
trị cuối cùng trong GT luôn có `annotation_source: "human"`; thông tin nạp từ
model chỉ nằm trong `source_event_id`/`suggestions` để truy vết và không được
xem là nhãn đã xác nhận.

Bảng GT trong GUI hiển thị toàn bộ trường annotation và provenance của từng
record, không chỉ ID, loại xe và thời gian. Các trường chưa được gán hiển thị
`None`; `suggestions` và `source_uri` có thể xem bằng cuộn ngang hoặc tooltip.

Quy trình pilot:

1. Chọn video liên tục từ từng làn, gồm giờ vắng/đông, ngày/đêm và các loại xe.
2. Người gán nhãn xem toàn bộ đoạn raw, không chỉ candidate do model sinh.
3. Một người thứ hai kiểm tra toàn bộ event model bỏ sót, event sát nhau và một mẫu ngẫu nhiên các event còn lại.
4. Khóa phiên bản GT trước khi chỉnh threshold/config trên test.

## 5. Matching và metric

Ghép event dự đoán với event GT theo cùng camera/làn, giao nhau về thời gian và vị trí/track nếu có. Dùng matching một-một; không dùng biển số để ghép.

### Metric nghiệm thu chính

| Metric | Cách tính | Mục đích |
|---|---|---|
| Event recall | Số event GT được giữ đủ theo quy tắc coverage / tổng event GT | Phát hiện xe bị bỏ sót. |
| Readable-opportunity retention@k | Tỷ lệ event có ít nhất k frame đọc được trong raw vẫn giữ đủ k frame | Kiểm tra dữ liệu hữu ích cho model2. Báo k=1 và k phù hợp model2, ví dụ 3. |
| Event precision | Event dự đoán ghép đúng / tổng event dự đoán | Chỉ tính khi module phát ra event rõ ràng. |
| False clips/hour | Clip không giao event GT / số giờ raw | Đo clip sinh do nhiễu. |
| Video reduction | `1 − thời lượng hợp các khoảng giữ / thời lượng raw hợp lệ` | Đo mức giảm dữ liệu. |

### Metric chẩn đoán

- Phân bố phần trăm thời lượng mỗi event được giữ; không chỉ báo một ngưỡng pass/fail.
- Start loss và end loss theo giây: median, p95 và max.
- Fragmentation: tỷ lệ event bị giữ thành nhiều khoảng rời.
- Duplicate event rate: một xe bị sinh nhiều event.
- Merge error rate: hai xe phân biệt được nhưng bị coi là một event.
- Temporal precision: phần thời gian giữ thực sự giao với event GT.
- Runtime factor, peak RAM/VRAM, tỷ lệ video lỗi.
- Toàn bộ metric phải báo theo từng camera, từng làn, ENTRY/EXIT, loại xe và điều kiện sáng.

Hai mục tiêu `Event recall` và `Readable-opportunity retention` phải được ưu tiên khi chọn cấu hình. Không chọn cấu hình chỉ vì giảm video nhiều nếu nó làm mất lượt xe hoặc mất phần biển số rõ.

## 6. Thí nghiệm cần thực hiện trước khi chốt phương pháp

Trên cùng tập validation và cùng ground truth, so sánh:

1. Background subtraction trong ROI làm baseline rẻ.
2. Detector + tracker + ROI ở 5 FPS, 10 FPS và FPS gốc.
3. Các ngưỡng confidence, thời gian xác nhận, grace period và buffer.
4. Video gốc với video encode lại để kiểm tra model2 có mất chất lượng đầu vào không.

Chọn cấu hình theo thứ tự:

1. Đạt yêu cầu event recall.
2. Đạt yêu cầu readable-opportunity retention.
3. Trong các cấu hình đạt hai điều kiện trên, chọn cấu hình giảm video tốt hơn và có runtime phù hợp.

Nếu detector pretrained hụt nhiều xe máy hoặc ca che khuất, gán thêm dữ liệu train/validation và fine-tune detector. Không xây model mới trước khi baseline được đo và chỉ ra đúng nhóm lỗi.

## 7. Các trường hợp bắt buộc kiểm thử

- Một xe đi vào/ra bình thường.
- Xe máy và ô tô đi qua làn.
- Hai xe nối sát hoặc song song trong cùng góc nhìn.
- Xe dừng lâu trước barrier.
- Xe lùi, quay đầu hoặc vào ROI rồi rời ra.
- Detector mất xe trong vài frame.
- Biển số chỉ rõ ở đầu hoặc cuối lượt.
- Đêm, ngược sáng, đèn pha, mưa và bóng chuyển động.
- Người đi bộ/barrier chuyển động nhưng không có xe.
- Xe đỗ nền ngoài làn.
- Event qua ranh giới hai file video.
- File thiếu frame, sai FPS hoặc timestamp gián đoạn.

## 8. Thứ tự triển khai đề xuất

1. Chốt schema camera/làn, event và manifest.
2. Viết bộ đọc video, timeline và công cụ vẽ ROI.
3. Gán ground truth pilot từ raw video liên tục.
4. Làm baseline detector + ByteTrack + state machine + clip writer.
5. Viết evaluator và trang xem false positive/false negative theo timestamp.
6. Chạy ma trận thí nghiệm trên validation, chốt cấu hình.
7. Khóa test và phát hành báo cáo bước 1 theo từng làn.

Đầu ra hoàn thành của bước 1 phải cho phép trả lời được ba câu hỏi: có bỏ sót lượt xe nào không, có giữ được lúc biển số đọc được không, và đã giảm được bao nhiêu video với chi phí xử lý bao nhiêu.

## Xuất clip vật lý hiện đã triển khai

Pipeline quy đổi `start_ms/end_ms` sang chỉ số frame như cũ, lấy đủ frame đầu
đến trước frame cuối, và xuất CFR theo FPS raw. Trên máy có `imageio-ffmpeg`
hoặc lệnh `ffmpeg`, đường ưu tiên dùng CPU `libx264` preset `ultrafast`,
H.264/yuv420p MP4; FFmpeg phải trả đúng số frame, FPS và decode được frame
đầu. Clip bắt đầu muộn seek gần vị trí cần cắt rồi đối chiếu frame đầu/cuối
với raw; nếu lệch thì giải mã/đếm frame từ đầu. Nếu FFmpeg thiếu hoặc lỗi,
dùng lại `cv2.VideoWriter` `mp4v`. Nhiều clip do
FFmpeg tạo được nối bằng concat stream copy theo thứ tự nguồn; nếu không,
đường nối OpenCV vẫn hoạt động. Mốc raw và frame count giữ nguyên nhưng codec,
byte file và sai số nén ảnh khác bản MP4 cũ. Không áp dụng cắt stream copy theo
keyframe cho clip con vì có thể làm lệch ranh giới.
# Plate Enrichment tùy chọn hiện đã triển khai

Sau khi Bước 1 tạo `events.jsonl` và `detections.jsonl`, enrichment đọc raw
video theo `frame_index`, chỉ lấy detection có `track_id` và timestamp thuộc
event. Box xe được nới 12%, rồi model `yolov8n-oiv7.pt` tìm class
`Vehicle registration plate` trong crop đó. Mỗi box biển được chấm điểm để
chọn tối đa 5 frame cách nhau ít nhất 300 ms. Model
`latin_PP-OCRv5_mobile_rec` đọc từng crop; phiếu cùng chuỗi sau chuẩn hóa
được cộng trọng số `quality.score × ocr_confidence`. Kết quả chỉ là gợi ý
`plate_text` trong HITL, không tự ghi thành nhãn chuẩn. Nếu không tìm được
biển hoặc OCR rỗng, consensus là `null`.
YOLO biển số chạy theo lô tối đa 8 crop trong mỗi event; thứ tự kết quả vẫn
ứng với thứ tự frame. Khi crop trong lô có kích thước khác nhau, padding của
model có thể khiến box, confidence và frame được chọn khác cách gọi từng crop.
Không coi batch là bảo đảm kết quả gợi ý giống từng byte với run cũ.
Trong từng event, crop biển có padding OCR được giữ tạm tối đa 64 MiB ở RAM
khi đọc frame để detect; frame được chọn sẽ OCR trực tiếp từ crop này. Khi
giới hạn bộ nhớ không đủ, nhánh OCR đọc lại đúng frame raw như trước. Crop
cache không thêm field/artifact và phải giữ cùng pixel với cách đọc lại raw.
