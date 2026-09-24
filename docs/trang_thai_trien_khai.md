# Trạng thái triển khai

Ngày cập nhật: **24/09/2026** — phạm vi: pilot Bước 1, chạy offline từng
camera/làn.

## Cập nhật 24/09/2026: đo điểm nghẽn và bỏ mã hóa trùng clip final

- Run hoàn thành `step1-20260924T064758430929Z` (raw 17,395 s, 522 frame,
  3060×1664, detector 10 FPS/174 frame, 4 event, 1 clip) dùng code cũ mất
  550,000 s: lõi 144,516 s, OCR 156,828 s, CV–VLM 248,656 s. Đây là số đo
  **theo chặng**, chưa phân rã model/đọc ghi trong chính run cũ.
- Kiểm tra artifact: segment `CLIP-000001.mp4` và `clip_final.mp4` của run này
  đều 74.274.732 byte, có cùng SHA-256. Code cũ đọc raw và mã hóa 522 frame
  *hai lần*. Run mới có đúng một segment vật lý sao chép byte clip đã xuất
  thành final; timeline, hash, frame count, codec và nội dung được giữ nguyên.
  Run có nhiều segment vẫn dùng cách nối hiện tại. Không thay đổi detector,
  tracker, OCR, VLM hoặc tham số inference.
- Nhánh Plate trước đây gọi `CAP_PROP_POS_FRAMES` trên từng frame ứng viên và
  từng frame OCR; Condition cũng seek từng frame. `SequentialFrameReader`
  hiện đi tiếp bằng `grab`, chỉ seek khi cần quay lại. Benchmark đúng thứ tự
  173 yêu cầu frame của run trên: seek mỗi lần mất **82,037 s**; reader mới
  mất **5,611 s** (6 seek, 822 grab, 173 read). Đây là microbenchmark đọc
  frame, chưa phải thời gian tiết kiệm đo trên full run. Trên 14 frame rải
  đều ở raw hiện tại, kể cả quay lui, ảnh của reader mới bằng ảnh seek cũ
  từng pixel. OCR vẫn nhận cùng crop, chọn cùng candidate và dùng cùng model.
- `runtime.json` schema `0.3.0` giữ các trường tổng cũ và thêm profile trong
  từng chặng: nạp model, giải mã/seek, inference, xử lý event, hash và xuất
  video. Nhờ vậy run **mới** mới xác định được thời gian chính xác của từng
  phần; không suy ngược được số này từ run cũ. API/evaluator hiện vẫn chỉ hiển
  thị tổng ba chặng; profile nằm trong artifact để phân tích khi cần.
- Benchmark độc lập trên đúng video raw, cùng máy: giải mã tuần tự 522 frame
  6,551 s; hash file 0,068 s. Đọc và mã hóa một lượt MP4 `mp4v` 522 frame
  mất 30,924 s (đọc 7,893 s, ghi 22,986 s), cho file 74.274.732 byte.
  YOLO26s+ByteTrack 960 px trên 30 frame đầu: khởi tạo adapter 2,383 s;
  inference frame đầu 4,332 s, 29 frame còn lại trung bình 0,328 s/frame.
  Các benchmark ngắn này cho biết xu hướng, không thay thế profile của run
  hoàn chỉnh và không là cam kết thời gian sau tối ưu.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **55 tests, OK**; test xác nhận clip final một segment giống byte clip
  thành phần, artifact runtime có profile, reader giữ nguyên frame.
- Chạy lại **đủ pipeline thật** với cùng raw, cấu hình và weights trong
  `outputs/perf_validation/step1-20260924T074735616078Z`: **394,484 s**
  so với **550,000 s** của run cũ, giảm **155,516 s** (28,3%). Lõi
  105,313 s (nạp YOLO 1,828; decode 8,532; YOLO+ByteTrack 60,155;
  xuất segment 34,110; copy final 0,281). Plate/OCR 90,906 s (nạp model
  27,765; seek/decode 7,329; YOLO biển 53,060; OCR 2,172). CV–VLM
  198,250 s (nạp model 14,594; seek/decode 2,389; CV/contact sheet 0,595;
  tiền xử lý+suy luận VLM 180,203). Các phần nhỏ còn lại là điều phối,
  ghi manifest và chọn/fusion. Chênh lệch VLM so với run cũ cũng có thể do
  biến thiên tải CPU; code không đổi model/prompt và không thể quy toàn bộ
  phần giảm VLM cho cách đọc frame.
- So sánh output hai run: 4 event cùng loại và mốc đầu/cuối; số candidate,
  box/chất lượng plate và consensus OCR bằng nhau; CV metric, VLM JSON và
  condition của cả 4 event bằng nhau. MP4 segment lẫn final của hai run có
  cùng SHA-256 `5d223879af9cb6809d7825b0fdf8c12b185efc99b916b80c452a1e3edbdf7abf`.
  Số đo trên một video này chưa chứng minh tốc độ/cùng output cho mọi codec
  hoặc cấu hình nhiều clip; cần đo các video khác khi có mẫu.

## Cập nhật 24/09/2026: chạy nhiều run đồng thời và tách bảng trạng thái

- `RunJobs` dùng `ThreadPoolExecutor` mặc định **2 worker**; đổi bằng biến môi
  trường `PARKING_WEB_MAX_WORKERS` (số nguyên >=1) trước khi khởi động backend.
  Mỗi run có snapshot cấu hình, ID và thư mục artifact riêng; run thứ ba giữ
  `QUEUED` cho tới khi worker trống. Hai model nặng chạy cùng lúc dùng chung
  tài nguyên máy; khi thiếu RAM/VRAM, hạ số worker hoặc tắt enrichment ở run.
- Trang Chạy phân tích mở ở bảng tất cả run, cập nhật trạng thái/tiến độ mỗi
  1,5 giây khi trang đang mở. `Tạo run mới` mở cấu hình, sau khi tạo quay lại
  bảng; người dùng có thể tiếp tục tạo run dù run khác đang chạy. Có thể dừng
  run chờ/chạy, mở kết quả run hoàn thành, xóa run terminal tại bảng này.
  Trang Kết quả & duyệt chỉ tải run `COMPLETED`; `CANCELLED`, `FAILED`,
  `QUEUED`, `RUNNING` chỉ ở bảng Chạy phân tích.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **54 tests, OK**, gồm test hai worker bắt đầu đồng thời và run thứ ba còn
  `QUEUED` khi cả hai worker bận; `npm run build` trong `frontend`: **đạt**.
  Backend local đã restart với code mới. Kiểm tra browser: trang Chạy phân
  tích liệt kê 3 run ở các trạng thái `CANCELLED`/`COMPLETED`, mở được màn
  Tạo run mới; trang Kết quả & duyệt chỉ còn run `COMPLETED`.

## Cập nhật 24/09/2026: căn nút Duyệt trong bảng run

- Hai trạng thái nút `Duyệt` và `Đã duyệt` trong cột Thao tác dùng cùng chiều
  rộng 112 px, nên các nút phía sau thẳng hàng giữa các dòng. Đây chỉ là thay
  đổi CSS, không đổi trạng thái hay API duyệt. Kiểm tra `npm run build` trong
  `frontend`: **đạt**.

## Cập nhật 24/09/2026: dừng run đang xử lý

- Header trang Chạy phân tích chỉ hiển thị **một** hành động theo trạng thái:
  chưa chạy/đã hủy/thất bại là `Chạy phân tích`, đang chờ/đang chạy là
  `Dừng run`, hoàn thành là `Mở kết quả`. Không còn hiện đồng thời hai nút
  Chạy phân tích và Dừng run. Kiểm tra thay đổi UI bằng `npm run build` trong
  `frontend`: **đạt**.
- Đã gửi `POST /api/runs/WEB-C8363BAF8E/cancel`; run thực tế chuyển
  `CANCELLED`, thông báo `Đã hủy`, không xuất hiện như kết quả hoàn thành.
  Artifact dở dang của chính run này được xác minh qua `run.json` và liên kết
  lại vào SQLite, để nút Xóa dọn được về sau. Sau khi restart backend, browser
  hiển thị run `CANCELLED`, không cho chỉnh sửa/duyệt và vẫn cho xóa.
- Trang Chạy phân tích và bảng Kết quả & duyệt có nút `Dừng` cho run
  `QUEUED`/`RUNNING`; gọi API hủy sẵn có và theo dõi trạng thái đến khi
  worker dừng. Worker kiểm tra cờ khi còn xếp hàng, trong vòng phát hiện,
  trong xuất clip/clip final và trước khi kết thúc hoặc vào enrichment.
  `on_run_created` lưu `pipeline_run_id` và `run_dir` sớm vào SQLite để run
  bị hủy vẫn liên kết với artifact dở dang cho thao tác xóa.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **53 tests, OK**; `npm run build` trong `frontend`: **đạt**. Test mới kiểm
  tra hủy khi đang xuất clip/final clip, run còn chờ và trường hợp cờ hủy bật
  ngay trước khi worker định ghi `COMPLETED`.

## Cập nhật 24/09/2026: xóa run ở Kết quả & duyệt

