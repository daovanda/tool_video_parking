# Hướng dẫn làm việc trong repository

## Phạm vi áp dụng

File này áp dụng cho toàn bộ repository. Mọi agent hoặc người thực hiện thay đổi code trong repository phải tuân thủ các yêu cầu tài liệu bên dưới.

## Mục tiêu của repository

Repository xây dựng tool xử lý và đánh giá video bãi xe nhiều làn:

1. Bước 1 đọc video raw theo camera/làn, phát hiện và theo dõi xe, tạo event và các đoạn video cần giữ.
2. Bước 2 chạy model nhận diện của bên dev, đối chiếu ground truth và tạo báo cáo metric/lỗi.
3. Mỗi làn có chiều cố định `ENTRY` hoặc `EXIT`; xe có thể vào bằng bất kỳ làn vào nào và ra bằng bất kỳ làn ra nào.
4. Phạm vi hiện tại có ba lớp phương tiện: `car`, `motorcycle`, `bicycle`;
   các nhánh biển số/OCR/điều kiện không áp dụng cho `bicycle`.
5. Mỗi làn hiện có đúng một camera và mỗi camera ánh xạ đúng một làn; `lane_id` và `direction` được khai báo sẵn trong cấu hình camera.

## Tài liệu nguồn trong `docs`

Trước khi sửa code, phải đọc các tài liệu liên quan:

- `docs/kien_truc_cuoi_buoc_1.md`: kiến trúc hiện tại và ranh giới trách nhiệm của bước 1.
- `docs/dac_ta_buoc_1_cat_video.md`: hành vi, module, ground truth và metric của bước 1.
- `docs/dinh_dang_dau_ra_buoc_1.md`: định dạng clip, event, manifest và ground truth.
- `docs/nghien_cuu_va_de_xuat_danh_gia.md`: cơ sở nghiên cứu và bộ metric đánh giá.
- `docs/trang_thai_trien_khai.md`: trạng thái code thực tế, phần đã làm, chưa làm, cách chạy và bằng chứng kiểm thử.

Nếu code và tài liệu mô tả trạng thái triển khai khác nhau, phải kiểm tra code/test để xác định trạng thái thực tế rồi sửa tài liệu ngay trong cùng thay đổi. Không âm thầm coi phần thiết kế dự kiến là chức năng đã triển khai.

## Quy tắc bắt buộc khi thay đổi code

Mọi thay đổi code có ảnh hưởng đến hành vi, kiến trúc, dữ liệu, cấu hình, CLI/API, dependency hoặc cách vận hành đều phải cập nhật tài liệu tương ứng trong cùng lượt làm việc.

Sau khi code, phải thực hiện đủ các bước:

1. Xem diff và xác định thành phần/hành vi nào đã thay đổi.
2. Cập nhật `docs/trang_thai_trien_khai.md` để ghi đúng phần vừa hoàn thành.
3. Cập nhật tài liệu kiến trúc nếu module, luồng dữ liệu, dependency hoặc ranh giới trách nhiệm thay đổi.
4. Cập nhật đặc tả hoặc schema nếu input/output, field, trạng thái hoặc quy tắc xử lý thay đổi.
5. Ghi lệnh kiểm thử đã chạy và kết quả trong phần trạng thái triển khai.
6. Rà lại tài liệu để bảo đảm không tuyên bố chức năng chưa có trong code.

Không được kết thúc task code với lý do “sẽ cập nhật docs sau”. Code và tài liệu tương ứng là một deliverable duy nhất.

Thay đổi chỉ sửa chính tả/comment và không ảnh hưởng hành vi có thể chỉ ghi ngắn trong tài liệu bị sửa; không cần thay đổi sơ đồ kiến trúc. Tuy nhiên, nếu tài liệu hiện tại đã sai so với code thì vẫn phải sửa.

## Tài liệu nào cần cập nhật

| Loại thay đổi code | Tài liệu bắt buộc xem xét/cập nhật |
|---|---|
| Thêm/sửa module, service, worker, queue, storage hoặc luồng dữ liệu | `docs/kien_truc_cuoi_buoc_1.md` và `docs/trang_thai_trien_khai.md` |
| Sửa detector, tracker, ROI, state machine, buffer hoặc logic tạo event/clip | `docs/dac_ta_buoc_1_cat_video.md`, tài liệu kiến trúc và trạng thái triển khai |
| Thêm/sửa JSON, JSONL, CSV, database schema, field, enum hoặc version | `docs/dinh_dang_dau_ra_buoc_1.md` và trạng thái triển khai |
| Sửa matching, metric, ground truth, error analysis hoặc report | `docs/nghien_cuu_va_de_xuat_danh_gia.md` và trạng thái triển khai |
| Sửa CLI, API, cấu hình, biến môi trường hoặc cách chạy | `docs/trang_thai_trien_khai.md`; tạo/cập nhật hướng dẫn vận hành nếu cần |
| Thêm/sửa test hoặc cách xác minh | Phần kiểm thử trong `docs/trang_thai_trien_khai.md` |
| Thay đổi dependency/runtime/phần cứng yêu cầu | Kiến trúc, trạng thái triển khai và hướng dẫn cài đặt liên quan |

