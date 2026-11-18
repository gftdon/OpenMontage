// Static instruction/fixture contract only: not runtime AI efficacy, media QC,
// an AIOS parser integration test, or proof that any footage was measured.
// Run: node --test tests/video-qc-gg-short-contract.test.mjs
// AIOS may import/copy syntheticInput and syntheticReports without reading files.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const files = {
  md: '.claude/agents/video-qc-gg-short.md',
  toml: '.codex/agents/video-qc-gg-short.toml',
  rubric: 'docs/video-qc/rubric-gg-short.md',
};
function read(kind) {
  const path = new URL(files[kind], root);
  assert.ok(existsSync(path), `Missing approved contract artifact: ${fileURLToPath(path)}`);
  return readFileSync(path, 'utf8');
}
function body() {
  const match = read('md').match(/^---\n([\s\S]*?)\n---\n\n([\s\S]*)$/);
  assert.ok(match, 'Agent must have YAML frontmatter followed by its instruction body');
  return { frontmatter: match[1], instructions: match[2] };
}
function contract() {
  const match = read('rubric').match(/```json contract\n([\s\S]*?)\n```/);
  assert.ok(match, 'Rubric must expose the locked machine-readable contract');
  return JSON.parse(match[1]);
}

export const syntheticInput = {
  schema: 1, report_id: 'synthetic-gg-001',
  do_not_copy: ['The midnight glass elevator', 'A mirrored city folds into a paper crane'],
};
const categoryScores = {
  hook: 18, visual: 22.5, text: 14.25, story_pacing: 14.25, audio: 9, originality: 9, technical: 5,
}; // Hand-checked sum: 92.
const complete = {
  synthetic: true, // Every number/timecode/path below is invented fixture data, not an observation.
  agent: 'video-qc-gg-short', rubric_version: 'gg-short-v1',
  report_id: 'synthetic-gg-001', video_code: 'GG_SYNTH_001',
  inputs: {
    final_path: '/synthetic/GG_SYNTH_001_40_Short_Final.mp4',
    qc_input_path: '/synthetic/qc-input.json',
  },
  report_path: '/synthetic/GG_SYNTH_001_50_QC.json',
  scoring_status: 'complete', total: 92, verdict: 'PASS', category_scores: categoryScores,
  work_dir: '/synthetic/qc-work-example',
  scoring_details: {
    hook: [{ check: 'opening clarity', level: 3.6, max: 10, points: 9, evidence_ids: ['E1'],
      rationale: 'Synthetic 3-to-4 interpolation: clear premise by 2.2s, slight reveal delay.' },
    { check: 'curiosity', level: 3.6, max: 10, points: 9, evidence_ids: ['E1'],
      rationale: 'Synthetic distinctive promise with a small explanatory hold.' }],
    visual: [{ check: 'continuity', level: 3.6, max: 12.5, points: 11.25, evidence_ids: ['E1'],
      rationale: 'Synthetic consistent identity, minor transition distraction (3-to-4).' },
    { check: 'composition', level: 3.6, max: 12.5, points: 11.25, evidence_ids: ['E1'],
      rationale: 'Synthetic controlled focus with localized excess movement (3-to-4).' }],
    text: [{ check: 'legibility', level: 3.6, max: 7.5, points: 6.75, evidence_ids: ['E1'],
      rationale: 'Synthetic readable safe text, localized tight hold (3-to-4).' },
    { check: 'English precision', level: 4, max: 7.5, points: 7.5, evidence_ids: ['E1'],
      rationale: 'Synthetic concise correct English inventory.' }],
    story_pacing: [{ check: 'progression', level: 3.6, max: 7.5, points: 6.75, evidence_ids: ['E1'],
      rationale: 'Synthetic clear arc with localized delayed setup (3-to-4).' },
    { check: 'rhythm', level: 4, max: 7.5, points: 7.5, evidence_ids: ['E3'],
      rationale: 'Synthetic motivated pauses and satisfying close.' }],
    audio: [{ check: 'objective levels', level: 3.6, max: 5, points: 4.5, evidence_ids: ['E2', 'E3', 'E4'],
      rationale: 'Synthetic compliant levels and measured/image-reviewed integrity; localized RMS irregularity explained (3-to-4).' },
    { check: 'objective continuity/end', level: 3.6, max: 5, points: 4.5, evidence_ids: ['E2', 'E5', 'E6'],
      rationale: 'Synthetic endpoint alignment and supported fade; localized tail transient explained (3-to-4), no perceptual claim.' }],
    originality: [{ check: 'exclusions', level: 3.6, max: 5, points: 4.5, evidence_ids: ['E1'],
      rationale: 'Synthetic distinct compared beats with familiar framing (3-to-4).' },
    { check: 'specificity', level: 3.6, max: 5, points: 4.5, evidence_ids: ['E1'],
      rationale: 'Synthetic specific concept with localized generic transition (3-to-4).' }],
    technical: [{ check: 'format', level: 4, max: 2.5, points: 2.5, evidence_ids: ['E2'],
      rationale: 'Synthetic clean specs, timestamps and endpoints.' },
    { check: 'integrity', level: 4, max: 2.5, points: 2.5, evidence_ids: ['E2', 'E3'],
      rationale: 'Synthetic clean decode, all detector intervals reviewed.' }],
  },
  criticals: [],
  issues: [{ id: 'I1', description: 'Synthetic hook reveal arrives slightly late.',
    severity: 'minor', start_s: 0, end_s: 2.2, evidence_ids: ['E1'] }],
  evidence: [
    { id: 'E1', kind: 'frame_review', start_s: 0, end_s: 2.2,
      artifact: '/synthetic/qc-work-example/opening.png',
      observation: 'Synthetic frame review of English opening text and original reveal.' },
    { id: 'E2', kind: 'measurement', start_s: 0, end_s: 32,
      artifact: '/synthetic/qc-work-example/measurements.log',
      observation: 'Synthetic probe, decode and filter summary; no actual file was processed.' },
    { id: 'E3', kind: 'audio_image_review', generator: 'showwavespic',
      personally_inspected: true, settings: 's=1920x480:split_channels=1', start_s: 0, end_s: 32,
      artifact: '/synthetic/qc-work-example/waveform.png',
      observation: 'Synthetic inspected full waveform: no unexplained discontinuity; no perceptual claim.' },
    { id: 'E4', kind: 'audio_image_review', generator: 'showspectrumpic',
      personally_inspected: true, settings: 's=1920x1080:legend=1', start_s: 0, end_s: 32,
      artifact: '/synthetic/qc-work-example/spectrum.png',
      observation: 'Synthetic inspected spectrum; patterns are leads, not proof of perceived noise.' },
    { id: 'E5', kind: 'audio_image_review', generator: 'showwavespic',
      personally_inspected: true, settings: 's=1920x480:split_channels=1', start_s: 30.8, end_s: 32,
      artifact: '/synthetic/qc-work-example/tail-waveform.png',
      observation: 'Synthetic tail envelope decays, not active-level truncation.' },
    { id: 'E6', kind: 'audio_image_review', generator: 'showspectrumpic',
      personally_inspected: true, settings: 's=1920x1080:legend=1', start_s: 30.8, end_s: 32,
      artifact: '/synthetic/qc-work-example/tail-spectrum.png',
      observation: 'Synthetic tail spectrum attenuation supports measured decay only.' },
  ],
  category_evidence: {
    hook: ['E1'], visual: ['E1'], text: ['E1'], story_pacing: ['E1', 'E3'],
    audio: ['E2', 'E3'], originality: ['E1'], technical: ['E2'],
  },
  measurements: {
    width: 1080, height: 1920, fps: 30, duration_s: 32,
    integrated_lufs: -14.2, true_peak_dbtp: -1.7, full_decode: 'ok',
    video_streams: 1, audio_streams: 1, lra_lu: 4.2,
    astats: { sample_peak_dbfs: -1.9, rms_dbfs: -17, dc_offset: 0.0001, peak_count: 2,
      clipping_indications: [],
      channels: [
        { channel: 1, sample_peak_dbfs: -1.9, rms_dbfs: -17, dc_offset: 0.0001, peak_count: 2 },
        { channel: 2, sample_peak_dbfs: -2, rms_dbfs: -17.1, dc_offset: -0.0001, peak_count: 1 },
      ],
      windows: [{ start_s: 0, end_s: 32, sample_peak_dbfs: -1.9, rms_dbfs: -17,
        dc_offset: 0.0001, peak_count: 2 }], evidence_ids: ['E2'] },
    duration_alignment: { audio_start_s: 0, video_start_s: 0, audio_end_s: 32, video_end_s: 32,
      raw_audio_start_s: -0.0213333, raw_audio_end_s: 32, encoder_delay_samples: 1024,
      sample_rate: 48000, audio_frame_duration_s: 0.0213333,
      start_delta_s: 0, end_delta_s: 0, tolerance_s: 1 / 30,
      derivation: 'max(1/30,1024/48000), declared encoder delay removed',
      status: 'aligned', evidence_ids: ['E2'] },
    ending_fade: {
      windows: [
        [30.8, 30.9, -18, -6], [30.9, 31, -19, -7], [31, 31.1, -20, -8],
        [31.1, 31.2, -21, -9], [31.2, 31.3, -22, -10], [31.3, 31.4, -24, -12],
        [31.4, 31.5, -26, -14], [31.5, 31.6, -29, -17], [31.6, 31.7, -33, -21],
        [31.7, 31.8, -38, -26], [31.8, 31.9, -45, -33], [31.9, 32, -56, -44],
      ].map(([start_s, end_s, rms_dbfs, peak_dbfs]) =>
        ({ start_s, end_s, rms_dbfs, peak_dbfs, sample_count: 4800 })),
      final_20ms: { start_s: 31.98, end_s: 32, rms_dbfs: -65, peak_dbfs: -58, sample_count: 960 },
      last_sample: [0.00001, -0.00001], status: 'verified_decay',
      rationale: 'Synthetic measured envelope and both tail images support decay to observed floor.',
      evidence_ids: ['E2', 'E5', 'E6'],
    },
    silencedetect: [], blackdetect: [], freezedetect: [], evidence_ids: ['E2'],
  },
  coverage: {
    frame_times_s: [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
      15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 31.9667],
    full_audio_review: false, objective_audio_review: true, content_verified: true,
    limitation: 'Synthetic example only; no subjective listening. Sampling does not prove every frame is free of defects.',
    unverified: ['Intelligibility', 'Perceptual sync', 'Music quality'],
    audio_image_intervals: [[0, 32], [30.8, 32]],
  },
  originality: { status: 'no_observed_match', compared_input_indices: [0, 1],
    evidence_ids: ['E1'], limitation: 'Only supplied strings compared; not global originality proof.' },
  inputs_missing: [], tool_failures: [], fail_reasons: [],
};
const clone = (value) => structuredClone(value);
const at90 = clone(complete);
at90.category_scores.hook = 16; at90.total = 90; at90.verdict = 'FAIL';
at90.scoring_details.hook = [
  { check: 'opening clarity', level: 3.2, max: 10, points: 8, evidence_ids: ['E1'],
    rationale: 'Synthetic 3-to-4 interpolation: strong opening but reveal only just clears 3s.' },
  { check: 'curiosity', level: 3.2, max: 10, points: 8, evidence_ids: ['E1'],
    rationale: 'Synthetic 3-to-4 interpolation: strong promise with noticeable generic setup.' },
];
at90.fail_reasons = ['Total must be strictly greater than 90.'];
const at905 = clone(complete);
at905.category_scores.hook = 16.5; at905.total = 90.5;
at905.scoring_details.hook = [
  { check: 'opening clarity', level: 3.3, max: 10, points: 8.25, evidence_ids: ['E1'],
    rationale: 'Synthetic 3-to-4 interpolation: immediate focus, slightly delayed premise.' },
  { check: 'curiosity', level: 3.3, max: 10, points: 8.25, evidence_ids: ['E1'],
    rationale: 'Synthetic 3-to-4 interpolation: clear promise with a localized explanatory hold.' },
];
const critical = clone(complete);
critical.verdict = 'FAIL';
critical.evidence[0].observation = 'Synthetic full-size frame review: legible Spanish “Hola mundo” at 1..2s.';
critical.criticals = [{ code: 'NON_ENGLISH_TEXT', description: 'Synthetic visible Spanish text: Hola mundo.',
  start_s: 1, end_s: 2, evidence_ids: ['E1'], observed: 'Hola mundo', expected: 'English only' }];