- Bảng run có nút `Xóa` ở cột Thao tác, cần xác nhận trước khi gọi
  `DELETE /api/runs/{id}`. Backend chỉ nhận `COMPLETED`, `FAILED`, `CANCELLED`;
  chặn `QUEUED`/`RUNNING` để không đụng worker. Backend chỉ xóa thư mục artifact
  là con trực tiếp của `web_data/runs`, gồm clip, JSONL, GT xuất file và cache
  preview; SQLite xóa các annotation và hàng run trong một transaction.
  Video raw trong `uploads` và các run khác không bị xóa. Run dùng đường dẫn
  artifact ngoài kho bị chặn để tránh xóa nhầm. Sau khi xóa, bảng run tải lại;
  Tổng quan tải lại số liệu khi người dùng mở lại trang.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **51 tests, OK**; `npm run build` trong `frontend`: **đạt**. Test API xác
  nhận run đang chờ bị chặn, run hoàn thành mất artifact/GT/SQLite, video raw
  còn nguyên, và đường dẫn artifact ngoài kho bị chặn.

## Cập nhật 24/09/2026: phần 4 Chi phí trên trang Đánh giá

- Phần 04 hiện bốn ô: thời gian phát hiện/cắt clip, OCR, CV–VLM và tỷ số tổng
  thời gian chạy / thời lượng video raw. Artifact `runtime.json` tăng lên
  `0.2.0` để lưu thời gian từng chặng. Nhánh tắt lưu `null`; run cũ không có
  thời gian riêng giữ `—`. Tổng của run cũ chỉ có thời gian lõi không được
  đem chia video raw như thể là tổng pipeline. API vẫn đọc `runtime.json`
  `0.1.0` và `run.json` cũ.
- Kiểm thử thay đổi bốn ô: `PYTHONPATH=src python -m unittest discover -s
  tests -q`: **50 tests, OK**; `npm run build` trong `frontend`: **đạt**.
  Browser với run cũ `WEB-29A673FD2A`: thời gian lõi 2 phút 33,9 giây,
  OCR/CV–VLM và tỷ số tổng/raw hiện `—`, video raw 17,4 giây.
- Chi tiết đánh giá thêm phần `04 · Chi phí xử lý`, hiện chỉ đo thời gian chạy
  của run tạo gợi ý. `parking_step1.run_pipeline` ghi `runtime.json`
  (`schema_version=0.2.0`, `scope=full_pipeline`, tổng và từng chặng) sau
  detector, xuất clip, OCR và CV–VLM tùy chọn. Đồng hồ bắt đầu trước khởi tạo
  model, kết thúc sau các nhánh; không tính chờ queue hoặc thời gian HITL.
- `GET /api/runs/{id}/evaluation` trả thêm `runtime`. Run cũ không có file mới
  dùng `run.json.elapsed_seconds` với `scope=step1_core_only` và giao diện ghi
  rõ không gồm OCR/CV–VLM; nếu không có cả hai thì hiện `—`. Không suy thời gian
  từ `runs.updated_at` vì timestamp này đổi khi duyệt hoặc sửa GT.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **50 passed** (gồm ghi runtime mới và fallback run cũ/không có dữ liệu);
  `npm run build` trong `frontend`: **đạt**. Kiểm tra browser với run đã duyệt
  `WEB-29A673FD2A`: phần 04 hiển thị 2 phút 33,9 giây với nhãn
  `Bước 1 lõi`, đúng theo artifact cũ chỉ lưu 153,89 giây.

## Cập nhật 24/09/2026: xuất bảng GT ra Excel kèm frame có box

- Trang `Kết quả & duyệt → Chỉnh sửa` có nút `Xuất Excel`. Frontend gửi toàn
  bộ hàng GT hợp lệ đang ở form (kể cả thay đổi chưa bấm Cập nhật) tới
  `POST /api/runs/{id}/export.xlsx`; endpoint chỉ tạo file tải về, không lưu
  GT hoặc đổi trạng thái duyệt. Workbook gồm Event, thời gian, loại xe,
  `crossed`, biển số, cờ đọc biển, trạng thái/điều kiện, clip, tên video và
  ảnh frame đại diện. Không xuất ba cột `Detector TB`, `Độ dễ (0–1)` và
  `Ưu tiên / lý do`; cột `Thao tác` là nút UI nên không có trong file.
- `src/parking_web/export_excel.py` chọn frame có biển theo
  `0,45 × plate_confidence + 0,40 × quality.score + 0,15 × ocr_confidence`
  trong khoảng GT hiện tại; vẽ box xe xanh và biển vàng từ observation.
  Nếu không có observation biển, chọn frame có confidence detector xe cao
  nhất của đúng track và vẽ box xe. GT thêm thủ công/thiếu detection lấy frame
  giữa khoảng GT nhưng không tự tạo box không có bằng chứng. Ảnh PNG được
  nhúng trong đúng hàng Excel; video raw và artifact không bị sửa.
- Dependency mới `openpyxl>=3.1` và `Pillow>=10` trong `requirements.txt`.
  Test: `PYTHONPATH=src python -m unittest discover
  -s tests -q`: **50 passed** (gồm chọn frame biển tốt nhất, fallback đúng
  track và test Excel có ảnh); `npm run build` trong `frontend`: **đạt**.
  Run thật `WEB-29A673FD2A` xuất HTTP 200, workbook 4 hàng/4 ảnh;
  kiểm tra ảnh đầu xác nhận box xanh quanh xe và box vàng quanh biển. Browser
  trên trang Chỉnh sửa hiển thị nút `Xuất Excel`; nhấn nút báo đã tạo file,
  trạng thái run vẫn `REVIEWED` và nút Cập nhật vẫn vô hiệu: **đạt**.

## Cập nhật 24/09/2026: điểm độ dễ tổng hợp cho event

- API result bổ sung vào `suggestion` bằng chứng OCR (`plate_consensus_confidence`,
  `plate_support_count`, `plate_analyzed`) và CV–VLM (`cv_clean_fraction`,
  `vlm_readable`, `condition_analyzed`). Frontend tính điểm `Độ dễ (0–1)`
  cho từng event dự đoán và cho phép sắp xếp thấp → cao. Bảng hiển thị điểm
  từng thành phần và số nhánh có bằng chứng. GT thủ công không có điểm.
