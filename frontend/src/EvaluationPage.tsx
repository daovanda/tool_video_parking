import {useEffect,useState} from 'react';
import {ArrowLeft,ChevronRight,RefreshCw} from 'lucide-react';
import {api} from './api';
import type {RunItem} from './types';

type Scores={tp:number;fp:number;fn:number;precision:number|null;recall:number|null;f1:number|null};
type Evaluation={run:RunItem;runtime:{schema_version:string;scope:'full_pipeline'|'step1_core_only'|'unavailable';elapsed_seconds:number|null;core_elapsed_seconds:number|null;ocr_elapsed_seconds:number|null;condition_elapsed_seconds:number|null;raw_duration_seconds:number;total_to_raw_ratio:number|null};metrics:{events:Scores&{gt_count:number;prediction_count:number;matched:number;class_confusions:number;mean_temporal_iou:number|null;mean_start_error_ms:number|null;mean_end_error_ms:number|null;vehicle_type_accuracy:number|null;crossed_accuracy:number|null;within_boundary_tolerance:number|null;min_temporal_iou:number;boundary_tolerance_ms:number};clip:{gt_count:number;retained_count:number;retention_recall:number|null;mean_gt_coverage:number|null;coverage_threshold:number;foreground_precision:number|null;foreground_recall:number|null;video_reduction:number|null;invalid_clip_count:number};ocr:Scores&{available:boolean;scored_matched_events:number;unknown_gt_count:number;eligible_readable_gt:number;total_readable_gt:number;end_to_end:Scores};condition_status:Scores&{available:boolean;accuracy:number|null;unknown_gt_count:number;evaluated_matched_events:number;end_to_end:Scores};conditions:Scores&{available:boolean;end_to_end:Scores};review_diagnostics:{linked_gt_count:number;manual_gt_count:number;rejected_prediction_count:number;event_fields_unchanged_count:number;event_fields_unchanged_ratio:number|null}}};
const pct=(value:number|null)=>value===null?'—':`${(value*100).toFixed(1)}%`;
const date=(value:string)=>new Date(value).toLocaleString('vi-VN');
const elapsed=(seconds:number|null)=>seconds===null?'—':seconds>=60?`${Math.floor(seconds/60)} phút ${(seconds%60).toFixed(1)} giây`:`${seconds.toFixed(1)} giây`;
type Metrics=Evaluation['metrics'];

function eventAssessment(m:Metrics):string[]{
 const e=m.events, c=m.clip;
 if(e.gt_count===0)return ['Chưa có event GT để đánh giá bước phát hiện. Hãy kiểm tra tập GT đã duyệt trước khi diễn giải các tỷ lệ.'];
 const lines=[`Model phát hiện đúng ${e.tp}/${e.gt_count} lượt xe GT, tạo ${e.fp} event dư và bỏ sót ${e.fn} lượt. Recall event là ${pct(e.recall)}${e.class_confusions?`; ${e.class_confusions} cặp ghép sai loại xe`:''}.`];
 if(e.matched)lines.push(`Các cặp ghép có temporal IoU trung bình ${pct(e.mean_temporal_iou)}; ${pct(e.within_boundary_tolerance)} có cả mốc đầu và cuối lệch không quá ${e.boundary_tolerance_ms} ms.`);
 lines.push(`Clip giữ đủ ít nhất ${pct(c.coverage_threshold)} thời lượng cho ${c.retained_count}/${c.gt_count} event GT. ${c.foreground_precision===null?'Chưa có thời gian clip hợp lệ để tính tỷ lệ hữu ích':`${pct(c.foreground_precision)} thời gian clip trùng với GT`}; video giảm ${pct(c.video_reduction)} thời lượng.${c.invalid_clip_count?` Có ${c.invalid_clip_count} clip bị đánh dấu lỗi.`:''}`);
 return lines;
}