critical.issues.push({ id: 'I2', description: 'Synthetic visible Spanish text: Hola mundo.',
  severity: 'critical', start_s: 1, end_s: 2, evidence_ids: ['E1'] });
critical.category_scores.text = 7.5;
critical.scoring_details.text[0] = { check: 'legibility', level: 4, max: 7.5, points: 7.5,
  evidence_ids: ['E1'], rationale: 'Synthetic Spanish text is fully legible inside safe zone.' };
critical.scoring_details.text[1] = { check: 'English precision', level: 0, max: 7.5, points: 0,
  evidence_ids: ['E1'], rationale: 'Synthetic visible non-English meaning violates this check.' };
critical.category_scores.hook = 20;
critical.category_scores.visual = 25;
critical.category_scores.story_pacing = 15;
critical.category_scores.audio = 10;
critical.category_scores.originality = 10;
for (const [key, points] of [['hook', 10], ['visual', 12.5], ['story_pacing', 7.5],
  ['audio', 5], ['originality', 5]]) {
  for (const check of critical.scoring_details[key]) {
    check.level = 4; check.points = points;
    check.rationale = 'Synthetic highest anchor fully supported for this separate check.';
  }
}
critical.total = 92.5;
critical.fail_reasons = ['Verified non-English viewer-visible text.'];
const failed = clone(complete);
failed.scoring_status = 'incomplete'; failed.total = 0; failed.verdict = 'FAIL';
failed.category_scores = Object.fromEntries(Object.keys(categoryScores).map((key) => [key, null]));
failed.scoring_details = null;
failed.category_evidence = Object.fromEntries(Object.keys(categoryScores).map((key) => [key, []]));
failed.measurements = null; failed.evidence = [];
failed.coverage = { frame_times_s: [], full_audio_review: false, objective_audio_review: false, content_verified: false,
  limitation: 'No media examined: synthetic tool failure.', unverified: ['All media checks'] };
