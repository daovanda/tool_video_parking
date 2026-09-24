import {useEffect,useState} from 'react';
import {Save} from 'lucide-react';
import {api} from './api';

export type AppSettings={schema_version:'0.1.0';run_defaults:{model:string;image_size:number;grace_seconds:number;pre_seconds:number;post_seconds:number;merge_gap_seconds:number;plate_model:string;plate_class_name:string;plate_confidence:number;plate_top_k:number;plate_min_gap_ms:number;ocr_model:string;condition_vlm_model:string;condition_max_frames:number};evaluation:{min_temporal_iou:number;boundary_tolerance_ms:number;coverage_threshold:number}};

function Field({label,description,value,onChange,step,min,max}:{label:string;description:string;value:string|number;onChange:(value:string|number)=>void;step?:string;min?:number;max?:number}){
 return <label className="settingsField"><span>{label}</span><small>{description}</small><input type={typeof value==='number'?'number':'text'} value={value} step={step} min={min} max={max} onChange={event=>onChange(typeof value==='number'?Number(event.target.value):event.target.value)}/></label>;
}

export default function SettingsPage({active,onSaved}:{active:boolean;onSaved:(value:AppSettings)=>void}){
 const[settings,setSettings]=useState<AppSettings>();
 const[baseline,setBaseline]=useState('');
 const[busy,setBusy]=useState(false);
 const[error,setError]=useState('');
 const[message,setMessage]=useState('');
 useEffect(()=>{if(!active||settings)return;let cancelled=false;api.settings().then((value:AppSettings)=>{if(cancelled)return;setSettings(value);setBaseline(JSON.stringify(value));setError('')}).catch((e:Error)=>{if(!cancelled)setError(e.message)});return()=>{cancelled=true}},[active,settings]);
 const updateRun=(key:keyof AppSettings['run_defaults'],value:string|number)=>setSettings(current=>current?{...current,run_defaults:{...current.run_defaults,[key]:value}}:current);
 const updateEvaluation=(key:keyof AppSettings['evaluation'],value:number)=>setSettings(current=>current?{...current,evaluation:{...current.evaluation,[key]:value}}:current);
 const save=async()=>{if(!settings)return;setBusy(true);setError('');setMessage('');try{const saved:AppSettings=await api.saveSettings(settings);setSettings(saved);setBaseline(JSON.stringify(saved));onSaved(saved);setMessage('Đã lưu cài đặt. Run mới dùng các giá trị mặc định này; điểm đánh giá được tính lại khi mở chi tiết.')}catch(e:any){setError(e.message)}finally{setBusy(false)}};
 const changed=!!settings&&JSON.stringify(settings)!==baseline;
 return <><header className="pageHead"><div><span>WORKSPACE</span><h1>Cài đặt</h1></div><button className="primary" onClick={()=>void save()} disabled={!changed||busy}><Save size={16}/>Lưu cài đặt</button></header>
 {error&&<div className="alert">{error}</div>}{message&&<div className="notice">{message}</div>}
 {!settings?<div className="loading">Đang tải cài đặt…</div>:<>
 <p className="evaluationIntro">Các giá trị xử lý bên dưới là mặc định cho <b>run tạo sau khi lưu</b>. Run cũ giữ nguyên cấu hình đã chạy. Các ngưỡng đánh giá áp dụng khi mở lại trang Đánh giá, kể cả với run đã duyệt.</p>
 <div className="settingsSections">
 <section className="panel"><h2>Event và clip</h2><div className="settingsGrid">
  <Field label="Model phương tiện" description="Weights YOLO cho car, motorcycle, bicycle." value={settings.run_defaults.model} onChange={v=>updateRun('model',v)}/>
  <Field label="Input detector (px)" description="Kích thước ảnh đưa vào detector." value={settings.run_defaults.image_size} min={1} onChange={v=>updateRun('image_size',v)}/>
  <Field label="Grace (giây)" description="Chờ xe quay lại sau khi mất detection trước khi đóng event." value={settings.run_defaults.grace_seconds} min={0} step="0.1" onChange={v=>updateRun('grace_seconds',v)}/>
  <Field label="Buffer trước (giây)" description="Giữ thêm video trước event." value={settings.run_defaults.pre_seconds} min={0} step="0.1" onChange={v=>updateRun('pre_seconds',v)}/>
  <Field label="Buffer sau (giây)" description="Giữ thêm video sau event." value={settings.run_defaults.post_seconds} min={0} step="0.1" onChange={v=>updateRun('post_seconds',v)}/>
  <Field label="Khoảng gộp clip (giây)" description="Gộp các đoạn clip nếu cách nhau không quá ngưỡng này." value={settings.run_defaults.merge_gap_seconds} min={0} step="0.1" onChange={v=>updateRun('merge_gap_seconds',v)}/>
 </div></section>
 <section className="panel"><h2>Biển số và OCR</h2><div className="settingsGrid">
  <Field label="Model phát hiện biển" description="Weights YOLO chạy trong crop xe." value={settings.run_defaults.plate_model} onChange={v=>updateRun('plate_model',v)}/>
  <Field label="Tên class biển" description="Tên class biển số trong model phát hiện." value={settings.run_defaults.plate_class_name} onChange={v=>updateRun('plate_class_name',v)}/>
  <Field label="Confidence biển" description="Ngưỡng confidence khi phát hiện biển." value={settings.run_defaults.plate_confidence} min={0} max={1} step="0.01" onChange={v=>updateRun('plate_confidence',v)}/>
  <Field label="Top-K frame OCR" description="Số frame biển chất lượng cao tối đa trên mỗi event." value={settings.run_defaults.plate_top_k} min={1} onChange={v=>updateRun('plate_top_k',v)}/>
  <Field label="Khoảng cách frame OCR (ms)" description="Khoảng cách tối thiểu giữa các frame được chọn." value={settings.run_defaults.plate_min_gap_ms} min={0} onChange={v=>updateRun('plate_min_gap_ms',v)}/>
  <Field label="Model OCR" description="Tên model nhận dạng ký tự biển số." value={settings.run_defaults.ocr_model} onChange={v=>updateRun('ocr_model',v)}/>
 </div></section>
 <section className="panel"><h2>Điều kiện CV–VLM</h2><div className="settingsGrid">
  <Field label="Model VLM" description="Đường dẫn hoặc tên model phân tích điều kiện." value={settings.run_defaults.condition_vlm_model} onChange={v=>updateRun('condition_vlm_model',v)}/>
  <Field label="Frame / event" description="Số frame tối đa chọn cho VLM, từ 1 đến 5." value={settings.run_defaults.condition_max_frames} min={1} max={5} onChange={v=>updateRun('condition_max_frames',v)}/>
 </div></section>
 <section className="panel"><h2>Ngưỡng đánh giá</h2><p className="evaluationIntro">Thay đổi nhóm này không chạy lại model hoặc sửa GT; nó thay đổi cách ghép và chấm điểm khi mở lại kết quả đánh giá.</p><div className="settingsGrid">
  <Field label="Temporal IoU tối thiểu" description="Độ giao thời gian tối thiểu để ghép event dự đoán với GT." value={settings.evaluation.min_temporal_iou} min={0.01} max={1} step="0.01" onChange={v=>updateEvaluation('min_temporal_iou',Number(v))}/>
  <Field label="Dung sai biên (ms)" description="Chỉ dùng cho tỷ lệ mốc đầu/cuối nằm trong dung sai; không quyết định ghép." value={settings.evaluation.boundary_tolerance_ms} min={0} onChange={v=>updateEvaluation('boundary_tolerance_ms',Number(v))}/>
  <Field label="Độ phủ clip đủ giữ" description="Tỷ lệ tối thiểu thời gian một GT phải nằm trong clip." value={settings.evaluation.coverage_threshold} min={0.01} max={1} step="0.01" onChange={v=>updateEvaluation('coverage_threshold',Number(v))}/>
 </div></section>
 </div><div className="settingsBottom"><button className="primary" onClick={()=>void save()} disabled={!changed||busy}><Save size={16}/>Lưu cài đặt</button></div></>}
 </>;
}
