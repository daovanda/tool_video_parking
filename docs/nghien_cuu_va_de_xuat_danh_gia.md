# Nghiên cứu và đề xuất đánh giá tool video bãi xe

## Web local: phần 4 Chi phí xử lý (cập nhật 25/09/2026)

Trang chi tiết Đánh giá hiện chi phí xử lý run tạo gợi ý, đơn vị giây hoặc
phút–giây. Artifact `runtime.json` giữ thời gian wall-clock từng chặng; API
trừ thời gian nạp detector/model trong profile để tính ba thời gian xử lý và
tổng xử lý hiển thị. Thời gian đọc/giải mã raw, suy luận và xuất clip vẫn được
tính. Run cũ không có profile nạp model hiện `—` thay vì ước lượng. Không
dùng `runs.updated_at - runs.created_at`: thời gian chờ queue và thao tác
review có thể làm sai lệch. Đây là metric vận hành, không so với GT và
chưa gồm chi phí GPU/tiền điện hay dung lượng lưu trữ. Bốn ô hiển thị thời gian
phát hiện/cắt clip, OCR, CV–VLM, và **tổng xử lý / thời lượng video raw**.
Ô cuối là tỷ số `T_processing / T_raw`; ví dụ 2× nghĩa là xử lý (sau khi trừ
nạp model) mất thời gian gấp đôi độ dài video. Run thiếu profile hoặc nhánh
chưa đo hiện `—`, không coi
thời gian của nhánh bằng 0. Tổng có thể lớn hơn tổng ba chặng vì có overhead
điều phối/ghi artifact. Các trường wall-clock gốc vẫn lưu nguyên trong
`runtime.json` để chẩn đoán.

## Web local: metric trên GT đã duyệt (đã triển khai 23/09/2026)

Trang **Đánh giá** chỉ đọc run `REVIEWED`. GT cuối cùng gồm nhãn gắn event
model còn hợp lệ và GT thêm thủ công cho lượt xe model bỏ sót; event bị người
duyệt xóa luôn là FP, không được dùng để ghép với GT khác. GT thủ công
`GT-xxxxxx` luôn là FN của bước phát hiện. Nhãn GT có `source_event_id` chỉ
được ghép với đúng event nguồn; nhãn độc lập khác được ghép toàn cục bằng
Hungarian theo cùng camera/làn/chiều và temporal IoU theo ngưỡng cài đặt
(mặc định **≥0,30**), bắt buộc có
giao thời gian. Không còn ghép hai khoảng chỉ cách nhau ≤500 ms nhưng không
giao nhau. Cặp không gắn nguồn và có nhiều khả năng ghép gần ngang nhau
(chênh IoU ≤0,05) không dùng để chấm OCR/điều kiện vì chưa rõ danh tính xe.

Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 là trung bình điều hòa. Mẫu số
rỗng trả `null` (UI hiện `—`), không tự coi là đúng. API trả
`evaluation_schema_version="0.2.0"`:

- **Event:** TP là cặp ghép **đúng loại xe**; cặp sai loại tạo một FP và một
  FN. Báo cáo thêm số cặp ghép, đúng loại, đúng `crossed`, temporal IoU trung
  bình, sai số đầu/cuối trung bình và tỷ lệ cả hai biên nằm trong ±500 ms.
  Dung sai 500 ms này chỉ là metric chẩn đoán, không quyết định ghép.
- **Clip:** hợp nhất các khoảng clip trước khi tính để không đếm trùng. Clip
  vật lý dùng `actual_start_ms`/`actual_end_ms` và bỏ clip `quality_status=invalid`;
  virtual segment dùng thời gian dự kiến. Từng GT đạt retained nếu clip giữ
  ≥ ngưỡng cài đặt (mặc định 95%) thời lượng GT; báo retention recall, độ phủ GT trung bình, precision
  thời gian giữ hữu ích, foreground recall và video reduction. Đây là chất
  lượng giữ/cắt video, tách khỏi F1 phát hiện event.
- **OCR:** bỏ bicycle. Nhánh không có artifact thì không chấm. Chỉ GT có
  `plate_readable=true` **và** chuỗi biển, hoặc `plate_readable=false` **và**
  không có chuỗi, được chấm; nhãn thiếu/mâu thuẫn được đếm là chưa thể chấm.
  Chuẩn hóa chữ hoa và bỏ ký tự không phải chữ/số. Chuỗi sai tạo một FP + một
  FN; không có dự đoán cho GT đọc được tạo FN. Báo điểm có điều kiện trên cặp
  ghép và điểm end-to-end tính cả GT bị bỏ sót và dự đoán ở event dư.
- **Điều kiện CV + VLM:** bỏ bicycle và run không có artifact thì không chấm.
  `good`/`unreadable` có accuracy và PRF với `unreadable` là lớp dương; ba
  nguyên nhân dùng micro PRF đa nhãn. Gợi ý thiếu trên GT `unreadable` tạo FN.
  Có cả điểm trên cặp ghép và end-to-end tính GT/event bỏ sót hoặc dư. GT
  không có trạng thái hợp lệ được đếm là chưa thể chấm.

Trang còn hiển thị số GT giữ nguyên các trường event từ gợi ý. Con số này
**không chứng minh người duyệt đã hoặc chưa kiểm tra**, nhưng cảnh báo khi điểm
100% có thể phản ánh việc GT lấy nguyên gợi ý. Điểm vẫn phụ thuộc chất lượng
GT do người duyệt tạo; không thể tự xác minh xe bỏ sót chưa được thêm GT.