failed.issues = [{ id: 'I1', description: 'Synthetic ffprobe executable unavailable.',
  severity: 'major', start_s: null, end_s: null, evidence_ids: [] }];
failed.originality = { status: 'unverified', compared_input_indices: [], evidence_ids: [],
  limitation: 'Content could not be inspected.' };
failed.tool_failures = [{ tool: 'ffprobe', error: 'Synthetic executable unavailable', exit_code: null }];
failed.fail_reasons = ['Measurement unavailable; total 0 is the unscored sentinel.'];
const missingAudio = clone(failed);
missingAudio.measurements = { audio_streams: 0, integrated_lufs: null, true_peak_dbtp: null };
missingAudio.evidence = [{ id: 'E2', kind: 'measurement', start_s: 0, end_s: 32,
  artifact: '/synthetic/qc-work-example/probe.log', observation: 'Synthetic ffprobe inventory: no audio stream.' }];
missingAudio.criticals = [{ code: 'SPEC', description: 'Synthetic missing audio stream.',
  start_s: 0, end_s: 32, evidence_ids: ['E2'], observed: 0, expected: 1 }];
missingAudio.issues = [{ id: 'I1', description: 'Synthetic missing audio stream.', severity: 'critical',
  start_s: 0, end_s: 32, evidence_ids: ['E2'] }];