- Công thức, điều kiện áp dụng và giới hạn được ghi trong
  `docs/kien_truc_web_local.md`. Điểm là heuristic để phân luồng HITL, không
  phải xác suất event/biển/điều kiện đúng. Không sửa GT hoặc artifact Bước 1.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -q`:
  **48 passed**; `node --experimental-strip-types --test
  tests/reviewPriority.test.mjs` trong `frontend`: **5 passed**;
  `npm run build`: **đạt**. API run `WEB-29A673FD2A` trả đầy đủ
  confidence xe/biển, consensus OCR, phần CV sạch và kết luận VLM. Trên browser,
  sắp xếp `Độ dễ thấp → cao` cho thứ tự EVT-000001 **0,846**,
  EVT-000003 **0,857**, EVT-000002 **0,873**, EVT-000004 **0,934**: **đạt**.
  EVT-000004 vẫn có cảnh báo riêng `Không qua line`; điểm thuận lợi từ model
  không thay thế kiểm tra quy tắc event.

## Cập nhật 24/09/2026: điểm detector để sắp xếp hàng GT

- Bảng chỉnh sửa GT thêm cột `Detector TB` và lựa chọn sắp xếp `Detector thấp
  → cao`. Giá trị là `events.jsonl.confidence_mean`: trung bình confidence
  YOLO của các lần phát hiện đúng `track_id` trên các frame tạo event, do
  EventEngine đã tính và API result đã trả về. Cột hiện thêm số lần phát hiện
  (`hits`). Event không có điểm (GT thủ công hoặc artifact cũ) hiện `—` và
  đứng sau event có điểm trong chế độ sắp xếp này. Hòa điểm theo thời gian
  bắt đầu và ID.
- Đây là điểm của **detector phương tiện**, không phải xác suất event/loại xe
  đúng; không trộn với confidence detector biển, OCR hoặc VLM. Chỉ thay đổi
  frontend và kiểu dữ liệu TypeScript, không đổi schema hay pipeline.
- Kiểm thử: `node --experimental-strip-types --test
  tests/reviewPriority.test.mjs` trong `frontend`: **3 passed** (gồm điểm
  thấp–cao, điểm thiếu và giá trị không hợp lệ); `npm run build`: **đạt**.
  Browser với run `WEB-29A673FD2A` hiển thị 81,8% / 83,8% / 86,8% /
  91,1% tương ứng EVT-000001 / 000003 / 000002 / 000004 khi chọn
  `Detector thấp → cao`: **đạt**.

## Cập nhật 24/09/2026: ngưỡng chồng lấn khi ưu tiên duyệt

- `frontend/src/reviewPriority.ts` chỉ gắn lý do chồng lấn khi hai event cùng
  camera/làn giao nhau **ít nhất 500 ms và ít nhất 20% thời lượng event ngắn
  hơn**. Giao 1 ms hoặc chồng lấn nhỏ không còn được đẩy lên vì lý do này.
  Các dấu hiệu ưu tiên khác giữ nguyên. Đây là ngưỡng hiển thị để duyệt,
  không thay đổi EventEngine, GT hoặc metric đánh giá.
- Kiểm thử: `node --experimental-strip-types --test
  tests/reviewPriority.test.mjs` trong `frontend`: **2 passed** (1/499 ms,
  500 ms nhưng tỷ lệ thấp, đạt cả hai ngưỡng và khác làn); `npm run build`:
  **đạt**. Kiểm tra trình duyệt với run `WEB-29A673FD2A`: EVT-000003 không
  còn lý do chồng lấn do chỉ giao EVT-000004 trong khoảng ngắn; EVT-000004
  vẫn đứng đầu vì riêng lý do "Không qua line": **đạt**.

## Cập nhật 24/09/2026: ưu tiên kiểm tra event trong trang chỉnh sửa GT

- Frontend thêm bộ lọc Tất cả/Cần kiểm tra event/OCR/điều kiện/GT thủ công,
  cùng sắp xếp Ưu tiên kiểm tra hoặc Theo thời gian. Cột mới ghi lý do rõ
  trên từng hàng; số hàng đang hiển thị luôn được báo. Quy tắc ở
  `frontend/src/reviewPriority.ts` dùng dự đoán gốc: GT thủ công, không qua
  line, chưa xác nhận chuyển động, overlap giữa event cùng camera/làn, ít
  detection, OCR không có biển khi bật OCR, kết quả điều kiện thiếu/khó đọc
  khi bật CV–VLM. Bicycle không bị xếp vào nhóm OCR/điều kiện.
- Bộ lọc và thứ tự chỉ thay đổi UI; không sửa dữ liệu dự đoán, GT hay metric.
  Điểm là trọng số ưu tiên duyệt theo quy tắc, chưa được hiệu chuẩn thành xác
  suất model sai. Hòa điểm theo thời gian bắt đầu rồi event ID.
- Kiểm thử: `npm run build` trong `frontend`: **đạt** (gồm TypeScript).
  Kiểm tra trình duyệt với run `WEB-29A673FD2A`: mặc định xếp 4 event, hàng
  không qua line và chồng thời gian lên đầu; lọc "Cần kiểm tra event" còn 2/4
  hàng, nút Cập nhật vẫn vô hiệu khi chưa sửa GT: **đạt**.

## Cập nhật 24/09/2026: phát Video final và clip trong trình duyệt

- Nguyên nhân lỗi dừng ở `0:00`: MP4 do OpenCV xuất dùng `FMP4/mp4v`, không
  được browser hiện tại giải mã. `src/parking_web/media.py` tạo bản xem trước
  H.264 tối đa 960 px rộng, cache theo nội dung trong `.browser_media` của run.
  Hai nút Video final/clip dùng `?preview=true`; endpoint không có tham số này
  vẫn trả artifact gốc đầy đủ độ phân giải. Không thay đổi schema, manifest,
  thời gian hay cách xuất MP4 của Bước 1.
- Đã kiểm tra run `WEB-29A673FD2A`: cả `CLIP-000001.mp4` và `clip_final.mp4`
  cùng nội dung nguồn 74,274,732 byte; bản H.264 xem trước rộng 960 px khoảng
  31.9 MB. Lần mở đầu cần thời gian mã hóa; lần sau dùng cache. Backend hiện
  dùng khóa trong một process; chưa có chính sách dọn cache tự động.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -v`:
  **48 passed**; `npm run build` trong `frontend`: **đạt**. Sau khi khởi động
  lại backend, cả file gốc và bản preview của clip/final trả HTTP **206** khi
  yêu cầu Range; trình duyệt đọc được cả hai bản preview với `readyState=4`,
  thời lượng **17.395 s**, khung hình **960×522**.

## Cập nhật 24/09/2026: rút gọn hướng dẫn trên giao diện

- Trang Tài liệu bắt đầu từ thao tác Kho video; bỏ hai mục lệnh terminal chạy
  backend và frontend khỏi ô đầu tiên theo yêu cầu. Cách chạy qua terminal
  vẫn được ghi trong tài liệu vận hành repository; API, dữ liệu và metric không đổi.
- Xác minh `npm run build` trong `frontend`: **đạt** (bao gồm TypeScript check),
  đã cập nhật `frontend/dist`. Không cần chạy lại test backend vì chỉ đổi nội
  dung văn bản trên trang Tài liệu.

## Cập nhật 24/09/2026: trang Tài liệu và Cài đặt web

- Thêm hai trang cuối sidebar ngay trên trạng thái Backend local. Tài liệu
  hướng dẫn chạy backend/frontend và đọc toàn bộ metric theo event/clip → OCR
  → CV–VLM. Cài đặt cho phép lưu mặc định nâng cao trước đây bị cố định ở
  frontend: model và input detector, grace/buffer/gộp clip, model và chọn frame
  OCR, model/số frame VLM. Thêm ba ngưỡng đánh giá temporal IoU, dung sai biên
  và độ phủ clip. Các ô khác trên trang Chạy phân tích tiếp tục chỉnh theo
  từng run.