function ocrAssessment(m:Metrics):string[]{
 const o=m.ocr;
 if(!o.available)return ['Nhánh OCR chưa có artifact trong run này, nên chưa thể đánh giá khả năng đọc biển số.'];
 const lines=o.scored_matched_events?[`Trong ${o.scored_matched_events} event ghép được và đủ nhãn biển, OCR đọc đúng ${o.tp} biển; có ${o.fp} kết quả biển dư hoặc sai và ${o.fn} biển đọc được nhưng chưa trả đúng.`]:['Chưa có event ghép được và đủ nhãn biển để chấm OCR riêng; hãy xem recall toàn pipeline nếu có GT đọc được.'];
 if(o.total_readable_gt)lines.push(`Tính từ video raw qua toàn pipeline, OCR trả đúng ${o.end_to_end.tp}/${o.total_readable_gt} biển GT đọc được (recall ${pct(o.end_to_end.recall)}); chỉ số này tính cả xe bị bước event bỏ sót.`);
 else lines.push('Không có biển GT được xác nhận là đọc được để tính recall OCR toàn pipeline.');
 if(o.unknown_gt_count)lines.push(`${o.unknown_gt_count} GT biển thiếu hoặc mâu thuẫn thông tin nên chưa được chấm; cần kiểm tra lại nhãn trước khi kết luận.`);
 return lines;
}

function conditionAssessment(m:Metrics):string[]{
 const s=m.condition_status, c=m.conditions;
 if(!s.available&&!c.available)return ['Nhánh CV–VLM chưa có artifact trong run này, nên chưa thể đánh giá điều kiện biển số.'];
 const lines=s.evaluated_matched_events?[`Trên ${s.evaluated_matched_events} event ghép được và có GT hợp lệ, trạng thái good/unreadable đúng ${pct(s.accuracy)}.`]:['Chưa có event ghép được và có GT điều kiện hợp lệ để tính độ đúng good/unreadable.'];
 const unreadableCount=s.end_to_end.tp+s.end_to_end.fn;
 lines.push(unreadableCount?`Toàn pipeline phát hiện đúng ${s.end_to_end.tp}/${unreadableCount} trường hợp GT unreadable (recall ${pct(s.end_to_end.recall)}), kể cả xe bị bước event bỏ sót.`:'Không có GT unreadable để tính recall cho trạng thái này; dấu “—” không có nghĩa là 0% hoặc 100%.');
 const causeCount=c.end_to_end.tp+c.end_to_end.fn;
 lines.push(causeCount?`Với ba nguyên nhân lỗi, toàn pipeline phát hiện đúng ${c.end_to_end.tp}/${causeCount} nhãn GT (recall ${pct(c.end_to_end.recall)}); có ${c.fp} nhãn nguyên nhân gợi ý dư trên các event ghép được.`:'Không có nhãn nguyên nhân lỗi trong GT để tính recall nguyên nhân.');
 if(s.unknown_gt_count)lines.push(`${s.unknown_gt_count} GT điều kiện không hợp lệ chưa được chấm.`);
 return lines;
}

function Assessment({lines}:{lines:string[]}){
 return <div className="evaluationAssessment"><strong>Nhận xét từ kết quả</strong>{lines.map((line,index)=><p key={index}>{line}</p>)}</div>;
}

function MetricTable({title,score,available=true}:{title:string;score:Scores;available?:boolean}){
 return <div className="panel evaluationCard"><h2>{title}</h2>{available?<><div className="scoreGrid"><div><span>Precision</span><b>{pct(score.precision)}</b></div><div><span>Recall</span><b>{pct(score.recall)}</b></div><div><span>F1</span><b>{pct(score.f1)}</b></div></div><small>Đúng: {score.tp} · Dư: {score.fp} · Thiếu: {score.fn}</small></>:<p className="evaluationIntro">Nhánh model chưa chạy trên run này.</p>}</div>
}