missingAudio.tool_failures = [];
missingAudio.fail_reasons = ['Audio stream absent; objective audio cannot be scored.'];
const eburFailure = clone(failed);
eburFailure.measurements = { audio_streams: 1, integrated_lufs: null, true_peak_dbtp: null, lra_lu: null };
eburFailure.tool_failures = [{ tool: 'ebur128', error: 'Synthetic filter failure', exit_code: 1 }];
eburFailure.issues[0].description = 'Synthetic ebur128 failure; no loudness values invented.';
eburFailure.fail_reasons = ['Required ebur128 measurement failed.'];
const durationMismatch = clone(complete);
durationMismatch.measurements.duration_alignment.video_end_s = 31.9;
durationMismatch.measurements.duration_alignment.end_delta_s = 0.1;
durationMismatch.measurements.duration_alignment.status = 'confirmed_mismatch';
durationMismatch.criticals = [{ code: 'SPEC', description: 'Synthetic adjusted A/V endpoint mismatch exceeds tolerance.',
  start_s: 31.9, end_s: 32, evidence_ids: ['E2'], observed: 0.1, expected: 1 / 30 }];
durationMismatch.issues.push({ id: 'I2', description: durationMismatch.criticals[0].description,
  severity: 'critical', start_s: 31.9, end_s: 32, evidence_ids: ['E2'] });
durationMismatch.verdict = 'FAIL'; durationMismatch.fail_reasons = ['Confirmed duration mismatch: SPEC.'];
const missingFade = clone(complete);
missingFade.measurements.ending_fade.status = 'confirmed_missing_fade';
for (const window of missingFade.measurements.ending_fade.windows) {
  window.rms_dbfs = -18; window.peak_dbfs = -6;
}
missingFade.measurements.ending_fade.final_20ms.rms_dbfs = -18;
missingFade.measurements.ending_fade.final_20ms.peak_dbfs = -6;
missingFade.measurements.ending_fade.last_sample = [0.3, -0.3];
missingFade.measurements.ending_fade.rationale = 'Synthetic active-level tail remains flat through cutoff: no promised fade.';
for (const item of missingFade.evidence.filter((item) => ['E5', 'E6'].includes(item.id))) {
  item.observation = 'Synthetic tail image confirms active-level cutoff without ending fade.';
}
missingFade.criticals = [{ code: 'SPEC', description: 'Synthetic confirmed missing promised 1.2-second ending fade.',
  start_s: 30.8, end_s: 32, evidence_ids: ['E2', 'E5', 'E6'], observed: 'no decay', expected: '1.2-second fade-out' }];
missingFade.issues.push({ id: 'I2', description: missingFade.criticals[0].description,
  severity: 'critical', start_s: 30.8, end_s: 32, evidence_ids: ['E2', 'E5', 'E6'] });