- `src/parking_web/storage.py` thêm bảng SQLite `app_settings`; API
  `GET/PUT /api/settings` schema `0.1.0` xác thực và lưu một bản cấu hình.
  `RunPayload` và `_config` chuyển tiếp cả ngưỡng phát hiện biển/top-K/khoảng
  frame mới từ frontend tới pipeline. Frontend nạp default nâng cao vào form
  run; run cũ giữ config đã lưu. Endpoint evaluation dùng ngưỡng hiện hành nên
  điểm run đã duyệt có thể thay đổi khi sửa ngưỡng, dù GT/artifact không đổi.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -v`:
  **48 passed** (gồm lưu/đọc/validate settings, chuyển tiếp tham số OCR và
  tính lại evaluation theo ngưỡng mới); `python -m py_compile
  src/parking_web/api.py src/parking_web/storage.py`: **đạt**;
  `npx tsc --noEmit -p tsconfig.json`: **đạt**; `npm run build`: **đạt**.
  Đã khởi động lại backend local: `GET /api/settings` trả schema `0.1.0`,
  `/` phục vụ JS `index-BHAlq1D2.js` chứa trang Tài liệu/Cài đặt. Chưa có
  kiểm thử browser tự động cho thao tác form; phần này đã kiểm tra bằng build
  TypeScript và API integration test.

## Cập nhật 24/09/2026: bố cục và nhận xét trang Đánh giá

- Màn chi tiết Đánh giá nay theo ba phần: (1) phát hiện event và giữ clip,
  (2) OCR biển số, (3) điều kiện CV–VLM. Metric trên event ghép và recall toàn
  pipeline được đặt trong phần tương ứng, thay cho khối tổng hợp lẫn nhiều
  bước. Dưới mỗi phần, React tạo nhận xét tiếng Việt theo số TP/FP/FN, tỷ lệ,
  số GT, độ phủ clip và tình trạng artifact. Nhận xét dùng quy tắc xác định,
  không gọi LLM và không lưu vào GT/API; backend/schema metric không đổi.
- Xác minh: `npx tsc --noEmit -p tsconfig.json` **đạt**;
  `PYTHONPATH=src python -m unittest discover -s tests -p 'test_web*.py' -v`:
  **13 passed**; `npm run build` **đạt**. API local phục vụ
  `index-swrptiMu.js` chứa đủ ba tiêu đề bước và phần nhận xét mới.

## Cập nhật 24/09/2026: đơn giản hóa màn Đánh giá

- Bỏ ô `Cặp thời gian chưa rõ danh tính` khỏi trang Đánh giá vì không hữu ích
  cho luồng GT web hiện tại (GT gắn `source_event_id` hoặc GT thêm tay cho xe
  bỏ sót). Điểm event, OCR và điều kiện không đổi. Backend vẫn giữ trường chẩn
  đoán trong API `0.2.0` và quy tắc không chấm OCR/điều kiện cho cặp độc lập
  mơ hồ; giao diện chỉ hiển thị các metric chính.
- Xác minh: `npx tsc --noEmit -p tsconfig.json` **đạt**;
  `PYTHONPATH=src python -m unittest discover -s tests -p 'test_web*.py' -v`:
  **13 passed**; `npm run build` **đạt**. API local đang phục vụ JS mới
  `index-DZlG6AEx.js`, trong đó không còn nhãn metric đã bỏ.

## Cập nhật 23/09/2026: rà soát metric đánh giá

- `src/parking_web/metrics.py` nâng response evaluation lên `0.2.0`. Bỏ
  matching không giao thời gian trong cửa sổ 500 ms; yêu cầu temporal IoU
  ≥0,30, đúng camera/làn/chiều. Tôn trọng `source_event_id`; GT thủ công cho
  xe bỏ sót và event đã bị xóa không được ghép lại sai. Trường hợp GT độc lập
  nhiều ứng viên dùng Hungarian để ưu tiên số cặp ghép tối đa. Event sai loại
  xe tính FP+FN; báo riêng đúng `crossed`, IoU và sai số biên.
- Thêm metric clip retention@95%, độ phủ GT, foreground precision/recall và
  video reduction trên hợp khoảng thời gian; clip `invalid` không được coi là
  đã giữ video. OCR và điều kiện báo điểm trên cặp ghép **và** end-to-end tính
  cả GT xe bị bỏ sót/event dư. Run thiếu artifact enrichment hiện “chưa chạy”,
  GT biển thiếu/mâu thuẫn được đếm riêng, không âm thầm coi là sai. Điều kiện
  tách `good`/`unreadable` khỏi ba nguyên nhân đa nhãn; cặp thời gian chưa rõ
  danh tính không chấm OCR/điều kiện.
- Trang Đánh giá hiển thị các metric trên cùng số GT thêm tay, event loại và
  GT giữ nguyên trường event từ gợi ý. Chỉ báo giữ nguyên không thay thế xác
  nhận người duyệt đã kiểm tra raw. Dependency `scipy>=1.9` được khai báo
  trực tiếp cho Hungarian; các artifact Bước 1 và schema GT không đổi.
- Kiểm thử sau thay đổi: `PYTHONPATH=src python -m unittest discover -s tests -v`:
  **47 passed**; `python -m py_compile src/parking_web/metrics.py
  src/parking_web/api.py`: **đạt**; `npx tsc --noEmit -p tsconfig.json`:
  **đạt**; `npm run build`: **đạt**, đã cập nhật `frontend/dist`.
  Khởi động lại API local và kiểm tra `GET /api/runs/WEB-29A673FD2A/evaluation`:
  response `evaluation_schema_version=0.2.0`, 4/4 event khớp, clip giữ
  4/4 GT, OCR F1=0,75. Cả 4 GT của run này giữ nguyên các trường event từ
  gợi ý, nên điểm event 1,0 chỉ là mức thống nhất với bản đã duyệt, chưa
  chứng minh 4 nhãn đã được đối chiếu độc lập với video raw.

## Cập nhật 23/09/2026: GT thủ công và trang đánh giá web

- Sửa lifecycle chỉnh sửa: bấm `Chỉnh sửa` hoặc quay lại bảng không gọi
  `reopen`, không đổi `REVIEWED`. Frontend so sánh các trường GT với bản lúc
  tải/lưu; nút `Cập nhật` chỉ bật khi có thay đổi thực, kể cả thêm/xóa/khôi
  phục event. API PUT chấp nhận run đã duyệt: payload giống GT đã lưu là
  no-op giữ `REVIEWED`; payload thay đổi được lưu và chuyển `DRAFT` trong cùng
  transaction SQLite. GET/result và endpoint đánh giá vẫn đọc được khi chỉ
  mở workspace. Kiểm tra `PYTHONPATH=src python -m unittest discover -s tests -v`:
  **37 passed**; `npm run build`: **đạt**, đã cập nhật `frontend/dist`.

- Trang Đánh giá hiện mở bằng **bảng run đã duyệt** thay cho ô chọn run; bảng
  dùng cùng kiểu trình bày với Kết quả & duyệt và có nút `Chi tiết`. Màn chi
  tiết chỉ tải metric của run được chọn và có nút về danh sách. Đổi trang rồi
  quay lại sẽ làm mới danh sách run đã duyệt; backend/schema metric không đổi.
  Kiểm tra `npx tsc --noEmit -p tsconfig.json`: **đạt**;
  `PYTHONPATH=src python -m unittest discover -s tests -p 'test_web*.py' -v`:
  **3 passed**; `npm run build`: **đạt**, đã cập nhật `frontend/dist`.

- React có trang thứ năm **Đánh giá**, chọn run `REVIEWED` và hiển thị event,
  OCR, điều kiện với precision/recall/F1 cùng IoU/sai số biên/đúng loại xe và
  đúng trạng thái. Trang Kết quả & duyệt có nút **Thêm hàng GT**, tự cấp ID
  `GT-000001`… theo run, lấy mốc đầu từ video raw đang xem; người dùng sửa
  khoảng thời gian và nhãn rồi bấm **Cập nhật**. GT này có
  `source_event_id=null`, cho phép ghi xe model bỏ sót.
- Màn chỉnh sửa cho phép **Xóa** event dự đoán sai khỏi GT và **Khôi phục**
  trước khi lưu. Dấu `is_valid_event=false` chỉ còn trong SQLite để xác nhận
  đã kiểm tra; `ground_truth.jsonl` và `gt_events` chỉ gồm các event hợp lệ.
  Vì vậy tập đã duyệt chính là GT cuối cùng và event đã xóa tính là FP.
- FastAPI `PUT /api/runs/{id}/annotations` thay thế toàn bộ GT trong SQLite và
  `ground_truth.jsonl`, kiểm tra ID/thời gian/trường bicycle/điều kiện;
  `GET /api/runs/{id}/evaluation` chỉ cho run đã duyệt. Module
  `src/parking_web/metrics.py` lúc đầu ghép event với dung sai 500 ms; logic
  này đã được thay bằng giao thời gian và temporal IoU ≥0,30 ở cập nhật trên.
  Không chạy lại model; suggestion vẫn lấy từ artifact gốc. GT web schema là
  `0.9.0`; manifest Step 1 không đổi. Schema `0.7.0` cũ đọc được.
- Giới hạn: GT thêm thủ công hiện chỉ có khoảng thời gian, chưa có box không
  gian; event cùng làn chồng thời gian vẫn có thể chưa rõ danh tính. Bản
  evaluator mới báo số cặp mơ hồ và thêm điểm end-to-end cho OCR/điều kiện.
- Kiểm thử: `PYTHONPATH=src python -m unittest discover -s tests -p
  'test_web*.py' -v`: **3 passed**, gồm thêm GT bỏ sót và recall giảm xuống
  0.5, khóa endpoint trước duyệt, OCR/điều kiện sai. `python -m py_compile`
  ba module web đã sửa: **đạt**. `npm run build`: **đạt** với quyền ghi output
  production, TypeScript và Vite đã cập nhật `frontend/dist`. Toàn bộ
  `PYTHONPATH=src python -m unittest discover -s tests -v`: **37 passed**.

## Kiến trúc đang chạy thực tế

```text
React web (7 trang) ↔ FastAPI REST ↔ SQLite + web_data/
                             ↓
                    local single job worker
                             ↓
Video raw bất biến
  → OpenCV decode một lần
  → lấy mẫu frame theo sample_fps
  → YOLO26s Detect (COCO bicycle/car/motorcycle)
  → ByteTrack (trạng thái riêng cho camera)
  → ROI/corridor + motion gate + EventEngine
  → Segment planner (buffer và gộp khoảng gần nhau)
  → detections.jsonl + clips.jsonl/events.jsonl/run.json
  → materialize từng MP4 tùy chọn (hoặc virtual segment)
  → clip_final.mp4 nối các segment theo timestamp nguồn
  → [tùy chọn] crop đúng track event trên raw → YOLO biển số
  → chọn frame chất lượng → PaddleOCR → plate_observations.jsonl
  → GUI gợi ý plate_text cho HITL và vẽ box biển
  → [tùy chọn] CV đo sáng/độ nét + Qwen3-VL trên frame event
  → đánh giá plate_readable → good hoặc ba nguyên nhân unreadable
  → condition_suggestions.jsonl → GUI gợi ý cho HITL
