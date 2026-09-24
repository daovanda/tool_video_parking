import assert from 'node:assert/strict';
import test from 'node:test';
import {compareDetectorConfidence, compareEaseScore, detectorConfidence, easeScore,
  hasSignificantOverlap, reviewRank} from '../src/reviewPriority.ts';

const event = (id, start, end, overrides = {}) => ({
  event_id: id, start_ms: start, end_ms: end, camera_id: 'CAM01',
  lane_id: 'ENTRY_01', track_id: Number(id), vehicle_type: 'car',
  crossed: true, suggestion: {}, ...overrides,
});

test('tiny overlap does not promote an event', () => {
  const first = event('1', 0, 1000);
  for (const ms of [1, 499]) {
    const second = event('2', 1000 - ms, 2000);
    assert.equal(hasSignificantOverlap(first, second), false);
    const result = {events: [first, second], run: {config: {}}};
    assert.equal(reviewRank(first, result).score, 0);
  }
});

test('overlap must meet both absolute and relative thresholds', () => {
  assert.equal(hasSignificantOverlap(event('1', 0, 10000), event('2', 9500, 19500)), false);
  assert.equal(hasSignificantOverlap(event('1', 0, 2000), event('2', 1500, 3500)), true);
  assert.equal(hasSignificantOverlap(event('1', 0, 2000), event('2', 1500, 3500,
    {lane_id: 'ENTRY_02'})), false);
});

test('detector confidence sorts low to high, missing values last', () => {
  const low = event('1', 100, 200, {confidence_mean: 0.23});
  const high = event('2', 0, 100, {confidence_mean: 0.91});
  const missing = event('3', 50, 150);
  assert.deepEqual([high, missing, low].sort(compareDetectorConfidence).map(item => item.event_id),
    ['1', '2', '3']);
  assert.equal(detectorConfidence(event('4', 0, 100, {confidence_mean: NaN})), null);
  assert.equal(detectorConfidence(event('5', 0, 100, {confidence_mean: 1.2})), null);
});

test('ease score combines vehicle, plate/OCR and CV/VLM evidence', () => {
  const result = {run: {config: {plate_ocr_enabled: true, condition_analysis_enabled: true}}};
  const first = event('1', 0, 1000, {confidence_mean: .8,
    plate_observations: [{plate_confidence: .8}, {plate_confidence: .6},
      {plate_confidence: .4}, {plate_confidence: .1}],
    suggestion: {plate_analyzed: true, plate_consensus_confidence: .9,
      plate_support_count: 2, condition_analyzed: true, cv_clean_fraction: .5,
      vlm_readable: true, plate_readable: true}});
  const score = easeScore(first, result);
  assert.ok(Math.abs(score.score - .785) < 1e-10);
  assert.equal(score.measured, 3);
  assert.deepEqual(score.parts.map(part => part.score), [.8, .75, .8]);
  const harder = event('2', 1000, 2000, {confidence_mean: .7, plate_observations: [], suggestion: {}});
  assert.equal(compareEaseScore(harder, first, result) < 0, true);
});

test('disabled branches and bicycle are excluded; missing enabled evidence is low', () => {
  const vehicle = event('1', 0, 1000, {confidence_mean: .8, plate_observations: []});
  assert.ok(Math.abs(easeScore(vehicle, {run: {config: {}}}).score - .8) < 1e-10);
  assert.ok(Math.abs(easeScore({...vehicle, vehicle_type: 'bicycle'},
    {run: {config: {plate_ocr_enabled: true, condition_analysis_enabled: true}}}).score - .8) < 1e-10);
  const missing = easeScore(vehicle, {run: {config: {
    plate_ocr_enabled: true, condition_analysis_enabled: true}}});
  assert.ok(Math.abs(missing.score - .28) < 1e-10);
  assert.equal(missing.measured, 1);
  assert.equal(easeScore(event('manual', 0, 1000, {track_id: -1}),
    {run: {config: {}}}), null);
});