missingFade.verdict = 'FAIL'; missingFade.fail_reasons = ['Confirmed missing ending fade: SPEC.'];
for (const report of [durationMismatch, missingFade]) {
  report.category_scores.audio = 5;
  report.scoring_details.audio[1].level = 0; report.scoring_details.audio[1].points = 0;
  report.scoring_details.audio[1].rationale = 'Synthetic verified objective ending/alignment spec failure.';
  report.scoring_details.audio[0].level = 4; report.scoring_details.audio[0].points = 5;
  report.scoring_details.audio[0].rationale = 'Synthetic compliant level measurements, separate from ending failure.';
  report.total = 88;
}
export const syntheticReports = {
  pass: complete, at90Fail: at90, at90_5Pass: at905, highScoreCriticalFail: critical,
  measurementFailureFail: failed, missingAudioStreamFail: missingAudio, ebur128FailureFail: eburFailure,
  durationMismatchFail: durationMismatch, missingEndingFadeFail: missingFade,
};

// Test-only consumer of the published contract, not a production QC validator.
function expectedVerdict(report, c) {
  const gate = c.pass_rule;
  assert.equal(gate.comparison, 'strictly_greater_than');
  return report.scoring_status === gate.scoring_status && report.total > gate.threshold
    && report.criticals.length === gate.critical_count ? 'PASS' : 'FAIL';
}
function validateFrameCadence(report) {
  const times = report.coverage.frame_times_s;
  const lastFrame = report.measurements.duration_s - 1 / report.measurements.fps;
  const tolerance = 0.0001; // Fixtures retain last-frame timestamps to four decimals.
  assert.equal(times[0], 0);
  for (let index = 0; index < times.length; index++) {
    assert.ok(Number.isFinite(times[index]) && times[index] >= 0);
    assert.ok(times[index] <= lastFrame + tolerance);
    if (index > 0) {
      const gap = times[index] - times[index - 1];
      assert.ok(gap > 0, 'Frame timestamps must be strictly increasing');
      const maxGap = times[index - 1] < 3 ? 0.5 : 1;
      assert.ok(gap <= maxGap + tolerance,
        `Missing required frame cadence between ${times[index - 1]} and ${times[index]}`);
    }
  }
  assert.ok(Math.abs(times.at(-1) - lastFrame) <= tolerance, 'Must inspect last decodable frame');
}
function validateCheckMaxima(report, c) {
  for (const [category, weight] of Object.entries(c.weights)) {
    for (const check of report.scoring_details[category]) {
      assert.equal(check.max, weight / 2, `${category}/${check.check} must declare its point maximum`);
      assert.ok(check.points >= 0 && check.points <= check.max);
    }
  }
}
function validateFixture(report, c) {
  for (const key of c.report_required) assert.ok(Object.hasOwn(report, key), `Missing ${key}`);
  assert.equal(report.agent, c.agent); assert.equal(report.rubric_version, c.rubric_version);
  assert.equal(report.report_id, syntheticInput.report_id);
  assert.equal(typeof report.total, 'number'); assert.ok(Number.isFinite(report.total));
  assert.ok(report.total >= 0 && report.total <= 100);
  assert.ok(['PASS', 'FAIL'].includes(report.verdict));
  assert.ok(report.inputs.final_path.endsWith(`${report.video_code}_40_Short_Final.mp4`));
  assert.ok(report.inputs.qc_input_path.endsWith('/qc-input.json'));
  assert.ok(report.report_path.endsWith(`${report.video_code}_50_QC.json`));
  assert.deepEqual(Object.keys(report.category_scores).sort(), Object.keys(c.weights).sort());
  if (report.scoring_status === 'incomplete') {
    assert.equal(report.total, c.incomplete.total);
    for (const score of Object.values(report.category_scores)) assert.equal(score, null);
    assert.equal(report.verdict, 'FAIL');
  } else {
    validateFrameCadence(report);
    validateCheckMaxima(report, c);
    let sum = 0;
    for (const [category, max] of Object.entries(c.weights)) {
      const score = report.category_scores[category];
      assert.equal(typeof score, 'number'); assert.ok(score >= 0 && score <= max);
      assert.ok(report.category_evidence[category].length > 0);
      const checks = report.scoring_details[category];
      assert.equal(checks.length, 2);
      assert.equal(score, checks.reduce((points, check) => points + check.points, 0));
      for (const check of checks) {
        assert.ok(check.level >= 0 && check.level <= 4);
        assert.ok(Math.abs(check.points - max * check.level / 8) < 1e-10);
      }
      sum += score;
    }
    assert.equal(report.total, sum);
    assert.equal(report.coverage.content_verified, true);
    assert.equal(report.coverage.objective_audio_review, true);
    assert.equal(report.measurements.audio_streams, 1);
    for (const field of ['integrated_lufs', 'true_peak_dbtp', 'lra_lu']) {
      assert.ok(Number.isFinite(report.measurements[field]), `Missing ${field}`);
    }
    for (const field of ['astats', 'duration_alignment', 'ending_fade']) {
      assert.ok(report.measurements[field] != null, `Missing ${field}`);
    }
    const astats = report.measurements.astats;
    assert.ok(astats.channels.length > 0);
    for (const values of [astats, ...astats.channels, ...astats.windows]) {
      for (const field of ['sample_peak_dbfs', 'rms_dbfs', 'dc_offset', 'peak_count']) {
        assert.ok(Number.isFinite(values[field]), `Missing astats ${field}`);
      }
    }
    assert.ok(astats.windows.length > 0);
    const alignment = report.measurements.duration_alignment;
    assert.ok(['aligned', 'confirmed_mismatch'].includes(alignment.status));
    assert.equal(alignment.tolerance_s, Math.max(1 / 30, alignment.audio_frame_duration_s));
    const mismatch = Math.abs(alignment.start_delta_s) > alignment.tolerance_s
      || Math.abs(alignment.end_delta_s) > alignment.tolerance_s;
    assert.equal(alignment.status, mismatch ? 'confirmed_mismatch' : 'aligned');
    if (mismatch) assert.ok(report.criticals.some((item) => item.code === 'SPEC'));
    const fade = report.measurements.ending_fade;
    assert.ok(['verified_decay', 'confirmed_missing_fade'].includes(fade.status));
    if (fade.status === 'confirmed_missing_fade') {
      assert.ok(report.criticals.some((item) => item.code === 'SPEC'));
    }
    assert.equal(fade.windows.length, 12);
    assert.ok(Math.abs(fade.windows[0].start_s - (alignment.audio_end_s - 1.2)) < 1e-9);
    for (let index = 0; index < fade.windows.length; index++) {
      const window = fade.windows[index];
      assert.ok(Math.abs(window.end_s - window.start_s - 0.1) < 1e-9);
      if (index > 0) assert.equal(window.start_s, fade.windows[index - 1].end_s);
    }
    assert.equal(fade.windows.at(-1).end_s, alignment.audio_end_s);
    assert.ok(Math.abs(fade.final_20ms.end_s - fade.final_20ms.start_s - 0.02) < 1e-9);
    assert.ok(fade.last_sample.length > 0);
    for (const generator of ['showwavespic', 'showspectrumpic']) {
      for (const [start, end] of [[0, alignment.audio_end_s],
        [alignment.audio_end_s - 1.2, alignment.audio_end_s]]) {
        assert.ok(report.evidence.some((item) => item.generator === generator
          && item.personally_inspected === true && Math.abs(item.start_s - start) < 1e-9
          && item.end_s === end), `Missing inspected ${generator} ${start}..${end}`);
      }
    }
  }
  const ids = new Set(report.evidence.map((e) => e.id));
  for (const item of [...report.issues, ...report.criticals]) {
    assert.equal(typeof item.description, 'string');
    for (const id of item.evidence_ids) assert.ok(ids.has(id), `Dangling evidence ${id}`);
  }
  for (const item of report.criticals) {
    assert.ok(c.critical_codes.includes(item.code));
    assert.ok(item.evidence_ids.length > 0);
    assert.ok(item.start_s >= 0 && item.end_s >= item.start_s);
  }
  for (const item of report.issues) {
    assert.equal(typeof item.id, 'string');
    assert.ok(['minor', 'major', 'critical'].includes(item.severity));
  }
  assert.equal(report.verdict, expectedVerdict(report, c));
}