Một thay đổi có thể phải cập nhật nhiều tài liệu.

## Nội dung bắt buộc trong tài liệu trạng thái triển khai

`docs/trang_thai_trien_khai.md` phải phản ánh code hiện tại và có ít nhất:

- Ngày cập nhật và phạm vi phiên bản/run liên quan.
- Kiến trúc đang chạy thực tế, kèm sơ đồ hoặc luồng chữ ngắn.
- Danh sách **đã triển khai**, chỉ gồm chức năng có bằng chứng trong code.
- Danh sách **đang làm** và **chưa triển khai**.
- Đường dẫn tới module/file chính.
- Input/output hiện đang hỗ trợ.
- Cách chạy hoặc command entry point hiện tại.
- Cấu hình và dependency quan trọng.
- Test/validation đã chạy, command và kết quả.
- Hạn chế, giả định và lỗi đã biết.
- Thay đổi gần nhất có ảnh hưởng hành vi/kiến trúc.

Không dùng các câu chung như “đã hoàn thành pipeline” nếu mới chỉ có một phần. Nêu chính xác module nào hoạt động và phần nào chưa có.

## Quy tắc mô tả kiến trúc

Tài liệu kiến trúc phải mô tả **kiến trúc hiện tại** trước, sau đó mới được có mục kiến trúc mục tiêu hoặc kế hoạch. Hai trạng thái phải được ghi nhãn rõ ràng:

- `Hiện đã triển khai`.
- `Thiết kế mục tiêu/chưa triển khai`.

Khi thay đổi kiến trúc, phải cập nhật:

- Thành phần và trách nhiệm.
- Luồng dữ liệu giữa các thành phần.
- Điểm lưu trữ và định dạng dữ liệu.
- Đồng bộ/thứ tự xử lý, queue hoặc retry nếu có.
- Ranh giới bước 1, Model 2 và evaluator.
- Lý do của thay đổi và ảnh hưởng tương thích.

Ưu tiên Mermaid hoặc sơ đồ chữ nhỏ, dễ cập nhật. Không giữ sơ đồ cũ nếu không còn đúng.

## Các bất biến thiết kế cần bảo toàn

Chỉ thay đổi các bất biến này khi có lý do rõ ràng và cập nhật toàn bộ tài liệu liên quan:

- Raw video là nguồn dữ liệu bất biến trong một lần đánh giá.
- Timeline của clip/event phải truy ngược được tới camera và video nguồn.
- `clip` là đoạn video vật lý hoặc ảo; `event` là một lượt xe. Một clip có thể chứa nhiều event.
- Mỗi event có `camera_id`, `lane_id` và `direction` rõ ràng.
- `camera_id → lane_id → direction` là ánh xạ cấu hình một-một trong phạm vi hiện tại; Model 1 không suy luận ENTRY/EXIT.
- Detector bước 1 hiện chỉ phát ba lớp `car`, `motorcycle`, `bicycle`.
- `bicycle` vẫn tạo event/clip nhưng Plate/Condition Enrichment phải bỏ qua
  và ghi trạng thái `not_applicable`, không đánh giá là `unreadable`.
- Bước 1 xử lý từng camera/làn; ghép lượt vào–ra thuộc module khác.
- Ground truth được tạo độc lập trên raw video và phải bao gồm event Model 1 bỏ sót.
- Không truyền ground truth, `conditions` do người gán hoặc kết quả đúng/sai vào input Model 2.
- Điều kiện như `night`, `glare`, `dirty` gắn với event và phải ghi nguồn nhãn.
- Ưu tiên virtual segment; chỉ materialize MP4 khi consumer cần.
- Detector có thể chạy FPS thấp hơn, nhưng video giao Model 2 không tự động bị giảm FPS/độ phân giải.
- Mọi thay đổi schema phải tăng `schema_version` phù hợp và mô tả tương thích/migration.

## Kiểm thử và bằng chứng

- Chạy test phù hợp với phạm vi thay đổi.
- Với schema/example JSON, phải parse hoặc validate được.
- Với video pipeline, kiểm tra ít nhất thời lượng, timestamp mapping, khả năng decode và trường hợp ranh giới file liên quan.
- Với metric, thêm ví dụ có kết quả tính tay hoặc fixture đủ để chứng minh mẫu số/tử số đúng.
- Không ghi “đã kiểm thử” nếu chỉ đọc code hoặc chưa chạy command.
- Nếu môi trường không cho chạy test, ghi rõ test chưa chạy, nguyên nhân và phần rủi ro còn lại trong `docs/trang_thai_trien_khai.md`.

## Definition of Done cho task code

Một task code chỉ được coi là hoàn thành khi:

- Code đáp ứng yêu cầu và không để lỗi đã biết chưa được nêu.
- Test/validation phù hợp đã chạy hoặc hạn chế kiểm thử được ghi rõ.
- Tài liệu tương ứng đã cập nhật theo code thực tế.
- `docs/trang_thai_trien_khai.md` nêu rõ đã làm gì và kiến trúc hiện tại.
- Ví dụ/config/schema liên quan còn hợp lệ.
- Phần chưa triển khai được ghi rõ, không trình bày như đã hoàn thành.
