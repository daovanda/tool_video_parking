import type {EventItem, RunResult} from './types';

export type ReviewFilter = 'all' | 'high' | 'ocr' | 'condition' | 'manual';
export type ReviewSort = 'priority' | 'timeline' | 'detector_confidence' | 'ease_score';
export type ReviewReason = {kind: 'event' | 'ocr' | 'condition' | 'manual'; label: string; weight: number};
export type ReviewRank = {score: number; reasons: ReviewReason[]};
export type EasePart = {label: string; score: number; weight: number; measured: boolean};
export type EaseScore = {score: number; parts: EasePart[]; measured: number};

const clamp01 = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;

// A transparent review heuristic. It is deliberately not called an accuracy
// probability: detector, OCR and VLM outputs are not jointly calibrated.
export function easeScore(event: EventItem, result: RunResult): EaseScore | null {
  if (event.track_id === -1) return null;
  const vehicle = detectorConfidence(event);
  const parts: EasePart[] = [{label: 'Xe', score: vehicle ?? 0, weight: .35, measured: vehicle !== null}];
  if (event.vehicle_type !== 'bicycle' && result.run.config?.plate_ocr_enabled) {
    const topPlate = event.plate_observations.map(item => clamp01(item.plate_confidence))
      .filter((value): value is number => value !== null).sort((a, b) => b - a).slice(0, 3);
    const plateDetector = topPlate.length ? topPlate.reduce((sum, value) => sum + value, 0) / topPlate.length : 0;
    const consensus = clamp01(event.suggestion?.plate_consensus_confidence) ?? 0;
    const support = Math.max(0, Number(event.suggestion?.plate_support_count) || 0);
    const ocrEvidence = consensus * Math.min(1, support / 2);
    parts.push({label: 'Biển + OCR', score: .5 * plateDetector + .5 * ocrEvidence,
      weight: .30, measured: Boolean(event.suggestion?.plate_analyzed)});
  }
  if (event.vehicle_type !== 'bicycle' && result.run.config?.condition_analysis_enabled) {
    const cvClean = clamp01(event.suggestion?.cv_clean_fraction) ?? 0;
    const vlmReadable = event.suggestion?.vlm_readable === true ? 1 : 0;
    const fusedReadable = event.suggestion?.plate_readable === true ? 1 : 0;
    parts.push({label: 'CV + VLM', score: .4 * cvClean + .4 * vlmReadable + .2 * fusedReadable,
      weight: .35, measured: Boolean(event.suggestion?.condition_analyzed)});
  }
  const weight = parts.reduce((sum, part) => sum + part.weight, 0);
  return {score: parts.reduce((sum, part) => sum + part.score * part.weight, 0) / weight,
    parts, measured: parts.filter(part => part.measured).length};
}

export function compareEaseScore(first: EventItem, second: EventItem, result: RunResult): number {
  const a = easeScore(first, result);
  const b = easeScore(second, result);
  if (!a && b) return 1;
  if (!b && a) return -1;
  return (a?.score ?? 0) - (b?.score ?? 0) || first.start_ms - second.start_ms ||
    first.event_id.localeCompare(second.event_id);
}

export function detectorConfidence(event: EventItem): number | null {
  const value = event.confidence_mean;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? value : null;
}

export function compareDetectorConfidence(first: EventItem, second: EventItem): number {
  const a = detectorConfidence(first);
  const b = detectorConfidence(second);
  // Manual GT and legacy events without a score follow scored predictions.
  if (a === null && b !== null) return 1;
  if (b === null && a !== null) return -1;
  return (a ?? 0) - (b ?? 0) || first.start_ms - second.start_ms ||
    first.event_id.localeCompare(second.event_id);
}

export const MIN_SIGNIFICANT_OVERLAP_MS = 500;
export const MIN_SIGNIFICANT_OVERLAP_RATIO = 0.20;

export function hasSignificantOverlap(first: EventItem, second: EventItem): boolean {
  if (first.event_id === second.event_id || first.camera_id !== second.camera_id ||
      first.lane_id !== second.lane_id) return false;
  const overlapMs = Math.max(0, Math.min(first.end_ms, second.end_ms) -
      Math.max(first.start_ms, second.start_ms));
  const shorterMs = Math.min(first.end_ms - first.start_ms, second.end_ms - second.start_ms);
  return shorterMs > 0 && overlapMs >= MIN_SIGNIFICANT_OVERLAP_MS &&
      overlapMs / shorterMs >= MIN_SIGNIFICANT_OVERLAP_RATIO;
}

// Rules rank review work, not model error probabilities. Use immutable predictions
// so typing into a GT row does not unexpectedly move that row.
export function reviewRank(event: EventItem, result: RunResult): ReviewRank {
  if (event.track_id === -1) return {score: 100, reasons: [{kind: 'manual', label: 'GT thêm thủ công', weight: 100}]};
  const reasons: ReviewReason[] = [];
  const add = (kind: ReviewReason['kind'], label: string, weight: number) => reasons.push({kind, label, weight});
  if (!event.crossed) add('event', 'Không qua line', 50);
  if ((event as EventItem & {motion_confirmed?: boolean}).motion_confirmed === false) add('event', 'Chưa xác nhận chuyển động', 50);
  if (result.events.some(other => hasSignificantOverlap(event, other))) {
    add('event', 'Chồng lấn đáng kể (≥500 ms và ≥20% event ngắn hơn)', 40);
  }
  const threshold = Number(result.run.config?.candidate_hits ?? 2);
  const hits = (event as EventItem & {hits?: number}).hits;
  if (typeof hits === 'number' && hits <= threshold + 1) add('event', 'Ít lần phát hiện', 20);
  if (event.vehicle_type !== 'bicycle') {
    if (result.run.config?.plate_ocr_enabled && !event.suggestion?.plate_text) add('ocr', 'OCR chưa có biển số', 20);
    if (result.run.config?.condition_analysis_enabled) {
      if (!event.suggestion?.condition_status) add('condition', 'Chưa có gợi ý điều kiện', 20);
      else if (event.suggestion.condition_status === 'unreadable') add('condition', 'Biển được gợi ý khó đọc', 15);
    }
  }
  return {score: reasons.reduce((sum, reason) => sum + reason.weight, 0), reasons};
}

export function matchesReviewFilter(rank: ReviewRank, filter: ReviewFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'high') return rank.reasons.some(reason => reason.kind === 'event' || reason.kind === 'manual');
  return rank.reasons.some(reason => reason.kind === filter);
}