test('agent identity and exact decoded TOML mirror cannot drift', () => {
  const { frontmatter, instructions } = body();
  assert.match(frontmatter, /^name: video-qc-gg-short$/m);
  assert.doesNotMatch(frontmatter, /^model:/m);
  const toml = read('toml');
  assert.match(toml, /^name = "video-qc-gg-short"$/m);
  assert.doesNotMatch(toml, /^model\s*=/m);
  const encoded = toml.match(/^developer_instructions = (".*")$/m);
  assert.ok(encoded, 'Use one JSON-quoted TOML basic string for deterministic decoding');
  assert.equal(JSON.parse(encoded[1]), instructions);
  assert.ok(instructions.includes(files.rubric));
  assert.match(instructions, /qc-input\.json/);
  assert.match(instructions, /gg-short-v1/);
});

test('published scoring gate and input/report schemas preserve locked boundaries', () => {
  const c = contract();
  assert.equal(c.agent, 'video-qc-gg-short'); assert.equal(c.rubric_version, 'gg-short-v1');
  assert.deepEqual(c.weights, { hook: 20, visual: 25, text: 15, story_pacing: 15,
    audio: 10, originality: 10, technical: 5 });
  assert.equal(Object.values(c.weights).reduce((a, b) => a + b), 100);
  assert.deepEqual(c.pass_rule, { comparison: 'strictly_greater_than', threshold: 90,
    critical_count: 0, scoring_status: 'complete' });
  assert.equal(c.category_floors, null);
  assert.deepEqual(c.input, { filename: 'qc-input.json', schema: 1,
    report_id: 'nonempty_string', do_not_copy: { min_items: 1, max_items: 20, item: 'nonempty_string' } });
  assert.deepEqual(c.incomplete, { total: 0, scoring_status: 'incomplete', category_scores: null });
  for (const field of ['agent', 'rubric_version', 'report_id', 'video_code', 'total', 'verdict',
    'criticals', 'issues', 'category_scores', 'category_evidence', 'evidence', 'measurements',
    'coverage', 'originality', 'inputs', 'report_path', 'inputs_missing', 'tool_failures', 'fail_reasons',
    'scoring_status']) assert.ok(c.report_required.includes(field), `Required report field ${field}`);
});