```

Ground truth được tạo độc lập trên raw trong tab **Kết quả & GT**. Event Model 1
có thể nạp làm gợi ý để người dùng kiểm tra/chỉnh sửa, nhưng evaluator chỉ đọc
GT sau khi người dùng thêm hoặc cập nhật và không truyền GT hay `conditions` vào detector.
Một lần chạy đơn nhận một `CameraConfig`; ngoài ra CLI có `BatchConfig` để
chạy tuần tự nhiều camera/làn với tracker và manifest tách riêng. Vì vậy
`camera_id → lane_id → direction` là ánh xạ một-một đã khai báo sẵn. Ghép một
lượt ENTRY với EXIT và Model 2 adapter chưa nằm trong code hiện tại.

Web local là giao diện chính mới; PyQt vẫn được giữ để tương thích. Web nay
thêm được GT event thủ công bị Model 1 bỏ sót. FastAPI phục vụ React production build,
nhận upload, validate config, tạo job, cung cấp media/result/detection và lưu
GT/review. SQLite cùng `web_data/` là storage local; worker chạy một job nặng
tại một thời điểm, không có Redis/retry/resume.

Kiến trúc mục tiêu mở rộng được mô tả tại
[`kien_truc_cuoi_buoc_1.md`](kien_truc_cuoi_buoc_1.md); các phần chưa có code
được đánh dấu rõ ở đó và bên dưới.

## Đã triển khai (có bằng chứng trong source)

- `frontend/`: React/TypeScript/Vite với sidebar và bảy trang Tổng quan, Kho
  video, Chạy phân tích, Kết quả & duyệt, Đánh giá, Tài liệu, Cài đặt. Trang result mở bằng bảng các run,
  hiển thị trạng thái pipeline/duyệt và nút chỉnh sửa/duyệt. Workspace chỉnh
  sửa riêng có final clip/các clip, bảng event, nút cập nhật GT và video event
  với overlay track. Event preview phát raw video tương thích browser, tua theo
  `event.start_ms` và vẽ box xe/biển trên cùng timeline nguồn. Box biển lấy từ
  `plate_observations.jsonl` của đúng event và hiện màu vàng ở frame gần
  observation; hai box chỉ hiện trong khoảng thời gian event đang chọn.
  Timeline dưới player tô vàng đoạn event trên video raw đầy đủ và cho phép
  tua tới mọi thời điểm. Giao diện ghi rõ nguồn là video raw đầy đủ. Chỉ lưu
  thay đổi GT của run đã duyệt mới chuyển run về `DRAFT`.
  Các page component luôn được mount và chỉ ẩn/hiện theo sidebar, nên đổi
  trang không làm mất config, ROI/line, tiến trình run, event đang chọn hoặc
  nội dung GT chưa lưu. Lựa chọn run từ Tổng quan được đồng bộ sang trang
  Kết quả.
- `src/parking_web/api.py`: FastAPI upload binary, JPEG preview, validation,
  lifecycle run, media sandbox, result/gợi ý, annotation theo lô và duyệt/mở
  lại. Production build được phục vụ tại `/`; API nằm dưới `/api`.
- `src/parking_web/storage.py`: SQLite catalog cho video/run/annotation và
  filesystem `web_data`; cập nhật HITL đồng bộ `ground_truth.jsonl` schema
  `0.7.0`.
- `src/parking_web/jobs.py`: hàng đợi in-process mặc định hai worker, cập nhật progress
  và gọi lõi Step 1; request HTTP không chạy inference trực tiếp.
- `run_web_api.py`: launcher web local ở `127.0.0.1:8000`.

- `src/parking_step1/conditions.py`: nhánh điều kiện tùy chọn, chọn frame theo
  event từ plate artifact hoặc detection, đo CV, chạy Qwen3-VL-2B-Instruct,
  đánh giá khả năng đọc trước rồi mới phân loại ba nguyên nhân và ghi artifact riêng; có thể chạy lại bằng
  `run_conditions.py` hoặc nút trong GUI. Nhánh chạy tuần tự và không sửa GT.
- YOLO/ByteTrack giữ COCO class `1=bicycle`, `2=car`, `3=motorcycle`.
  Bicycle vẫn tạo event/clip nhưng Plate Enrichment và Condition Enrichment
  chỉ ghi record `not_applicable`, không gọi model biển số/OCR/CV/VLM.
- Evaluator yêu cầu cùng `vehicle_type` khi matching và xuất thêm metric
  `by_vehicle_type`. GUI/GT hỗ trợ `bicycle`; trường biển và nguyên nhân được
  khóa, `plate_readable=null`, `condition_status="not_applicable"`.
- GUI có checkbox/model path/frame count, trạng thái `good`/`unreadable` và
  ba nguyên nhân cấp cao. Chọn `good` sẽ xóa/khóa nguyên nhân; chọn unreadable
  bắt buộc ít nhất một nguyên nhân. Bicycle dùng `not_applicable`. GT dùng
  schema `0.6.0`, run writer `0.9.0`.

- `src/parking_step1/plate.py`: enrichment tùy chọn dùng tạm
  `yolov8n-oiv7.pt` (class `Vehicle registration plate`) và
  `latin_PP-OCRv5_mobile_rec`. Detector chỉ nhận crop xe của đúng track event;
  artifact giữ tọa độ box biển trên raw, điểm frame, OCR và consensus.
- `run_plate.py`: chạy enrichment cho run đã có mà không chạy lại YOLO xe.

- `src/parking_step1/config.py`: `CameraConfig` và `RunConfig`, kiểm tra
  direction/ROI/line/line-gate margin, giao cắt hình học line–ROI, lưu và đọc
  JSON. Line hoàn toàn ngoài ROI bị chặn dù corridor có chạm ROI.
- `src/parking_step1/events.py`: `Detection`, ROI anchor, corridor quanh
  crossing line, state machine `CANDIDATE → ACTIVE → LEAVING → CLOSED`, grace
  period, motion gate loại xe đỗ và `plan_segments` với pre/post buffer, merge
  gap. Khi có cả ROI và line, cổng mở là `ROI ∩ corridor`; khi không có line,
  motion gate vẫn bắt buộc trước khi tạo event.
- `src/parking_step1/pipeline.py`: probe video, checksum SHA-256, decode và
  sample theo thời gian nguồn, adapter YOLO + ByteTrack, manifest JSONL,
  artifact `detections.jsonl` theo frame sampled, virtual segment, materialize
  MP4 bằng OpenCV và kiểm tra decode; khi bật MP4 còn nối mọi segment theo
  `start_ms` thành `clips/clip_final.mp4` và ghi bảng ánh xạ timeline.
- `src/parking_step1/gui.py`: giao diện PyQt6 local để chọn raw/output,
  vẽ ROI và line trên frame, chỉnh threshold/model/FPS/buffer, chạy nền có
  progress/hủy, xem event và phát clip ngay trong cửa sổ. Bấm một dòng event
  sẽ mở clip/virtual segment, tua tới đúng thời điểm bắt đầu event và vẽ box,
  lớp, confidence, track ID của YOLO + ByteTrack từ artifact; có nút phát,
  tạm dừng, về đầu và thanh tua riêng. Tab cấu hình giữ video raw ở pane bên
  phải; chạy xong tự chuyển sang tab kết quả. Bảng event và bảng GT chọn theo
  toàn hàng để dễ đối chiếu. Bảng GT hiện hiển thị đầy đủ mọi trường
  annotation/provenance (`source_event_id`, biển số, khả năng đọc, frame đọc
  được, điều kiện, camera/lane/hướng, nguồn nhãn, gợi ý, video raw và schema);
  trường chưa có hiển thị `None`, còn dữ liệu dài có thanh cuộn ngang và
  tooltip.
- Tab ground truth hỗ trợ nạp event làm gợi ý, đánh dấu/chỉnh đầu-cuối,
  frame đọc được, khả năng đọc biển, loại xe, biển số tùy chọn, điều kiện,
  `crossed` (chỉ `True`/`False`), thêm/cập nhật/xóa GT, chọn toàn hàng và
  lưu/mở JSONL. Khi nạp event Model 1, `crossed` được điền sẵn và lưu trong
  `suggestions.crossed` với nguồn `model1_event`; người dùng vẫn có thể sửa.
- `src/parking_step1/evaluation.py`: event recall, precision phát hiện,
  readable retention, false clips/hour và video reduction.
- `src/parking_step1/cli.py`: batch entry point tái lập được; hỗ trợ đọc
  `RunConfig` hoặc tham số dòng lệnh, ROI/line chuẩn hóa và `--no-clips`.
- `src/parking_step1/batch.py`: `BatchConfig` kiểm tra camera/làn không trùng
  và chạy tuần tự nhiều `RunConfig`, giữ tracker state độc lập.
- `run_gui.py` và `run_step1.py`: launcher từ root, không cần tự đặt
  `PYTHONPATH`.
- `camera_batch.example.json`: cấu hình mẫu hai camera, một ENTRY và một
  EXIT, dùng để chạy thử batch.
- Chỉ phát ba lớp `car`, `motorcycle`, `bicycle`; source raw giữ nguyên.

## Đang làm / chưa triển khai

### Đang làm trong pilot

- Benchmark `imgsz`, detector FPS, confidence, grace và buffer theo từng
  camera trên tập validation có GT.
- Kiểm tra khả năng giữ readable opportunity với xe máy nhỏ, ban đêm và
  ngược sáng.

### Chưa triển khai

- Ingest nhiều file thành một timeline logic, xử lý ranh giới file/VFR/mất
  frame và resume job.
- Batch inference song song trên GPU, queue/retry/giám sát tài nguyên.
- Model 2 adapter, OCR chuyên biển số Việt Nam/hiệu chỉnh confidence,
  ghép ENTRY–EXIT và báo cáo lỗi ký tự.
- Annotation UI có plate layout và quy trình review nhiều người; GUI hiện
  nhận khả năng đọc cơ bản, trạng thái `good`/`unreadable` và ba nguyên nhân
  cố định, lưu `suggestions`/nguồn gợi ý và ghi
  `condition_annotation_source: "human"`.
- Ảnh representative frame, database/Parquet và HTML dashboard. Artifact box/
  track dạng JSONL đã có ở mức pilot nhưng chưa có ảnh representative riêng.
- Web chưa có authentication/audit nhiều người, upload chunk/quota, queue
  bền vững/retry, object storage hoặc SSE. SQLite và worker đơn chỉ dành cho
  một máy local.
- Web chưa tạo GT event thủ công khi Model 1 bỏ sót; chức năng này còn ở PyQt.
- Artifact clip vẫn là `mp4v`; bản xem trước H.264 cho browser được tạo theo yêu cầu như cập nhật 24/09 ở đầu tài liệu.
- State frontend chỉ được giữ khi điều hướng trong cùng tab. Reload tab hoặc
  khởi động lại frontend sẽ mất config/ROI/line và các chỉnh sửa GT chưa bấm
  `Cập nhật`; dữ liệu đã lưu vẫn nằm trong SQLite và artifact của run.

## Source code, input/output và cách chạy

Input hiện hỗ trợ một file video OpenCV đọc được (`mp4`, `avi`, `mov`, `mkv`),
camera/làn/chiều, weights YOLO và các tham số trong `RunConfig`.

```powershell
$env:PYTHONPATH = "src"
python -m parking_step1                 # mở GUI
python -m parking_step1.cli --source video_test1.mp4 --output outputs\cam01 `
  --camera-id CAM01 --lane-id ENTRY_01 --direction ENTRY `
  --model yolo26s.pt --imgsz 960 --sample-fps 10