Ngày tổng hợp: 15/09/2026. Phạm vi: yêu cầu trong `tools can xay dung.txt` và 6 ảnh giới thiệu V-Parking.

## 1. Kết luận đề xuất

Xây **bộ đánh giá theo lượt xe, có ground truth do người kiểm duyệt**, gồm ba đường chạy: model dev trên clip chuẩn, toàn bộ pipeline trên video gốc và OCR trên crop chuẩn nếu giao diện model cho phép. Báo cáo phải vừa đo chất lượng chung vừa truy được từng lỗi về video gốc.

Phương án bước 1 phù hợp để bắt đầu: **detector xe có sẵn + ByteTrack + vùng quan tâm theo làn + quy tắc giữ/cắt theo thời gian**. Ưu tiên giữ đủ lượt xe và cơ hội đọc biển số. Thử phương pháp này đối chiếu với phát hiện chuyển động đơn giản trên cùng dữ liệu trước khi chọn cấu hình. Chưa có video, phần cứng hay model dev để chứng minh một cấu hình là tốt nhất.

Đơn vị chính là **một lần một xe đi qua vùng đánh giá của một làn**. Frame là đơn vị chẩn đoán bổ sung. Một xe đứng 20 giây không được có trọng số lớn gấp 10 lần xe đi qua trong 2 giây chỉ vì có nhiều frame hơn.

Ưu tiên xây dữ liệu và evaluator trước, sau đó tối ưu detector/cutter. Các metric nghiệp vụ và ngưỡng thử nghiệm bên dưới là **đề xuất thiết kế cho dự án**, không phải tiêu chuẩn nghiệm thu lấy nguyên từ một bài báo.

## 2. Nghiên cứu liên quan và ý nghĩa đối với dự án

Đây là tổng hợp có chọn lọc từ bài báo và nguồn chính chủ; không phải khảo sát hệ thống toàn bộ lĩnh vực hay bảng xếp hạng mô hình mới nhất. Các kết quả giữa nghiên cứu không được so trực tiếp nếu khác dataset, đơn vị tính, preprocessing hoặc phần cứng.