test('spec, safe zone and critical gates cannot silently relax', () => {
  const c = contract();
  assert.deepEqual(c.spec, { width: 1080, height: 1920, fps: 30, duration_s: [10, 90],
    integrated_lufs: [-15, -13], true_peak_max_dbtp: -1, video_streams: 1, audio_streams: 1 });
  assert.deepEqual(c.safe_zone, { x0: 90, y0: 210, x1: 990, y1: 1600 });
  assert.deepEqual(c.critical_codes, ['SPEC', 'AI_INCONSISTENCY', 'TEXT_READABILITY', 'SAFE_ZONE',
    'NON_ENGLISH_TEXT', 'COPYING', 'LOUDNESS', 'TRUE_PEAK', 'CONTENT_BROKEN']);
  const rubric = read('rubric');
  for (const required of ['Latin non-English', 'numbers and punctuation are not letters',
    'not automatic', 'timecode', 'uncertain', 'supplied strings', 'Sampling does not prove every frame',
    '0.5', 'interpolate', 'No per-category floors']) assert.ok(rubric.includes(required), required);
});

test('local inspection and isolation instructions stay independent and fail closed', () => {
  const { instructions } = body();
  for (const required of ['ffprobe', 'ffmpeg', 'ebur128=peak=true', 'silencedetect', 'blackdetect',
    'freezedetect', 'full decode', 'inspect frames yourself', 'objective_audio_review', 'Python -I',
    'untrusted data', 'no overwrites', 'result.json', 'previous QC reports', 'production QA',
    'no network', 'no database', 'no secrets', 'yt-dlp', 'exclusive', 'symlink', 'argument arrays',
    'scoring_status', 'incomplete', 'null', 'total 0', 'LRA', 'never invent', 'do_not_copy']) {
    assert.ok(instructions.includes(required), `Missing safety/evidence rule: ${required}`);
  }
  assert.doesNotMatch(instructions, /gemini|opus|sonnet|gpt-\d|model\s*[:=]/i);
});

for (const [name, verdict, total] of [
  ['pass', 'PASS', 92], ['at90Fail', 'FAIL', 90], ['at90_5Pass', 'PASS', 90.5],
  ['highScoreCriticalFail', 'FAIL', 92.5], ['measurementFailureFail', 'FAIL', 0],
]) {
  test(`synthetic ${name} demonstrates ${total} => ${verdict}`, () => {
    const report = syntheticReports[name]; validateFixture(report, contract());
    assert.equal(report.verdict, verdict); assert.equal(report.total, total);
  });
}

test('complete synthetic coverage includes opening cadence, every later second and last frame', () => {
  for (const report of Object.values(syntheticReports)) {
    if (report.scoring_status === 'complete') validateFrameCadence(report);
  }
});

test('cadence validation rejects missing opening, middle and final samples', () => {
  for (const missing of [0.5, 6, 31.9667]) {
    const report = clone(complete);
    report.coverage.frame_times_s = report.coverage.frame_times_s.filter((time) => time !== missing);
    assert.throws(() => validateFrameCadence(report));
  }
});

test('complete synthetic checks declare equal-weight point maxima', () => {
  for (const report of Object.values(syntheticReports)) {
    if (report.scoring_status === 'complete') validateCheckMaxima(report, contract());
  }
});

test('check maxima validation rejects missing and incorrect maxima', () => {
  for (const mutate of [
    (r) => { delete r.scoring_details.hook[0].max; },
    (r) => { r.scoring_details.visual[0].max = 25; },
  ]) {
    const report = clone(complete); mutate(report);
    assert.throws(() => validateCheckMaxima(report, contract()));
  }
});