```

Từ root repository có thể dùng trực tiếp `python run_gui.py` hoặc
`python run_step1.py`.

Web production local:

```powershell
cd frontend
npm install
npm run build
cd ..
python run_web_api.py
# mở http://127.0.0.1:8000
```

Development tách BE/FE: chạy `python run_web_api.py`, rồi trong terminal khác
chạy `cd frontend; npm run dev` và mở `http://127.0.0.1:5173`.

Batch nhiều camera/làn:

```powershell
python run_step1.py --batch-config camera_batch.example.json
```

Output của một run là thư mục `step1-<UTC>/` gồm:

- `run.json`: config, source metadata/checksum, số frame và thời gian chạy.
- `events.jsonl`: event dự đoán, track nội bộ, khoảng thời gian raw,
  crossing, confidence, detection đầu tiên và camera/làn/chiều.
- `clips.jsonl`: segment raw có buffer, event_ids, source checksum và trạng
  thái `virtual` hoặc `valid/invalid` sau materialize.
- `detections.jsonl`: các frame detector đã sample và toàn bộ box YOLO +
  ByteTrack (`track_id`, lớp, confidence, tọa độ box) để GUI trực quan hóa.
- `plate_observations.jsonl`: tùy chọn khi bật OCR.
- `condition_suggestions.jsonl`: tùy chọn khi bật CV + VLM; không phải GT.
- `clips/CLIP-*.mp4`: chỉ có khi `make_clips=true`.
- `clips/clip_final.mp4`: chỉ có khi `make_clips=true` và có segment; nối các
  clip theo thời gian raw tăng dần, bỏ khoảng trống giữa clip.

`schema_version` hiện là `0.9.0`. GUI vẫn mở được manifest `0.1.0`/`0.2.0`
cũ, nhưng overlay YOLO + ByteTrack cần run mới có `detections.jsonl`. Các
timestamp `start_ms/end_ms` trong
manifest là timestamp trên video nguồn; `clip_uri` là đường dẫn tương đối
trong run khi file MP4 được tạo. `run.json.artifacts.final_clip` chứa URI,
checksum, QC, tổng frame/thời lượng và `timeline_mapping` từ offset final về
`clip_id` cùng timestamp raw; giá trị là `null` nếu không xuất MP4 hoặc không
có segment.

## Dependency và cấu hình quan trọng

- `requirements.txt`: OpenCV, NumPy, PyQt6, `ultralytics` và `lap` (tracker).
- Web backend thêm FastAPI `>=0.115` và Uvicorn `>=0.34`; frontend dùng Node
  22, React, Vite và TypeScript ghim `5.7.3` vì bản TypeScript latest thử trên
  Windows đã crash nội bộ khi build.
- `requirements-conditions.txt`: PyTorch, Transformers, Accelerate và
  Hugging Face Hub; weights Qwen3-VL-2B-Instruct nằm trong `models/` và bị
  gitignore. Cài từ file này rồi `hf download ...` như README.
- Model pilot mặc định: `yolo26s.pt`, `imgsz=960`, detector `10 FPS`,
  confidence `0.12`, `candidate_hits=2`, motion distance `0.015` trong cửa
  sổ `1.5 s`, line gate margin `0.12`, grace `1.5 s`, buffer trước `1.5 s`,
  sau `2 s`.
- Máy hiện tại chạy CPU (`torch.cuda.is_available() == False`); GPU CUDA sẽ
  được Ultralytics tự chọn nếu có.

## Kiểm thử và bằng chứng đã chạy

- `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; python -m
  pytest -q tests`: **36 passed**. Hai test web tích hợp dùng SQLite/video tạm,
  bao phủ upload/probe/frame preview/dashboard, config line–ROI invalid/valid,
  result ghép event–clip, lưu `ground_truth.jsonl`, duyệt và khóa annotation.
- `cd frontend; npm run build`: **OK**, TypeScript type-check và Vite production
  build 1.878 module; JS 253.74 kB (gzip 79.07 kB), CSS 11.00 kB.
- `python -m py_compile src\parking_web\storage.py src\parking_web\jobs.py
  src\parking_web\api.py tests\test_web_api.py run_web_api.py`: **OK**.
- Smoke thật `python run_web_api.py`: Uvicorn chạy ở `127.0.0.1:8000`, health
  và dashboard trả HTTP 200. Kiểm tra bằng browser xác nhận dashboard, sidebar
  bốn trang, form cấu hình/event/motion/enrichment và workspace result render.
- Kiểm tra browser trên `http://127.0.0.1:8000`: đổi Camera ID ở trang Chạy
  phân tích, chuyển sang Tổng quan rồi quay lại; giá trị vẫn được giữ. Sau
  kiểm tra đã trả Camera ID về `CAM01`: **OK**.
- Kiểm tra browser sau build xác nhận trang Kết quả mở màn hình bảng run mới,
  có empty state đúng khi database chưa có run và không còn combobox chọn run:
  **OK**. API duyệt/lưu/mở lại tiếp tục được bao phủ bởi test tích hợp.
- Chẩn đoán run `WEB-29A673FD2A`: raw video là H.264, clip/final do OpenCV
  tạo là `FMP4`, nguyên nhân browser báo thời lượng `0:00`. Sau khi preview
  chuyển sang raw, browser báo `readyState=4`, video `3060×1664`, thời lượng
  `17.3953 s`; chọn `EVT-000003` tua đúng `9.831 s` và canvas overlay có kích
  thước hiển thị `617×334`: **OK**.
- Test API result với fixture biển số xác nhận `plate_observations` được gắn
  đúng event; bộ test đầy đủ **36 passed**. TestClient trên run thật
  `WEB-29A673FD2A` trả HTTP 200, bốn event có lần lượt 26/18/14/20
  observations với tọa độ `plate_box` theo video raw: **OK**.
- Browser smoke ở backend local cổng 8001 với run trên: Event Preview hiện
  nhãn video raw, box xe xanh và box biển vàng đúng vị trí biển trên frame
  đầu. Sau khi căn canvas theo `video.offsetTop/offsetLeft`, hai box khớp
  phần hình video trong player có viền đen: **OK**.
- Browser smoke với `EVT-000001` (0–4132 ms): tua đến 5000 ms, không còn box
  xe/biển; tua về 2000 ms, cả hai box xuất hiện. Timeline có dải vàng từ
  0 đến 4.13 s trên tổng 17.40 s và con trỏ ở đúng 5.00/2.00 s: **OK**.

- Smoke test adapter thật trên frame đầu `video_test1.mp4`, `imgsz=960`,
  confidence `0.12`: **OK**, ByteTrack trả 7 `car`, 3.362 giây trên CPU;
  không có bicycle trong video này. Weights xác nhận class map
  `{1: bicycle, 2: car, 3: motorcycle}`. Vì dữ liệu hiện chưa có bicycle,
  chưa thể kết luận recall/confidence tối ưu cho xe đạp; cấu hình 10 FPS và
  0.12 được giữ làm pilot, cần benchmark khi có mẫu thật.
- Benchmark bổ sung trên 20 frame đầu, `imgsz=960`: confidence `0.08`, `0.12`,
  `0.20` đều trả 7 car và 0 bicycle/motorcycle ở frame đầu; thời gian lần lượt
  1.625/0.367/0.257 giây (lần đầu gồm warm-up nên không dùng để so sánh tốc
  độ ngưỡng). ByteTrack ở nhịp mô phỏng 10 FPS (7 frame) và 5 FPS (4 frame)
  đều duy trì 7 track car, không có track bicycle; thời gian 1.397 và 0.712
  giây. Bằng chứng này xác nhận adapter/class filter/tracker chạy được, không
  chứng minh chất lượng bicycle vì source không có xe đạp.

- PowerShell `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src';
  python -m pytest -q tests`: **34 passed**. Bao phủ parser JSON VLM,
  fallback từ detection, artifact theo event, GT không bị ghi đè, prefill
  trạng thái đọc được/nguyên nhân trong GUI, OCR rõ buộc trạng thái `good`,
  và final clip tự sắp hai segment đảo thứ tự theo timestamp nguồn, có thể
  decode và có đúng thứ tự nội dung. Test motion gate xác nhận xe đứng yên bị
  loại ở toàn frame/chỉ ROI/ROI + line; xe đã di chuyển rồi dừng vẫn giữ một
  event; ROI + line chỉ mở track trong phần giao với corridor. Validation
  hình học bao phủ line nằm trong ROI, cắt ROI, chạm biên và line hoàn toàn
  ngoài ROI bị từ chối; GUI cảnh báo và xóa line sai ngay sau khi vẽ.
  Vô hiệu hóa plugin pytest bên thứ ba vì
  `pytest_isolate` hiện cài trong Python Windows cần `fcntl` của Unix.
