import type {AppSettings} from './SettingsPage';

const percent=(value:number)=>`${(value*100).toFixed(0)}%`;

export default function DocsPage({settings}:{settings?:AppSettings}){
 const iou=settings?.evaluation.min_temporal_iou??.30;
 const boundary=settings?.evaluation.boundary_tolerance_ms??500;
 const coverage=settings?.evaluation.coverage_threshold??.95;
 return <><header className="pageHead"><div><span>HƯỚNG DẪN LOCAL</span><h1>Tài liệu</h1></div></header>
 <div className="docsLayout">
 <section className="panel docsSection"><span className="docsEyebrow">BẮT ĐẦU</span><h2>1. Sử dụng tool</h2>
  <ol className="docsSteps">
   <li><b>Kho video:</b> tải video raw lên. Raw là nguồn gốc để kiểm tra mốc thời gian.</li>
   <li><b>Chạy phân tích:</b> xem bảng run và bấm Tạo run mới để chọn video, camera, làn và chiều ENTRY/EXIT; vẽ ROI/crossing line nếu cần, chọn OCR và CV–VLM rồi bấm Chạy phân tích. Có thể tạo run tiếp theo khi run trước vẫn đang chạy. Bấm Dừng trong bảng để hủy run chờ/chạy; trạng thái sẽ thành CANCELLED khi worker dừng. Cấu hình nâng cao nằm ở trang Cài đặt.</li>
   <li><b>Kết quả & duyệt:</b> chỉ có run đã hoàn thành. Xem video raw, kiểm tra từng event, sửa nhãn, xóa event sai và thêm hàng GT cho xe bị bỏ sót. Bấm Cập nhật để lưu, sau đó Duyệt để xác nhận GT cuối cùng. Nút Xóa ở bảng run xóa cả kết quả, clip và GT của run đó; video raw vẫn được giữ.</li>
   <li><b>Đánh giá:</b> mở run đã duyệt và đọc lần lượt event/clip → OCR → CV–VLM. Điểm được tính từ dự đoán gốc và GT đã duyệt; gợi ý model không tự chứng minh GT đã đúng.</li>
  </ol>
 </section>
 <section className="panel docsSection"><span className="docsEyebrow">CÁCH ĐỌC ĐIỂM</span><h2>Quy ước chung</h2>
  <p><b>TP</b> là kết quả đúng, <b>FP</b> là dự đoán dư hoặc sai, <b>FN</b> là GT bị bỏ sót. Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 cân bằng hai tỷ lệ. Dấu <b>—</b> nghĩa là không có mẫu số phù hợp hoặc nhánh model chưa chạy, không phải 0%.</p>
  <p>Metric OCR và điều kiện chỉ chấm <code>car</code>/<code>motorcycle</code>. <code>bicycle</code> vẫn được tính ở bước event và clip.</p>
 </section>
 <section className="panel docsSection"><span className="docsEyebrow">BƯỚC 01</span><h2>Event và clip</h2>
  <div className="docsMetric"><h3>Ghép event và Precision / Recall / F1</h3><p>Dự đoán và GT phải cùng camera, làn, chiều, có thời gian giao nhau và temporal IoU ≥ <b>{percent(iou)}</b>. Temporal IoU = thời gian giao / thời gian hợp. Ghép một-một: một GT chỉ nhận tối đa một event dự đoán. Cặp ghép còn phải đúng loại xe mới là TP; sai loại tạo một FP và một FN. Event dư là FP; xe GT thiếu là FN.</p></div>
  <div className="docsMetric"><h3>Sai số thời gian, loại xe và crossed</h3><p>Temporal IoU trung bình đo độ khớp thời gian trên các cặp đã ghép. Sai số đầu/cuối là chênh lệch tuyệt đối theo ms. “Biên trong ±{boundary} ms” là tỷ lệ cặp có <i>cả</i> đầu và cuối không lệch quá mức này; dung sai này không dùng để ghép. “Đúng loại xe” và “Đúng crossed” là tỷ lệ trên các cặp đã ghép.</p></div>
  <div className="docsMetric"><h3>Nguồn GT và kiểm tra nhãn</h3><p>“GT / Event model” là số lượt trong GT đã duyệt và số event dự đoán ban đầu. “GT thêm thủ công” đếm xe người duyệt thêm vì model bỏ sót; “event đã loại” đếm dự đoán bị xóa khỏi GT và tính là FP. “GT event giữ nguyên gợi ý” đếm hàng còn giữ nguyên thời gian, loại xe và crossed từ model: đây là tín hiệu cần kiểm tra raw, không chứng minh nhãn đúng hay sai.</p></div>
  <div className="docsMetric"><h3>Giữ clip trên video raw</h3><p>Một GT được coi là giữ đủ khi clip bao phủ ít nhất <b>{percent(coverage)}</b> thời lượng của event đó. “GT giữ đủ” đếm theo xe; “Độ phủ GT trung bình” lấy trung bình tỷ lệ phủ của từng xe. “Thời gian clip hữu ích” = thời gian clip trùng GT / toàn bộ thời gian clip. “Phần GT được giữ” = thời gian GT trùng clip / toàn bộ thời gian GT. “Giảm thời lượng video” = 1 − thời gian clip / thời lượng raw. Các clip chồng nhau được hợp nhất; clip bị đánh dấu invalid không được tính là đã giữ.</p></div>
  <p className="docsTip">Một clip có thể giữ đủ hình ảnh nhưng model vẫn gộp nhiều xe thành một event hoặc tách một xe thành nhiều event. Vì vậy hãy đọc metric event và clip cùng nhau.</p>
 </section>
 <section className="panel docsSection"><span className="docsEyebrow">BƯỚC 02</span><h2>OCR biển số</h2>
  <div className="docsMetric"><h3>OCR trên event ghép được</h3><p>So biển GT với biển gợi ý sau khi viết hoa và bỏ ký tự phân cách. Đúng toàn chuỗi là TP. Dự đoán biển sai tạo FP và FN; không trả biển cho GT đọc được tạo FN. Precision/recall/F1 ở thẻ này chỉ xét event đã ghép và đủ nhãn biển.</p></div>
  <div className="docsMetric"><h3>OCR toàn pipeline và giới hạn GT</h3><p>Recall toàn pipeline có mẫu số là mọi GT có biển đọc được, kể cả xe bị bước event bỏ sót. “GT biển chưa thể chấm” đếm nhãn thiếu hoặc mâu thuẫn: ví dụ đánh dấu đọc được nhưng không có chuỗi biển. Số 0 chỉ có nghĩa là nhãn đủ dữ liệu để chấm, không chứng minh chuỗi GT đã được người duyệt đọc đúng.</p></div>
  <p className="docsTip">“Event ghép đủ nhãn biển” là số cặp dự đoán–GT thực sự tham gia phép chấm OCR riêng. Số này có thể thấp hơn số event GT vì xe bị bỏ sót hoặc GT biển chưa đủ thông tin.</p>
 </section>
 <section className="panel docsSection"><span className="docsEyebrow">BƯỚC 03</span><h2>Điều kiện CV–VLM</h2>
  <div className="docsMetric"><h3>Trạng thái good / unreadable</h3><p>“Đúng good / unreadable” là accuracy: số trạng thái dự đoán đúng / số event ghép được có GT trạng thái hợp lệ. Precision/recall/F1 của thẻ unreadable coi <code>unreadable</code> là trường hợp cần phát hiện. Recall unreadable toàn pipeline còn tính cả xe GT bị bỏ sót. Nếu GT không có trường hợp unreadable, recall hiển thị “—”.</p></div>
  <div className="docsMetric"><h3>Ba nguyên nhân</h3><p><code>capture_blur</code>: ảnh bị mờ do quá trình ghi hình; <code>plate_obstruction</code>: biển bị vật thể che; <code>lighting_issue</code>: ánh sáng làm biển khó đọc. Một event có thể có nhiều nguyên nhân. Metric micro Precision/Recall/F1 cộng số nhãn nguyên nhân đúng, dư và thiếu trên toàn bộ mẫu; recall toàn pipeline tính thêm nguyên nhân của xe bị bước event bỏ sót. Không có nhãn nguyên nhân trong GT thì recall là “—”.</p></div>
  <p className="docsTip">“GT điều kiện không hợp lệ” đếm GT không có trạng thái good/unreadable để chấm. Điểm trên event ghép được giúp xem chất lượng riêng nhánh OCR/CV–VLM. Recall toàn pipeline phản ánh thêm tác động của bước phát hiện xe.</p>
 </section>
 </div></>;
}