test('objective audio contract replaces listening with measured and personally inspected evidence', () => {
  const c = contract();
  assert.deepEqual(c.objective_audio_required, ['lra_lu', 'astats', 'duration_alignment',
    'ending_fade', 'showwavespic', 'showspectrumpic']);
  for (const text of [body().instructions, read('rubric')]) {
    for (const term of ['objective_audio_review', 'showwavespic', 'showspectrumpic', 'astats',
      'LRA', 'DC', '1.2', '100 ms', '20 ms', 'no subjective listening']) assert.ok(text.includes(term), term);
    assert.doesNotMatch(text, /Full audio listening\/playback is mandatory|Review full audio through|inability to verify full sound|listened intervals|frame\/listening evidence/);
  }
});

test('measured-complete fixture can PASS without subjective listening', () => {
  const report = syntheticReports.pass;
  assert.equal(report.coverage.full_audio_review, false);
  assert.equal(report.coverage.objective_audio_review, true);
  for (const key of ['lra_lu', 'astats', 'duration_alignment', 'ending_fade']) {
    assert.ok(report.measurements[key] != null, `Missing objective audio ${key}`);
  }
  for (const name of ['showwavespic', 'showspectrumpic']) {
    assert.ok(report.evidence.some((item) => item.kind === 'audio_image_review'
      && item.generator === name && item.personally_inspected === true));
  }
  assert.match(report.coverage.limitation, /no subjective listening/);
  validateFixture(report, contract());
  assert.equal(report.verdict, 'PASS');
});

for (const name of ['missingAudioStreamFail', 'ebur128FailureFail']) {
  test(`synthetic ${name} fails closed without invented audio scores`, () => {
    const report = syntheticReports[name];
    assert.ok(report, `Missing ${name} fixture`);
    validateFixture(report, contract());
    assert.equal(report.verdict, 'FAIL');
    assert.equal(report.scoring_status, 'incomplete');
    assert.equal(report.total, 0);
    assert.equal(report.coverage.objective_audio_review, false);
    if (name === 'missingAudioStreamFail') {
      assert.equal(report.measurements.audio_streams, 0);
      assert.ok(report.criticals.some((item) => item.code === 'SPEC'));
    } else {
      assert.equal(report.measurements.integrated_lufs, null);
      assert.ok(report.tool_failures.some((item) => item.tool === 'ebur128'));
    }
  });
}

test('confirmed endpoint mismatch and absent ending fade are always SPEC criticals', () => {
  assert.deepEqual(contract().audio_spec_criticals,
    { confirmed_duration_mismatch: 'SPEC', confirmed_missing_ending_fade: 'SPEC' });
  for (const name of ['durationMismatchFail', 'missingEndingFadeFail']) {
    const report = syntheticReports[name];
    assert.ok(report, `Missing ${name}`);
    validateFixture(report, contract());
    assert.equal(report.verdict, 'FAIL');
    assert.equal(report.scoring_status, 'complete');
    assert.ok(report.criticals.some((item) => item.code === 'SPEC'));
    const withoutCritical = clone(report); withoutCritical.criticals = [];
    assert.throws(() => validateFixture(withoutCritical, contract()));
  }
});

test('complete objective review rejects absent astats channels, unreviewed tail images and missing fade windows', () => {
  const c = contract();
  for (const mutate of [
    (r) => { r.measurements.astats.channels = []; },
    (r) => { r.measurements.astats.dc_offset = null; },
    (r) => { r.measurements.ending_fade.windows.pop(); },
    (r) => { r.measurements.duration_alignment.status = 'unverified'; },
    (r) => { r.evidence.find((item) => item.id === 'E6').personally_inspected = false; },
  ]) {
    const report = clone(complete); mutate(report);
    assert.throws(() => validateFixture(report, c));
  }
});

test('fixture validator rejects malformed reports and unsupported PASS claims', () => {
  const c = contract();
  for (const mutate of [
    (r) => { delete r.report_id; }, (r) => { r.total = '92'; },
    (r) => { r.total = 101; }, (r) => { r.verdict = 'pass'; },
    (r) => { r.report_id = 'wrong-run'; }, (r) => { r.category_scores.audio = null; },
    (r) => { r.coverage.objective_audio_review = false; },
    (r) => { r.measurements.audio_streams = 0; },
    (r) => { r.measurements.integrated_lufs = null; },
    (r) => { r.measurements.lra_lu = null; },
    (r) => { r.measurements.ending_fade = null; },
    (r) => { r.evidence = r.evidence.filter((item) => item.generator !== 'showspectrumpic'); },
    (r) => { r.criticals = clone(critical.criticals); },
    (r) => { r.category_evidence.hook = []; },
  ]) {
    const report = clone(complete); mutate(report);
    assert.throws(() => validateFixture(report, c));
  }
  const incomplete = clone(failed); incomplete.category_scores.audio = 0;
  assert.throws(() => validateFixture(incomplete, c));
});