export default function EvaluationPage({active}:{active:boolean}){
 const[runs,setRuns]=useState<RunItem[]>([]);
 const[selected,setSelected]=useState('');
 const[data,setData]=useState<Evaluation>();
 const[error,setError]=useState('');
 const load=async()=>{try{const all=await api.runs();setRuns(all.filter((r:RunItem)=>r.status==='COMPLETED'&&r.review_status==='REVIEWED'));setError('')}catch(e:any){setError(e.message)}};
 useEffect(()=>{if(active)void load()},[active]);
 useEffect(()=>{if(!selected){setData(undefined);return}let cancelled=false;setData(undefined);setError('');api.evaluation(selected).then(value=>{if(!cancelled)setData(value)}).catch(e=>{if(!cancelled)setError(e.message)});return()=>{cancelled=true}},[selected]);
 const back=()=>{setSelected('');void load()};

 if(!selected)return <><header className="pageHead"><div><span>ĐÁNH GIÁ GT ĐÃ DUYỆT</span><h1>Đánh giá model gợi ý</h1></div><button className="ghost" onClick={()=>void load()}><RefreshCw size={16}/>Làm mới</button></header>
 {error&&<div className="alert">{error}</div>}
 <section className="panel runTablePanel"><div className="panelHead"><div><span>DANH SÁCH RUN ĐÃ DUYỆT</span><h2>{runs.length} kết quả có thể đánh giá</h2></div><small>Bấm Chi tiết để xem metric so với GT cuối cùng.</small></div>
 {runs.length?<div className="tableScroll runTableScroll"><table className="runTable"><thead><tr><th>Run</th><th>Video</th><th>Thời gian</th><th>Camera / Làn</th><th>Event model</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{runs.map(run=><tr key={run.id}><td><b>{run.id}</b></td><td><b>{run.video_filename}</b></td><td>{date(run.created_at)}</td><td>{run.config?.camera?.camera_id||'—'} / {run.config?.camera?.lane_id||'—'}</td><td>{run.event_count}</td><td><span className="status reviewed">Đã duyệt</span></td><td><button className="primary compact" onClick={()=>setSelected(run.id)}>Chi tiết <ChevronRight size={14}/></button></td></tr>)}</tbody></table></div>:<div className="empty"><h3>Chưa có GT đã duyệt</h3><p>Hãy cập nhật và duyệt một run ở trang Kết quả & duyệt.</p></div>}
 </section></>;

 return <><header className="pageHead"><div><span>CHI TIẾT ĐÁNH GIÁ</span><h1>{data?.run.video_filename||runs.find(run=>run.id===selected)?.video_filename||selected}</h1></div><button className="ghost" onClick={back}><ArrowLeft size={16}/>Danh sách run</button></header>
 {error&&<div className="alert">{error}</div>}{!data&&!error&&<div className="loading">Đang tính metric…</div>}
 {data&&<><div className="summaryCards editorSummary"><div><span>Run</span><b>{data.run.id}</b></div><div><span>Trạng thái</span><span className="status reviewed">Đã duyệt</span></div><div><span>Event model</span><b>{data.metrics.events.prediction_count}</b></div><div><span>Event GT</span><b>{data.metrics.events.gt_count}</b></div></div>
 <p className="evaluationIntro">Đọc kết quả theo thứ tự xử lý trên video raw: phát hiện event và giữ clip → đọc biển số → đánh giá điều kiện. Các nhận xét bên dưới được tạo từ metric của run đang xem.</p>

 <section className="evaluationStage" aria-labelledby="evaluation-event-title">
  <div className="evaluationStageHead"><span className="evaluationStageNumber">01</span><div><h2 id="evaluation-event-title">Phát hiện event và giữ clip</h2><p>Ghép một-một với GT cùng camera, làn, chiều và temporal IoU ≥ {pct(data.metrics.events.min_temporal_iou)}. Sai loại xe tính một FP và một FN.</p></div></div>
  <div className="evaluationCards"><MetricTable title="Event đúng loại và thời gian" score={data.metrics.events}/></div>
  <div className="evaluationStagePanels">
   <section className="panel evaluationDetails"><h3>Sai số event và nguồn GT</h3><div className="scoreGrid"><div><span>GT / Event model</span><b>{data.metrics.events.gt_count} / {data.metrics.events.prediction_count}</b></div><div><span>Temporal IoU trung bình</span><b>{pct(data.metrics.events.mean_temporal_iou)}</b></div><div><span>Sai số đầu / cuối trung bình</span><b>{data.metrics.events.mean_start_error_ms?.toFixed(0)??'—'} / {data.metrics.events.mean_end_error_ms?.toFixed(0)??'—'} ms</b></div><div><span>Biên trong ±{data.metrics.events.boundary_tolerance_ms} ms</span><b>{pct(data.metrics.events.within_boundary_tolerance)}</b></div><div><span>Đúng loại xe</span><b>{pct(data.metrics.events.vehicle_type_accuracy)}</b><small>{data.metrics.events.class_confusions} cặp sai loại</small></div><div><span>Đúng crossed</span><b>{pct(data.metrics.events.crossed_accuracy)}</b></div><div><span>GT thêm thủ công / event đã loại</span><b>{data.metrics.review_diagnostics.manual_gt_count} / {data.metrics.review_diagnostics.rejected_prediction_count}</b></div><div><span>GT event giữ nguyên gợi ý</span><b>{data.metrics.review_diagnostics.event_fields_unchanged_count}/{data.metrics.review_diagnostics.linked_gt_count}</b></div></div></section>
   <section className="panel evaluationDetails"><h3>Giữ clip trên video raw</h3><div className="scoreGrid"><div><span>GT giữ đủ ≥{pct(data.metrics.clip.coverage_threshold)}</span><b>{data.metrics.clip.retained_count}/{data.metrics.clip.gt_count}</b><small>Recall: {pct(data.metrics.clip.retention_recall)}</small></div><div><span>Độ phủ GT trung bình</span><b>{pct(data.metrics.clip.mean_gt_coverage)}</b></div><div><span>Thời gian clip hữu ích</span><b>{pct(data.metrics.clip.foreground_precision)}</b><small>Phần GT được giữ: {pct(data.metrics.clip.foreground_recall)}</small></div><div><span>Giảm thời lượng video</span><b>{pct(data.metrics.clip.video_reduction)}</b></div><div><span>Clip lỗi</span><b>{data.metrics.clip.invalid_clip_count}</b></div></div><p>Clip ảo dùng thời gian dự kiến; MP4 dùng thời gian xuất thực tế. Các khoảng clip chồng nhau được hợp nhất trước khi tính.</p></section>
  </div>
  <Assessment lines={eventAssessment(data.metrics)}/>
  {data.metrics.review_diagnostics.linked_gt_count>0&&data.metrics.review_diagnostics.event_fields_unchanged_count===data.metrics.review_diagnostics.linked_gt_count&&<div className="notice">Toàn bộ {data.metrics.review_diagnostics.linked_gt_count} GT gắn event vẫn giữ nguyên thời gian, loại xe và crossed từ gợi ý. Điểm event thể hiện mức đồng thuận với GT đã duyệt; hãy bảo đảm các hàng này đã được kiểm tra trên video raw.</div>}
 </section>

 <section className="evaluationStage" aria-labelledby="evaluation-ocr-title">
  <div className="evaluationStageHead"><span className="evaluationStageNumber">02</span><div><h2 id="evaluation-ocr-title">Đọc biển số · OCR</h2><p>Chấm trên event ghép được và kiểm tra thêm recall từ đầu pipeline, tính cả xe bị bỏ sót. Không áp dụng cho bicycle.</p></div></div>
  <div className="evaluationCards"><MetricTable title="OCR · event ghép được" score={data.metrics.ocr} available={data.metrics.ocr.available}/></div>
  <section className="panel evaluationDetails"><h3>Toàn pipeline và dữ liệu GT biển</h3><div className="scoreGrid"><div><span>OCR toàn pipeline · recall</span><b>{data.metrics.ocr.available?pct(data.metrics.ocr.end_to_end.recall):'—'}</b><small>{data.metrics.ocr.total_readable_gt} GT có biển đọc được, tính cả xe bị bỏ sót</small></div><div><span>GT biển chưa thể chấm</span><b>{data.metrics.ocr.unknown_gt_count}</b><small>Thiếu hoặc mâu thuẫn giữa đọc được và chuỗi biển</small></div><div><span>Event ghép đủ nhãn biển</span><b>{data.metrics.ocr.scored_matched_events}</b></div></div></section>
  <Assessment lines={ocrAssessment(data.metrics)}/>
 </section>

 <section className="evaluationStage" aria-labelledby="evaluation-condition-title">
  <div className="evaluationStageHead"><span className="evaluationStageNumber">03</span><div><h2 id="evaluation-condition-title">Điều kiện biển số · CV–VLM</h2><p>Đánh giá trạng thái good/unreadable rồi ba nguyên nhân: capture_blur, plate_obstruction và lighting_issue. Không áp dụng cho bicycle.</p></div></div>
  <div className="evaluationCards"><MetricTable title="Trạng thái · unreadable" score={data.metrics.condition_status} available={data.metrics.condition_status.available}/><MetricTable title="Ba nguyên nhân điều kiện" score={data.metrics.conditions} available={data.metrics.conditions.available}/></div>
  <section className="panel evaluationDetails"><h3>Trạng thái và recall toàn pipeline</h3><div className="scoreGrid"><div><span>Đúng good / unreadable</span><b>{pct(data.metrics.condition_status.accuracy)}</b><small>{data.metrics.condition_status.evaluated_matched_events} event được chấm</small></div><div><span>Unreadable toàn pipeline · recall</span><b>{data.metrics.condition_status.available?pct(data.metrics.condition_status.end_to_end.recall):'—'}</b></div><div><span>Nguyên nhân toàn pipeline · recall</span><b>{data.metrics.conditions.available?pct(data.metrics.conditions.end_to_end.recall):'—'}</b></div><div><span>GT điều kiện không hợp lệ</span><b>{data.metrics.condition_status.unknown_gt_count}</b></div></div></section>
  <Assessment lines={conditionAssessment(data.metrics)}/>
 </section>
 <section className="evaluationStage" aria-labelledby="evaluation-cost-title">
  <div className="evaluationStageHead"><span className="evaluationStageNumber">04</span><div><h2 id="evaluation-cost-title">Chi phí xử lý</h2><p>Thời gian chạy của run tạo gợi ý model; không tính thời gian người dùng chỉnh sửa và duyệt GT.</p></div></div>
  <section className="panel evaluationDetails"><h3>Thời gian xử lý</h3><div className="scoreGrid">
   <div><span>Phát hiện / cắt clip</span><b>{elapsed(data.runtime.core_elapsed_seconds)}</b><small>{data.runtime.schema_version==='0.1.0'||data.runtime.scope==='step1_core_only'?'Run cũ: thời gian lõi chưa gồm khởi tạo model.':'Gồm khởi tạo model, phát hiện event và xuất clip.'}</small></div>
   <div><span>OCR biển số</span><b>{elapsed(data.runtime.ocr_elapsed_seconds)}</b><small>{data.runtime.ocr_elapsed_seconds===null?'Chưa ghi thời gian riêng hoặc nhánh chưa chạy.':'Thời gian nhánh phát hiện và đọc biển số.'}</small></div>
   <div><span>CV–VLM điều kiện</span><b>{elapsed(data.runtime.condition_elapsed_seconds)}</b><small>{data.runtime.condition_elapsed_seconds===null?'Chưa ghi thời gian riêng hoặc nhánh chưa chạy.':'Thời gian nhánh phân tích điều kiện.'}</small></div>
   <div><span>Tổng thời gian / video raw</span><b>{data.runtime.total_to_raw_ratio===null?'—':`${data.runtime.total_to_raw_ratio.toFixed(2)}×`}</b><small>Tổng chạy: {elapsed(data.runtime.scope==='full_pipeline'?data.runtime.elapsed_seconds:null)} · Video raw: {elapsed(data.runtime.raw_duration_seconds)}</small></div>
  </div><p>Tổng thời gian đo từ lúc bắt đầu run đến khi xong các nhánh đã bật; không tính chờ queue hoặc thời gian duyệt GT. Dấu “—” nghĩa là run chưa lưu số liệu của phần đó.</p></section>
 </section>
 <p className="evaluationIntro">Dấu “—” nghĩa là chưa có mẫu phù hợp hoặc nhánh model chưa chạy; không được hiểu là 0% hay 100%.</p></>}
 </>;
}