| Nguồn | Nội dung có liên quan | Áp dụng và giới hạn |
|---|---|---|
| [Laroca et al., IJCNN 2018 — A Robust Real-Time ALPR Based on YOLO](https://arxiv.org/abs/1802.09567) | Pipeline nhận diện biển số nhiều bước và dataset UFPR-ALPR với xe/camera chuyển động. | Cần đánh giá từng bước và toàn bộ pipeline; dữ liệu thực địa quyết định độ khó. Bối cảnh khác camera cố định bãi xe Việt Nam. |
| [Silva & Jung, ECCV 2018 — License Plate Detection and Recognition in Unconstrained Scenarios](https://openaccess.thecvf.com/content_ECCV_2018/html/Sergio_Silva_License_Plate_Detection_ECCV_2018_paper.html) | Phát hiện và hiệu chỉnh biển số bị biến dạng phối cảnh trước OCR. | Phân nhóm góc nghiêng và lỗi crop/rectification; không quy mọi lỗi chuỗi cho OCR. |
| [VNLP, nguồn dataset của nhóm tác giả; MAPR 2022 / The Visual Computer 2023](https://github.com/fict-labs/VNLP) | Khoảng 37.300 ảnh biển số Việt Nam, một dòng/hai dòng; mô tả đánh giá OCR với crop GT và với detection thực tế. | Rất sát yêu cầu về bố cục và cách tách lỗi. Dataset ảnh không thay thế GT lượt xe trên video liên tục. |
| [Zhang et al., ECCV 2022 — ByteTrack](https://arxiv.org/abs/2110.06864) | Liên kết cả detection điểm thấp với track để giảm mất đối tượng và đứt track. | Là baseline theo dõi xe đáng thử; kết quả trên benchmark tracking không chứng minh sẵn hiệu quả ở làn xe máy. |
| [Luiten et al., IJCV — HOTA](https://arxiv.org/abs/2009.07736) | Cân bằng đánh giá detection, association và localization. | Dùng HOTA/DetA/AssA khi có GT track dày theo frame và cần chẩn đoán tracker. Không bắt buộc cho MVP chỉ lọc video. |
| [Che et al., 2023 — Character Time-series Matching](https://arxiv.org/html/2307.11336v2) | Ghép ký tự qua nhiều frame, cộng điểm tin cậy; có thử nghiệm với biển số Việt Nam. | Đáng thử temporal fusion. Protocol UFPR trong bài gộp 0/O và 1/I theo định dạng: không áp dụng phép gộp đó vào evaluator của dự án. |
| [Viswanathan et al., 2025 — FANVID](https://arxiv.org/abs/2506.07304) | Benchmark video độ phân giải thấp để nghiên cứu thông tin theo thời gian. | Hỗ trợ lý do đánh giá theo video; phần biển số có quy mô danh tính nhỏ và video được hạ độ phân giải, chưa đại diện bãi xe Việt Nam. Nguồn đọc: bản arXiv. |
| [Na et al., 2025 — MF-LPR²](https://arxiv.org/html/2508.14797v1) | Căn chỉnh/ghép nhiều frame bằng optical flow cho biển số chất lượng thấp. | Hướng nâng cấp sau baseline; cần kiểm chứng lợi ích nhận diện và chi phí. Không dùng ảnh phục hồi làm GT. Nguồn đọc: bản arXiv. |
| [Geifman & El-Yaniv, ICML 2019 — SelectiveNet](https://proceedings.mlr.press/v97/geifman19a) | Đánh đổi giữa tỷ lệ tự trả lời và lỗi trên các câu trả lời được chấp nhận. | Dùng đường risk–coverage để chọn ngưỡng chuyển người xử lý. Không cần thay model dev bằng SelectiveNet. |
| [Guo et al., ICML 2017 — On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a) | Confidence của mạng không tự động là xác suất đúng; nghiên cứu calibration. | Kiểm tra confidence ở cấp toàn biển số; không coi confidence 0,99 là đã chứng minh độ đúng 99%. |

Nguồn bổ sung: [UFPR-ALPR chính chủ](https://web.inf.ufpr.br/vri/databases/ufpr-alpr/) báo riêng ô tô/xe máy và kết quả có/không khai thác nhiều ảnh; [COCO evaluator](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py) cho AP; [Hugging Face CER implementation](https://github.com/huggingface/evaluate/blob/main/metrics/cer/cer.py) cho edit distance; [OpenCV background subtraction](https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html) cho baseline chuyển động; [NIST exact binomial confidence limits](https://www.itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbici.htm) cho độ bất định của tỷ lệ.

## 3. Chốt đối tượng đánh giá và cách ghép kết quả

### 3.1 Lượt xe và clip là hai khái niệm khác nhau

- Một lượt có `event_id`, `camera_id`, `lane_id`, xe, hướng di chuyển, thời gian vào/ra vùng đánh giá. Xe đứng đợi vẫn thuộc lượt đang mở. Xe rời rồi quay lại xử lý theo quy tắc tái nhập đã đóng băng.
- Clip chỉ là khoảng video được giữ. Một clip có thể chứa nhiều lượt xe nối tiếp hoặc đồng thời. Không bắt buộc một clip bằng một xe; không chấm clip chứa hai xe là sai nếu cutter có nhiệm vụ giữ vùng thời gian.
- Xác định riêng vùng xe xuất hiện và vùng camera có cơ hội đọc biển số. Xe đỗ nền ngoài vùng nghiệp vụ không phải lượt.
- Lượt dở dang ở đầu/cuối tệp: nối được thì nối bằng timestamp; không nối được thì gắn `truncated`, báo riêng. Không tự xóa khỏi thống kê mà không ghi số lượng.

### 3.2 Nguyên tắc matching

Ghép prediction với GT bằng camera/làn, thời gian và vị trí/track nếu có; **không dùng chuỗi biển số đúng/sai để quyết định ghép**, vì sẽ che mất lỗi nhận diện. Với các kết quả sự kiện, dùng ghép một-một tối đa số cặp hợp lệ rồi tối ưu độ khớp thời gian/vị trí. Các ngưỡng hợp lệ được chọn trên validation và lưu trong protocol. Khi có nhiều xe đồng thời mà output chỉ có một chuỗi cho cả clip, yêu cầu bổ sung timestamp/box/track hoặc đánh dấu không đủ thông tin quy lỗi cho từng xe.

Prediction dư sau matching tính là kết quả thừa, kể cả lặp lại biển đúng. GT không được ghép là lượt bỏ sót. Kết quả sửa đổi của cùng một lượt cần có loại thông điệp `update`/`final`; đánh giá quyết định cuối cùng hoặc quyết định tại deadline đã thỏa thuận, không lấy bất kỳ frame đúng nào làm kết quả cuối.

## 4. Bộ metric đề xuất

### 4.1 Bước 1 — giữ đủ dữ liệu trước khi tối ưu dung lượng

Gọi K là hợp các khoảng thời gian được giữ trên mỗi camera, Gᵢ là khoảng lượt xe i trong vùng đánh giá, Rᵢ là tập thời điểm/đoạn đã gán nhãn có thể đọc biển của lượt đó. Đo theo thời gian nguồn, không theo số frame của clip đã đổi FPS.

| Metric | Định nghĩa đề xuất | Vai trò |
|---|---|---|
| Event retention recall | Số lượt có `duration(K ∩ Gᵢ) / duration(Gᵢ) ≥ q` chia tổng lượt hợp lệ | Metric chính của cutter; q thử ban đầu 0,95, cần chốt sau pilot. Báo thêm phân bố coverage, không chỉ một ngưỡng. |
| Readable-opportunity retention | Trong các lượt có Rᵢ khác rỗng ở video gốc, tỷ lệ còn giữ ít nhất k frame đọc được tại các timestamp khác nhau | Bắt lỗi cắt mất phần hữu ích nhất. Báo k=1 và một k lớn hơn phù hợp input model2, ví dụ 3. GT frame thưa thì chỉ kết luận trên các frame đã kiểm duyệt. |
| Foreground time recall | `duration(K ∩ hợp Gᵢ) / duration(hợp Gᵢ)` | Đo bao nhiêu thời gian có xe được giữ. Không thay event recall vì xe đứng lâu có thể lấn át. |
| Temporal precision | `duration(K ∩ hợp Gᵢ) / duration(K)` | Đo mức giữ thừa nền; phần đệm chủ ý cũng làm precision giảm, cần đọc cùng recall. |
| Video reduction | `1 − duration(K) / duration(raw)` | Đo hiệu quả rút ngắn dữ liệu. Báo thêm tổng thời lượng file xuất để phát hiện xuất trùng các clip chồng lấn. |
| False clips/hour | Số clip xuất không giao bất kỳ Gᵢ nào / số giờ raw | Phát hiện cắt nhầm do người, bóng, đèn, barrier. |
| Start/end loss | Với mỗi Gᵢ có phần được giữ, số giây đầu/cuối lượt bị mất; báo median, p95 | Chỉ rõ cắt muộn/kết thúc sớm; lượt mất toàn bộ báo riêng. |
| Fragmentation | Số lượt có phần thời gian giữ bị chia thành nhiều đoạn rời / tổng lượt | Chẩn đoán mất liên tục, không phạt việc gộp nhiều xe vào cùng clip. |

Nếu cutter còn phát ra danh sách sự kiện xe: bổ sung event precision/recall/F1 sau matching một-một. Với cutter chỉ giữ khoảng thời gian, không ép event precision bằng cách đếm clip. Các metric trên là đề xuất theo mục tiêu cắt video của dự án.

### 4.2 Model dev và toàn pipeline — bộ metric bắt buộc

Tập E gồm các lượt có biển số GT xác minh được cho nhiệm vụ nhận diện. Báo riêng E-readable (đọc được từ video camera này), E-external (chỉ xác minh được từ nguồn độc lập). Các lượt không có biển/không xác định được text nằm ở nhóm khác, vẫn nằm trong thống kê phát hiện sự kiện và chuyển người xử lý.

| Metric | Cách tính | Lỗi được phản ánh |
|---|---|---|
| Event exact-match accuracy | Số lượt trong E có output cuối đúng toàn chuỗi, đúng xe / số lượt E | Chỉ số chính. Bỏ sót, crash, trả rỗng, trả sai đều không thành công. Công bố cho clip chuẩn và pipeline thực tế riêng. |
| Wrong-read rate | Số lượt E được trả một biển không rỗng nhưng sai / số lượt E | Phân biệt đọc sai với bỏ đọc. |
| No-result rate | Số lượt E không có kết quả được chấp nhận / số lượt E | Bao gồm abstain, miss, timeout; tách nguyên nhân con. Với mỗi lượt chọn đúng một trạng thái, correct + wrong + no-result = 100%. |
| Accepted-result precision | Số kết quả được chấp nhận đúng xe và đúng text / tổng kết quả được chấp nhận trên phạm vi GT xác minh được | Bắt cả output thừa/duplicate. Công bố mẫu số; không suy ra bằng 1 − wrong-read rate vì mẫu số khác. |
| Spurious outputs/hour | Số output không khớp lượt thật / giờ raw đã kiểm duyệt | Đọc “biển số” từ nền hoặc sinh sự kiện giả. |
| Duplicate outputs/1.000 events | Số final output dư gắn với lượt đã có kết quả / tổng lượt × 1.000 | Tránh ghi nhận một xe nhiều lần. |
| CER | `tổng(S + D + I) / tổng số ký tự GT` trên E | S: thay, D: thiếu, I: thừa theo căn chỉnh Levenshtein. Mất toàn chuỗi tính toàn bộ ký tự là D. CER có thể >100%; không gọi 1−CER là accuracy. |
| Character confusion | Bảng ký tự GT → ký tự dự đoán, kèm ký tự rỗng cho thiếu/thừa | Chỉ rõ nhầm 8/B, 0/O…; báo số lỗi và tỷ lệ theo số lần ký tự GT xuất hiện. |
| Coverage và selective risk | Coverage = số lượt E có trả lời được chấp nhận / số lượt E; risk = số trả sai / số lượt E có trả lời | Vẽ đường khi quét confidence; nếu không có trả lời thì risk là N/A. Báo thêm precision toàn output để bắt output thừa. |
| p50/p95 latency và timeout rate | Độ trễ từ mốc nghiệp vụ đến output được chấp nhận; timeout / tổng lượt hợp lệ | Chỉ báo độ trễ trên lượt thành công sẽ che bỏ sót, nên luôn báo deadline success cùng timeout. |
| Runtime và tài nguyên | Thời gian xử lý/thời lượng nguồn (RTF), peak RAM/VRAM, số video lỗi | Kiểm tra khả năng xử lý khối lượng dữ liệu thực tế. RTF <1 là nhanh hơn thời lượng nguồn trong cấu hình đo. |

CER dựa trên [triển khai tham chiếu](https://github.com/huggingface/evaluate/blob/main/metrics/cer/cer.py); risk–coverage vận dụng ý tưởng [SelectiveNet](https://proceedings.mlr.press/v97/geifman19a). Các định nghĩa cấp lượt xe ở bảng là protocol đề xuất, cần triển khai thống nhất.

Chuẩn hóa text: lưu cả nguyên bản và bản chuẩn hóa; có thể chuyển chữ hoa, bỏ dấu phân cách trình bày đã thống nhất, đọc biển hai dòng theo thứ tự trên rồi dưới. **Không đổi O thành 0, B thành 8, tự thêm ký tự, hay sửa theo danh sách xe đăng ký trong evaluator**. Nếu dev có hậu xử lý như vậy, lưu và chấm cả output trước/sau để thấy tác động.

Ví dụ minh họa tự xây: GT `30A12345`, prediction `30A12845`: exact match = 0, CER = 1/8 = 12,5%, substitution 3→8. Với 100 lượt GT, cắt chỉ giữ 90 và model đúng 81: accuracy trên 90 lượt giữ lại là 90%, nhưng thành công toàn pipeline chỉ 81/100 = 81%.

Deadline: có thể dùng lúc xe vào vùng đọc biển làm t0; thời hạn do nghiệp vụ quy định. Báo tỷ lệ đúng trước deadline trên toàn bộ E. “Thời điểm đúng đầu tiên” chỉ là chẩn đoán bằng GT, không thay cho thời điểm hệ thống thực sự ra quyết định. Kết quả offline dùng toàn clip phải tách khỏi kết quả online chỉ dùng frame đã đến.

### 4.3 Metric chẩn đoán chỉ bật khi có dữ liệu phù hợp

- **Plate detection:** AP50, AP@[0.50:0.95], precision/recall tại confidence vận hành; cần box GT và output box. Theo [COCO evaluator](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py). AP tốt không chứng minh OCR tốt. Chấm riêng nhóm biển nhỏ và một/hai dòng.
- **Tracking:** HOTA, DetA, AssA, ID switches khi có track GT theo frame đầy đủ trên các đoạn chọn đánh giá; dùng evaluator tham chiếu của [tác giả HOTA](https://autonomousvision.github.io/hota-metrics/). Không tính HOTA từ vài keyframe rồi công bố như đánh giá toàn video.
- **OCR-only:** exact match và CER trên crop GT; so với crop dự đoán trên cùng frame để khoanh vùng ảnh hưởng detection/crop.
- **Temporal stability:** tỷ lệ lượt có thay đổi chuỗi non-empty qua thời gian và số lần đổi/lượt; kiểm tra track trộn xe. Không dùng thay exact match vì model có thể sai ổn định.
- **Confidence calibration:** reliability plot, Brier score `mean((p−y)²)` ở cấp toàn biển số (y=1 khi toàn chuỗi đúng); ECE kèm số bin và số mẫu. Chỉ áp dụng nếu p có ý nghĩa xác suất đúng toàn chuỗi, hoặc được hiệu chỉnh trên validation. Tham khảo [Guo et al.](https://proceedings.mlr.press/v70/guo17a).
- **Xe không biển:** false plate emission rate = số lượt được xác nhận không biển nhưng model xuất biển / số lượt xác nhận không biển. “Không nhìn thấy biển ở camera này” là nhãn khác với “xe không gắn biển”.
- **Biển không đọc được, không có text xác minh:** báo tỷ lệ abstain và tỷ lệ phát text chưa xác minh; không tự kết luận text đó đúng hoặc sai.
- **Ghép vào/ra**, nếu model2 thực sự cung cấp: pair precision/recall, ghép sai xe, không ghép được. Chưa đưa vào nghiệm thu nếu model chỉ nhận diện biển số.

## 5. Xây ground truth để đánh giá đáng tin

### 5.1 Hai cấp nhãn

**Cấp lượt xe, cần cho toàn bộ test:** video nguồn/hash, camera/làn, event ID, t_start/t_end theo timestamp, loại xe, hướng, text và trạng thái biển, trạng thái đọc được, khoảng/keyframe đọc được, nhãn điều kiện, reviewer và phiên bản nhãn.

**Cấp frame, dành cho tập chẩn đoán:** timestamp gốc, vehicle box/track ID, plate box hoặc polygon, text nếu xác minh được, mức nhìn rõ/che khuất. Gán dày toàn frame của một số đoạn nếu cần tracking; không cần gán box từng ký tự trên toàn bộ dataset để tính CER.

Độ đọc được cần phân biệt: đọc được trong một frame; chỉ đọc được khi xem nhiều frame; text chỉ biết qua nguồn ngoài; đọc một phần; không đọc được; không có biển; ngoài góc nhìn. Rᵢ ở mục 4.1 chỉ áp dụng cơ hội đọc được đã xác minh, không ép mọi lượt có text GT phải có một frame hoàn chỉnh.

### 5.2 Quy trình gán nhãn

1. Lấy các khoảng video liên tục độc lập với kết quả model1, có cả giờ vắng và đông, ngày/đêm, ô tô/xe máy. Xác nhận các đoạn hỏng/mất camera và công bố thời lượng loại trừ.
2. Người gán nhãn xem toàn bộ các khoảng được chọn để tìm lượt xe, gồm phần cutter bỏ. Có thể dùng model gợi ý nhưng phải kiểm tra phần âm tính; GT test không được chỉ gồm clip model đã tìm thấy.
3. Người kiểm duyệt ghi text từ video gốc, cho phép xem chậm/phóng to; lưu bằng chứng và nguồn text. Không dùng OCR dev hoặc ảnh AI phục hồi làm sự thật mặc định.
4. Hai người đọc độc lập các biển mơ hồ và kiểm tra ngẫu nhiên một phần mẫu thường (đề xuất pilot 10–20%); bất đồng cần người phân xử. Theo dõi tỷ lệ bất đồng text và thời điểm.
5. Khóa phiên bản GT trước chạy test. Nếu sửa GT sau phát hiện lỗi nhãn, ghi changelog và chạy lại các phiên bản model bị ảnh hưởng.

Trong pilot, giao diện local hỗ trợ đánh dấu khoảng event, timestamp đọc được,
chọn `good` nếu biển có khả năng đọc, hoặc `unreadable` cùng một hay nhiều
nguyên nhân `capture_blur`, `plate_obstruction`, `lighting_issue`. Nguồn nhãn
là `human`; evaluator hiện chỉ dùng timestamp đọc được.

### 5.3 Chia dữ liệu

- Tách train/validation/test theo video liên tục, camera/ngày và danh tính xe khi khả thi. Không random các frame liền nhau sang các tập khác nhau.
- Có test trong điều kiện triển khai quen thuộc và test camera/ngày mới; báo riêng. Xe vé tháng lặp lại cần được đánh dấu để biết khả năng tổng quát sang xe chưa gặp.
- Validation dùng chọn FPS, ROI, ngưỡng, padding, confidence và fusion. Test giữ kín cho đánh giá cuối.
- Tách **tập đại diện vận hành** (tỷ lệ tình huống tự nhiên) và **tập thử thách** (cố ý nhiều ca khó). Không cộng hai tập rồi gọi đó là accuracy sản xuất.
- Dữ liệu công khai hỗ trợ nghiên cứu/khởi tạo; GT camera của bạn vẫn là trọng tâm. UFPR công bố giới hạn dùng nghiên cứu phi thương mại trên [trang chính chủ](https://web.inf.ufpr.br/vri/databases/ufpr-alpr/); xác minh điều kiện trước khi dùng cho dự án. Chưa tải dataset nào trong lần nghiên cứu này.

## 6. Phân tích lỗi để gửi dev sửa được

Mỗi lượt có thể có nhiều nhãn điều kiện: camera/làn, ngày/đêm, thiếu sáng, chói/phản xạ, mờ chuyển động, out-of-focus, biển nhỏ theo pixel, góc nghiêng, bẩn, che khuất, một/hai dòng, loại xe, nhiều xe sát nhau, dừng lâu, đi lùi, biển ngoài góc nhìn. Nhãn phải có mô tả và ví dụ thống nhất; không suy ra nhãn “bẩn” chỉ vì OCR sai.

Cho từng nhóm báo **N, số lỗi, exact-match, wrong-read, no-result, CER và khoảng tin cậy**. Báo cả tỷ lệ lỗi trong nhóm và tỷ trọng nhóm trong tổng lỗi. Nhóm có ít mẫu ghi “chưa đủ bằng chứng”; không xếp hạng quá chắc chắn. Nhãn chồng lấn nên tổng số lỗi theo nhóm có thể lớn hơn tổng lỗi thực.

Hai lớp giải thích cần tách rõ:

- **Vị trí lỗi có bằng chứng:** cutter bỏ mất lượt/cơ hội đọc; không detect biển; crop sai; gán nhầm xe; OCR sai; fusion đổi đúng thành sai; timeout. Khi model không cung cấp đầu ra trung gian thì để `unknown_stage`, không đoán.
- **Điều kiện đi kèm:** biển bẩn, tối, nghiêng… Tỷ lệ lỗi cao ở nhóm tối cho thấy tương quan; muốn kết luận do ánh sáng cần phân tích có kiểm soát hoặc thử nghiệm bổ sung.

Một dòng lỗi cần đủ: run/model version, event ID, link video + timestamp, GT, prediction, confidence, edit operations, nhãn điều kiện, ảnh bằng chứng, bước lỗi đã xác minh và ghi chú reviewer. Từ đó tạo danh sách lỗi thường gặp và bộ regression để kiểm tra phiên bản mới.

## 7. Phương pháp triển khai nên thử

### 7.1 Bước cắt video

| Phương án | Điểm hữu ích | Hạn chế dự kiến / cách sử dụng |
|---|---|---|
| Chuyển động trong ROI bằng MOG2/KNN | Ít công triển khai, dùng được làm đối chứng; OpenCV có hướng dẫn chính thức | Có thể giữ nhầm bóng/đèn/người và mất xe dừng lâu; cần đo thực tế. |
| Detector xe + tracking + ROI | Nhận biết đối tượng và duy trì lượt khi xe dừng, có thể theo dõi nhiều xe | Cần GPU/CPU phù hợp; detector có thể hụt xe nhỏ hoặc bị che. **Lựa chọn khởi đầu đề xuất.** |
| Huấn luyện model phân loại đoạn video riêng | Có thể thích nghi đặc thù cảnh | Cần nhãn và công huấn luyện; chỉ cân nhắc sau khi baseline bộc lộ lỗi khó sửa bằng cấu hình/fine-tune. |

Cấu hình thử ban đầu, không phải thông số đã chứng minh: detector pretrained thuộc họ YOLO hoặc detector xe sẵn có, ByteTrack, ROI riêng từng camera; so sánh 5/10 FPS và FPS gốc trên pilot. Buffer trước/sau thử 1–2 giây, thời gian chờ mất track thử 1–3 giây. Lưu khoảng theo timestamp và hiệu chỉnh theo thời gian thực khi đổi FPS. Chọn cấu hình theo event/readable recall trước, reduction và runtime sau.

**Pilot MOG2 từ 29/09/2026:** MOG2 đã được thêm làm gate tùy chọn trước
YOLO/ByteTrack, không thay detector. Bài toán đánh giá là *giảm lượt gọi YOLO
trong khoảng yên nhưng giữ event recall*. Báo cáo cần có
`detector_frames/sampled_frames`, chi phí gate, thời gian YOLO+gate, recall
event và sai lệch start/end so với GT trên video có thời gian yên dài, xe đi
chậm, đổi sáng và bóng. Trên video test 17,395 s có event gần liên tục,
gate không bỏ frame nào; trên video tĩnh 20 s, bỏ 148/200 frame detector và
giảm thời gian YOLO+gate từ 33,188 xuống 8,906 s. Đây là bằng chứng hiệu
năng ở hai tình huống, chưa đủ để khẳng định recall trên camera sản xuất.

Giữ video trong lúc xe có mặt trong ROI, có hysteresis để một vài detection hụt không cắt ngay. Tách logic presence để giữ clip khỏi logic crossing để đếm lượt; xe dừng trước vạch vẫn cần dữ liệu. Có cơ chế xử lý mất track/tái nhập để không giữ video vô hạn hoặc đếm trùng. Giữ ảnh gốc, độ phân giải và ánh xạ thời gian; đo lại chất lượng sau encode, không mặc định video nén lại tương đương đầu vào.

Nếu detector pretrained bỏ xe máy/xe che nhiều, bổ sung nhãn và fine-tune trên train; không dùng test để chỉnh. Nếu phát hiện chuyển động đạt cùng recall với chi phí thấp hơn rõ rệt trên camera đơn giản thì chọn nó cho camera đó.

### 7.2 Đánh giá model2 qua ba đường chạy

| Đường chạy | Dữ liệu | Trả lời câu hỏi |
|---|---|---|
| A — Model dev độc lập | Clip chuẩn do người duyệt, khoảng thời gian cố định | Model dev làm tốt đến đâu khi dữ liệu đầu vào đủ? |
| B — Pipeline thực tế | Raw → cutter tự động → model dev | Toàn tool bỏ sót/đọc sai bao nhiêu lượt? Mẫu số vẫn lấy từ raw GT. |
| C — OCR chẩn đoán | Crop biển số GT trên tập frame cố định | OCR yếu hay detector/crop yếu? Chỉ chạy nếu giao diện hỗ trợ. |

So A/B bằng kết quả từng lượt: A đúng B sai, A sai B đúng, cả hai đúng, cả hai sai. Chênh lệch tổng chỉ là dấu hiệu; cần xem clip, timestamp, encoding và trạng thái model để quy nguyên nhân. Reset trạng thái theo quy tắc giống nhau, nhất là model streaming. Nếu chạy model2 trực tiếp trên raw được thì thêm đối chứng raw trên một tập nhỏ.

### 7.3 Ghép nhiều frame là hướng cải thiện có điều kiện

Đánh giá bản dev nguyên trạng trước. Nếu muốn thêm fusion, coi là phiên bản pipeline riêng. So sánh: frame chọn theo chất lượng ảnh (không dùng GT), voting nguyên chuỗi trong cùng track, rồi fusion có trọng số/chỉnh phối cảnh nếu cần. Đo exact-match, wrong-read và latency; chọn trên validation.

Voting nguyên chuỗi dễ giải thích và không tạo chuỗi ghép chưa từng xuất hiện. Ghép từng ký tự có thể giúp nhưng phải căn chỉnh chuỗi, xử lý một/hai dòng, frame tương quan và nhầm track. Không chọn “frame nào đúng GT nhất” làm phương pháp vận hành; đó chỉ là trần tham khảo chẩn đoán. MF-LPR²/optical flow là hướng nghiên cứu sau, khi lợi ích vượt chi phí trên dữ liệu thật.

## 8. Cỡ mẫu, khoảng tin cậy và ngưỡng nghiệm thu

Chưa nên cam kết “đạt 99,9%” khi chưa có pilot. Đề xuất 300–500 lượt đa dạng để kiểm tra protocol và gán nhãn; sau đó mở rộng test đại diện tới vài nghìn lượt theo yêu cầu độ tin cậy. Đây là kế hoạch khởi đầu, không phải cỡ mẫu bảo đảm mọi mức chất lượng.

Báo khoảng tin cậy 95% cho tỷ lệ. Khi lượt đủ độc lập có thể dùng Wilson hoặc Clopper–Pearson; khi nhiều lượt cùng camera/ngày/xe có tương quan, so sánh phiên bản bằng paired cluster bootstrap theo phiên ghi hình hoặc nhóm phù hợp và báo số nhóm. Không bootstrap các frame như các lượt độc lập.

Ví dụ suy ra từ mô hình nhị thức: không gặp lỗi nào trong n phép thử độc lập cho cận trên lỗi một phía 95% là `1 − 0,05^(1/n)`, xấp xỉ `3/n`. Muốn cận này ≤0,1% cần ít nhất 2.995 thử nghiệm độc lập không lỗi. Đối với selective risk, n là số lượt **đã chấp nhận trả lời**, không phải tổng lượt. Với dữ liệu tương quan hoặc ít camera, không thể dùng phép tính này như bảo đảm triển khai. Cơ sở: [NIST exact binomial limits](https://www.itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbici.htm).

Ngưỡng để thảo luận sau pilot:

- Cutter: đề xuất mục tiêu event retention và readable-opportunity retention ≥99,5%; ưu tiên tăng recall nếu phải đánh đổi dung lượng. Đây là mục tiêu thử, chưa là mức đã đạt hay tiêu chuẩn ngành.
- Model2: thống nhất mức wrong-read chấp nhận được và coverage tối thiểu rồi chọn confidence trên validation. Không đưa ngưỡng accuracy tùy ý khi chưa biết điều kiện camera.
- Nghiệm thu: dùng cận dưới cho recall/accuracy/coverage và cận trên cho error risk; ghi cả kết quả chung, các nhóm quan trọng và độ trễ. Nếu thiếu mẫu thì kết luận “chưa đủ bằng chứng đạt”, không tự coi là đạt.
- Phiên bản mới: so trên cùng test, nêu số ca sửa được và ca mới bị lỗi. Regression phải bao gồm cả lỗi cũ đã phát hiện và test giữ kín chưa dùng để tune.

## 9. Nội dung báo cáo gửi dev

1. **Phạm vi và tái lập:** dataset/GT version, số camera/giờ/lượt, nhóm loại trừ, model hash, cấu hình, phần cứng, input FPS/resolution, deadline và matching protocol.
2. **Scorecard:** A/B exact-match, wrong-read, no-result, CER, accepted precision, spurious/duplicate outputs, coverage–risk, latency/runtime; luôn có tử số, mẫu số và CI.
3. **Cutter:** event retention, readable retention, mất đầu/cuối, video reduction, false clips/hour.
4. **Điểm yếu:** bảng nhóm điều kiện, confusion ký tự, top lỗi theo tần suất và tác động, ví dụ có bằng chứng.
5. **So phiên bản:** chênh lệch metric, khoảng tin cậy, ca cải thiện/regression, cấu hình được giữ cố định.
6. **Kết luận:** đạt/chưa đạt/chưa đủ dữ liệu theo từng tiêu chí, hành động đề xuất và phần chưa xác định được nguyên nhân.

Xuất HTML để xem/lọc lỗi; CSV/JSON cho kết quả từng lượt và manifest để tái lập. Dùng đường dẫn tương đối trong gói báo cáo tới clip/ảnh bằng chứng. Không cần xây mọi biểu đồ chẩn đoán ngay nếu model chưa trả box/track/confidence.

## 10. Thứ tự xây tool và thông tin còn thiếu

1. Định nghĩa event/nhãn/matching; chọn pilot video raw liên tục và kiểm duyệt GT.
2. Viết adapter model dev, evaluator exact-match/CER và trang xem lỗi; chạy đường A để có baseline sớm.
3. Xây cutter, kiểm tra phần bị bỏ và chạy đường B; thử motion so với detector + tracker.
4. Thêm nhãn điều kiện, confidence/deadline, so phiên bản và xuất báo cáo.
5. Khi cần khoanh vùng sâu, mở rộng box/track GT và đường C; sau đó mới thử fusion/fine-tune.

Thông tin cần lấy khi chuẩn bị triển khai: video mẫu có cả khoảng vắng; giao diện model2 nhận frame/clip/stream và output gì; camera/làn/FPS; GPU/CPU; nhu cầu offline hay online; thời hạn trả kết quả; mức sai chấp nhận được. Có thể tiến hành pilot và hoàn thiện protocol trước khi mọi mục này được xác định.

**Khuyến nghị cuối:** lấy exact-match theo lượt, wrong-read/no-result, CER/confusion ký tự và phân nhóm điều kiện làm lõi đánh giá dev; lấy event/readable retention làm lõi đánh giá cutter. Detector + ByteTrack + ROI là baseline ưu tiên để thử, còn GT độc lập trên raw video là điều kiện để các con số có ý nghĩa.

## 11. Metric đã có trong evaluator pilot

`src/parking_step1/evaluation.py` hiện triển khai một tập con có thể tính
ngay từ GT event trên raw và manifest Bước 1:

- `event_recall`: tỷ lệ GT event có span clip bao phủ ít nhất
  `coverage_threshold` (mặc định 95%). Mẫu số là toàn bộ GT event hợp lệ,
  gồm cả event Model 1 bỏ sót.
- `event_detection_precision`: số GT được ghép theo camera và thời gian giao
  nhau chia cho tổng event dự đoán.
- `readable_retention_at_1`: trong GT có `readable_timestamps_ms`, tỷ lệ có ít
  nhất một timestamp nằm trong clip.
- `false_clips_per_hour`: clip không giao GT nào chia số giờ raw.
- `video_reduction`: `1 - tổng thời lượng span clip / thời lượng raw`.

Matching hiện là greedy theo overlap lớn nhất trong cùng camera; đây là bản
pilot để kiểm tra denominator và luồng dữ liệu, chưa phải protocol production
cho nhiều file/VFR hoặc ghép ENTRY–EXIT. CER, exact match biển số, confusion
matrix và phân tích theo `conditions` vẫn chưa được code.
# Ghi chú quy trình GT trên web local

Web local lưu annotation hiện hành trong SQLite và đồng bộ thành
`ground_truth.jsonl` schema `0.9.0`. Trạng thái `REVIEWED` chỉ được đặt khi
mọi event dự đoán trong run đã được giữ hoặc loại; đây là kiểm tra độ đầy đủ
của thao tác HITL. Web đã hỗ trợ thêm GT cho xe Model 1 bỏ sót trực tiếp từ
timeline raw, nhưng reviewer vẫn phải rà toàn bộ video để recall có mẫu số
đầy đủ. Các row GT giữ nguyên gợi ý được báo riêng; không thể tự chứng minh
chúng đã được kiểm tra độc lập.