- Các test bicycle bao phủ event/detection manifest, evaluator matching theo
  lớp, GUI GT `not_applicable`, Plate Enrichment không gọi detector/OCR và
  Condition Enrichment không gọi CV/VLM: **OK**.
- `python -m py_compile src/parking_step1/conditions.py
  src/parking_step1/gui.py run_conditions.py`: **OK**.
- Đã tải Qwen3-VL-2B-Instruct vào `models/Qwen3-VL-2B-Instruct` (weights
  4.255 GB, không commit). Đã nạp model và chạy `QwenConditionVLM.analyze`
  thật trên ảnh synthetic bằng PyTorch CPU: trả về object JSON hợp lệ sau
  parse. Đây là smoke test nạp/sinh đáp án, chưa đo độ chính xác điều kiện.
- `python run_conditions.py outputs/step1-20260917T110741785303Z` trên raw
  `video_test1.mp4`: **OK**, 4 event được ghi vào
  `condition_suggestions.jsonl`; `run.json` tham chiếu artifact và dùng
  schema cũ `0.5.0`. Kết quả này là bằng chứng dẫn tới schema mới: đánh giá
  khả năng đọc trước, chỉ phân loại nguyên nhân khi không đọc được. Run sẽ
  được chạy lại bên dưới bằng artifact schema `0.2.0`/run `0.6.0`.
- Chạy lại cùng lệnh sau khi thu gọn schema: **OK**, 4/4 event có
  `plate_readable=true`, `condition_status="good"`, `conditions=[]`; phản hồi
  Qwen cũng trả readable và không đưa nguyên nhân. `run.json` là `0.6.0`.
  Kiểm tra GUI offscreen nạp đủ 4 record; event đầu điền `good`, boolean
  readable, danh sách nguyên nhân rỗng và `plate_readability` là
  `multi_frame_readable`: **OK**.

- `python -m unittest discover -s tests -v`: **12/12 OK**. Bao phủ config
  round-trip, crossing/state machine, merge planner, evaluator denominator,
  clip MP4 synthetic có thể decode, overlay detection và chọn toàn hàng trong
  GUI.
- PowerShell `$files = Get-ChildItem src\parking_step1 -Filter '*.py' | ForEach-Object { $_.FullName }; python -m py_compile $files tests\test_step1.py tests\test_gui_playback.py run_gui.py run_step1.py`:
  **OK**.
- Khởi tạo GUI offscreen với `QT_QPA_PLATFORM=offscreen`: **OK**, tiêu đề
  `Parking Video — Bước 1`.
- Nạp `yolo26s.pt` và infer một frame `video_test1.mp4` ở `imgsz=320`: **OK**,
  7 detection `car`, khoảng 2.4 s/frame trên CPU.
- Chạy smoke thật (**OK**, 522 frame nguồn, 9 frame detector, 11 event, 1
  virtual segment; đây là smoke test chức năng, chưa phải benchmark chất
  lượng):

  ```powershell
  $env:PYTHONPATH = "src"
  python -m parking_step1.cli --source video_test1.mp4 --output outputs\real_smoke `
    --camera-id CAM01 --lane-id ENTRY_01 --direction ENTRY --model yolo26s.pt `
    --imgsz 320 --sample-fps 0.5 --no-clips --print-json
  ```
- Chạy batch mẫu `python run_step1.py --batch-config
  camera_batch.example.json`: **OK**, 2 camera (ENTRY/EXIT) chạy tuần tự,
  tổng 22 event và 2 virtual segment.
- Chạy lại video thật với `imgsz=960`, `10 FPS`, line gate margin `0.12`:
  **OK**, run `outputs\\fixed_run\\step1-20260917T040252636898Z` ghi nhận
  đúng **4 event**, trong đó **3 event crossed**, và chỉ tạo 1 virtual
  segment bao phủ 17.395 giây nguồn.
- Chạy lại sau khi bổ sung artifact trực quan hóa:
  `outputs\\gui_overlay_run\\step1-20260917T042321231139Z` (**schema
  `0.3.0`**) ghi nhận **4 event/3 crossed**, `detections.jsonl` có 174 frame
  sampled, và `CLIP-000001.mp4` có 522 frame, `quality_status=valid`.
- Đối chiếu run trước `outputs\\step1-20260917T034556223596Z`: run này có
  `crossing_line` nhưng `roi=[]`, nên EventEngine nhận cả detection xe nền và
  ghi **31 event**. Sau khi bật corridor gate quanh line với margin `0.12`,
  cùng video/model/tham số detector cho kết quả 4 event/3 crossed như trên.
- Test GUI playback: **OK**, chọn event tại `400 ms` mở MP4 nhúng và tua đúng
  vị trí (sai số tối đa một frame), đồng thời đọc artifact và nhận đúng box
  track được highlight ở frame đầu event.
- Test bảng GT đầy đủ trường: **OK**, kiểm tra toàn bộ cột annotation/provenance
  và giá trị `None` cho bản ghi thiếu trường.
- Chạy smoke thật có crossing line `--crossing-line "0.5,0.1;0.5,0.9"`:
  **OK**, run `outputs\\line_smoke\\step1-20260917T034308189081Z` ghi nhận 2
  event có `crossed=true` (`crossing_ms=4032` và `16029`).

## Hạn chế và giả định đã biết

- `video_info` và materializer giả định constant-frame-rate; VFR cần timeline
  index riêng trước khi dùng production.
- Tracker chỉ được cập nhật ở các frame đã sample; cấu hình FPS quá thấp có
  thể tạo duplicate event hoặc mất crossing.
- `imgsz=960` trên CPU rất chậm; cần benchmark trên GPU/thiết bị triển khai.
- Qwen3-VL-2B trên CPU chậm và có thể gợi ý quá mức; ngưỡng CV và quy tắc
  OCR-readability chưa được hiệu chỉnh với bộ GT. `vlm_result` là bằng
  chứng tham khảo cho HITL, không phải nhãn đúng/sai đã xác nhận.
- MP4 materialize dùng codec `mp4v` của OpenCV, không giữ audio và có thể cần
  thay codec theo consumer Model 2.
- Trình phát nhúng dùng OpenCV/QTimer nên phù hợp xem và kiểm tra event; chưa
  phải player âm thanh/codec chuyên dụng.
- ROI để trống và không có crossing line nghĩa là toàn frame; crossing line để
  trống thì event vẫn được tạo theo presence nhưng `crossed=false`.
- Khi có crossing line, track mới chỉ mở event nếu anchor nằm trong corridor
  quanh line (`line_gate_margin`, mặc định `0.12`); có ROI thì phải đồng thời
  nằm trong ROI. Sau khi đã mở, track vẫn được cập nhật khi rời corridor để
  giữ đủ thời lượng event. Margin quá nhỏ có thể bỏ xe thật; margin quá lớn
  có thể giữ lại xe nền.
- Ngưỡng motion `0.015/1.5 s` mới được smoke test trên một video. Camera rung,
  box jitter lớn hoặc xe bò rất chậm có thể cần hiệu chỉnh bằng GT: ngưỡng quá
  thấp giữ xe đỗ, quá cao làm mất xe chạy chậm.
- Weights `*.pt`, cache và `outputs/` bị gitignore; phải quản lý weights theo
  chính sách license Ultralytics (AGPL/Enterprise) của sản phẩm.

## Thay đổi gần nhất

- Giới hạn overlay xe và biển số trong thời gian event đang chọn; khi tua ra
  ngoài khoảng đó, canvas được xóa ngay. Thêm thanh timeline raw tô vàng
  khoảng event và cho phép tua video.

- Bổ sung overlay box biển số màu vàng vào Event Preview từ artifact Plate
  Enrichment, đồng bộ bằng `timestamp_ms` raw và giới hạn sai lệch 150 ms.
  Player ghi rõ đang phát video raw đầy đủ; `Video final` vẫn là artifact riêng.

- Sửa Event Preview không phát được MP4 `FMP4/mp4v`: player nay dùng raw video
  H.264, tua trực tiếp theo timestamp event và dùng cùng raw timeline để vẽ
  YOLO + ByteTrack. Run cũ dùng được ngay, không cần chạy lại pipeline.

- Đổi flow Kết quả & duyệt thành bảng danh sách run có trạng thái và thao tác
  `Chỉnh sửa`/`Duyệt`. Chỉnh sửa mở workspace event + trực quan trong cùng
  trang, có nút quay lại và `Cập nhật` ở cuối; duyệt thực hiện trực tiếp từ
  danh sách. Cơ chế reopen trước khi mở workspace của bản này đã được thay bằng
  chuyển `DRAFT` khi lưu thay đổi thực, như cập nhật ở đầu tài liệu.

- Sửa điều hướng web làm mất trạng thái: bốn page React nay luôn được mount
  và chỉ ẩn/hiện, đồng thời lựa chọn run từ Tổng quan được đồng bộ vào trang
  Kết quả. Đã xác nhận bằng browser và production build; thay đổi chỉ giữ
  state trong vòng đời tab, chưa thêm persistence qua reload.

- Thêm web local BE/FE: React sidebar bốn trang; FastAPI + SQLite/filesystem +
  worker đơn; upload/config/run/progress/result/media/GT/review đầy đủ cho flow
  event dự đoán. Thêm `docs/kien_truc_web_local.md`, launcher
  `run_web_api.py`, dependencies và test tích hợp. GT web dùng schema `0.7.0`.

- Thêm validation line–ROI: nếu có cả hai, line phải nằm trong, cắt hoặc chạm
  biên ROI. Line hoàn toàn ngoài ROI bị `CameraConfig.validate()` từ chối,
  không xét corridor; GUI cảnh báo và xóa line sai ngay sau điểm vẽ thứ hai,
  đồng thời vẫn chặn config sai khi chạy/lưu/mở. Test toàn bộ: **34 passed**;
  pycompile config/GUI/test: **OK**.

- Sửa false positive xe đỗ: `candidate_hits` không còn đủ để tạo event.
  Candidate phải dịch chuyển anchor qua `min_motion_distance` trong
  `motion_window_seconds`. Khi có line, corridor luôn là cổng mở; nếu có ROI
  thì dùng `ROI ∩ corridor`. GUI/CLI đã có hai tham số motion mới; event ghi
  `motion_confirmed`/`motion_distance`; run schema tăng lên `0.9.0`.
- Chạy thật lại cấu hình ROI + line cũ trên `video_test1.mp4`, YOLO26s,
  `imgsz=960`, 10 FPS: run cũ có **8 event**; chỉ thêm motion gate còn **7**;
  sau khi sửa `ROI ∩ corridor` còn đúng **4 event**, tại
  `outputs/motion_gate_validation/step1-20260922T115605161200Z`. Run dùng
  virtual segment để tập trung kiểm tra EventEngine, 522 frame nguồn/174
  frame sampled, schema `0.9.0`.
- `python -m py_compile` các module cấu hình/event/pipeline/GUI/CLI: **OK**;
  toàn bộ pytest: **32 passed**.

- Thêm `clips/clip_final.mp4`: khi bật xuất MP4, pipeline nối toàn bộ segment
  theo `start_ms` nguồn. `run.json.artifacts.final_clip.timeline_mapping`
  bảo toàn ánh xạ giữa timeline đã bỏ khoảng trống và raw video. Run schema
  tăng từ `0.7.0` lên `0.8.0` tại thay đổi đó (hiện tại `0.9.0`); GUI/CLI ghi rõ `--no-clips` cũng tắt output này.
- Kiểm tra `python -m py_compile src\parking_step1\pipeline.py
  src\parking_step1\gui.py src\parking_step1\cli.py tests\test_step1.py`:
  **OK**; toàn bộ pytest: **29 passed**.

- Thêm bicycle xuyên suốt detector → ByteTrack → event/clip → GUI/GT →
  evaluator. Nhánh biển số và điều kiện bỏ qua bicycle, ghi rõ
  `not_applicable`. Run schema tại thay đổi đó là `0.7.0` (hiện tại `0.9.0`), Plate artifact `0.2.0`, Condition
  artifact `0.3.0`, GT `0.6.0`.

- Sửa lỗi GUI khi bật đồng thời PaddleOCR và Qwen:
  `numpy.dtype size changed, Expected 96 ... got 88`. Nguyên nhân là PaddleX
  import Transformers trước, sau đó AutoProcessor thử nạp TensorFlow/h5py có
  ABI khác NumPy 2.3.5. `plate.py` và `conditions.py` nay vô hiệu hóa backend
  TensorFlow trước import; pipeline vẫn dùng PaddlePaddle cho OCR và PyTorch
  cho Qwen.

- Thu gọn nhánh điều kiện: quyết định `good`/`unreadable` trước; chỉ khi
  unreadable mới chọn `capture_blur`, `plate_obstruction`, `lighting_issue`.
  Loại bỏ toàn bộ detail khỏi artifact và GUI; artifact tăng `0.2.0`, run tăng
  `0.6.0`, GT tăng `0.5.0` tại thay đổi đó; phiên bản hiện tại cao hơn do
  bổ sung bicycle.

- Thêm pipeline Bước 1, EventEngine, evaluator, CLI, GUI, tests và manifest
  writer.
- Bổ sung dependency `lap` để ByteTrack chạy thực tế.
- Thêm `BatchConfig`/`run_batch` để chạy tuần tự nhiều camera/làn với state
  tracker tách biệt.
- Sửa over-detection khi chỉ vẽ crossing line: thêm line corridor gate và
  nâng schema output lên `0.2.0`.
- Ghi `detections.jsonl` và `first_detection`/`track_artifact_uri` để GUI vẽ
  detection YOLO + ByteTrack ở frame đầu và trong lúc phát clip; schema tại
  thời điểm thêm Plate Enrichment là `0.4.0` (hiện tại `0.9.0`).
- Đổi bảng event/GT sang chọn và highlight toàn hàng khi người dùng bấm vào
  một dòng.
- Đổi flow GT: chọn event tự nạp thời gian/loại xe/`crossed` làm gợi ý, đánh
  dấu thời gian theo clip hoặc raw, hỗ trợ `Thêm GT`/`Cập nhật GT`, khả năng
  đọc biển và block `suggestions` để mở rộng cho detector/OCR/VLM sau này.
- Mở rộng bảng GT từ 4 cột cơ bản lên toàn bộ trường annotation/provenance,
  hiển thị rõ `None` cho dữ liệu chưa có và thêm cuộn ngang cho trường dài.
- Bổ sung trường HITL `crossed` vào form/bảng GT; giá trị chỉ là boolean
  `True`/`False`, tự nạp từ `event.crossed` và ghi provenance trong
  `suggestions.crossed`. GT schema tăng lên `annotation_schema_version: "0.3.0"`;
  record schema `0.2.0` cũ khi mở được mặc định hiển thị `False`.
- Bổ sung điều kiện GT và nguồn nhãn human; flow hiện đã thay bằng
  `good`/`unreadable` cùng ba nguyên nhân cấp cao.
- Lọc cứng class detector ngoài `car`/`motorcycle` trước khi tạo `Detection`.
- Thay mở clip ngoài ứng dụng bằng trình phát nhúng; event click/double-click
  tua tới event start và hỗ trợ cả MP4 lẫn virtual segment trên raw.
- Bổ sung kiểm tra line cấu hình và bảo đảm event ngắn vẫn tạo được MP4 có ít
  nhất một frame khi materialize.
- Cập nhật README và tài liệu này để mô tả đúng code chạy được, đồng thời
  phân biệt pilot hiện tại với kiến trúc mở rộng mục tiêu.

## Cập nhật 18/09/2026: Plate Enrichment

- CLI `python run_step1.py --source ... --output ... --plate-ocr` và checkbox
  trong GUI bật nhánh biển số sau EventEngine. `python run_plate.py <run_dir>`
  áp dụng cho run cũ. Dependency tùy chọn đã được cài bằng
  `python -m pip install -r requirements-plate.txt` trong Python 3.12;
  weights `yolov8n-oiv7.pt` (6.9 MB) đã tải vào root và OCR model đã tải vào
  cache PaddleX. Mặc định nhánh này tắt để Step 1 cũ vẫn chạy độc lập.
- Output thêm `plate_observations.jsonl` và tham chiếu trong `run.json`.
  `events.jsonl`/`clips.jsonl`/`run.json` lúc đó dùng schema `0.4.0`; GT lúc
  đó là `annotation_schema_version: 0.3.0` (hiện tại lần lượt `0.9.0` và
  `0.6.0`). GUI vẽ box biển màu vàng tại frame có
  quan sát và nạp consensus vào ô biển số cùng provenance `plate_ocr`.
- Đã chạy `python -m unittest discover -s tests -v` với `PYTHONPATH=src`:
  16 bài test, gồm tích hợp enrichment trên video nhỏ bằng detector/OCR giả,
  GUI prefill biển số và overlay giữ box khi tua, đều đạt.
- Đã chạy inference thật bằng `python run_plate.py
  outputs/step1-20260917T110741785303Z`. Run có 4 event, artifact có 4 dòng;
  lần lượt tạo 26/18/14/20 candidate, chọn 5/5/5/3 frame và consensus là
  `ZPN720`, `HT1748`, `MLZ106`, `BSA788`. Đây là smoke test trên video hiện
  có, chưa phải đánh giá độ chính xác trên bộ GT lớn. Nhánh VLM điều kiện là
  thành phần khác, không thay đổi luật
  hậu xử lý biển số Việt Nam; consensus confidence là tỷ phần phiếu, không
  được hiệu chỉnh.
- Sửa overlay khi tua clip: track của event đang chọn dùng detection gần nhất
  trong toàn khoảng event, nên box xe và box biển không bị mất giữa các frame
  detector đã sample; không giữ box sang buffer ngoài event.
