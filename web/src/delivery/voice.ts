/** Optional browser-only energy observations, NOT a speech recogniser or validated VAD.
 * Seconds throughout. Neither samples nor derived reports leave this tab. */
import { MIN_RATE_SEC, syllableCount } from "../review/insights";

export type VoiceSample = { t: number; rms: number; clipped?: boolean };
export type DeliverySummary = {
  /** Set on revision-aware reads; edited text cannot be aligned to the old recording. */
  transcriptRevisionMatches?: boolean;
  method: "browser-energy-candidates-v1";
  quality: "usable" | "insufficient" | "unreliable" | "unavailable";
  reasons: string[];
  totalSec: number;
  analyzedSec: number;
  unanalysedSec: number;
  coverage: number;
  activeCandidateSec: number | null;
  silenceCandidateSec: number | null;
  silenceCandidateRatio: number | null;
  /** Observed low-energy runs >=0.5s, including leading/trailing runs; NOT linguistic pauses. */
  pauseCount: number | null;
  longPauseCount: number | null;
  longestPauseSec: number | null;
  /** Whitespace-separated text units (Korean eojeol / words), not syllables. */
  transcriptUnits: number;
  syllables: number;
  totalPacePerMin: number | null;
  activeCandidatePacePerMin: number | null;
  fillers: { token: string; count: number }[];
  limitations: string[];
};
export const VOICE_SAMPLE_SEC = 0.1;
const MAX_REPRESENTED_SEC = 0.2;
const LIMITATIONS = [
  "브라우저 음량 변화로 찾은 발화 후보이며 검증된 음성 구간이 아닙니다. 배경 소음·자동 음량 조절의 영향을 받습니다.",
  "전체 속도와 발화 후보 속도는 전사문 근사 음절 수를 각각 전체 녹음 시간과 에너지 후보 시간으로 나눈 분당 음절 참고값입니다. 영문·숫자는 글자당 한 음절로 셉니다.",
  "멈춤은 관측된 저에너지 구간(처음·끝 포함)이며 언어적 쉼이나 긴장을 뜻하지 않습니다. 분석 공백은 멈춤으로 세지 않습니다.",
  "추임새는 전사문 속 독립된 낱말 후보로만 세며 발화 시각·실제 소리·습관을 판정하지 않습니다.",
];

/** At 10Hz this budget covers 30min. Stop retaining new samples at the cap; lost coverage remains explicit. */
export function createVoiceSampler(maxSamples = 18_000) {
  const data: VoiceSample[] = [];
  const cap = Number.isFinite(maxSamples) ? Math.max(0, Math.floor(maxSamples)) : 18_000;
  return {
    add(s: VoiceSample) {
      if (data.length >= cap || !Number.isFinite(s.t) || s.t < 0 || (data.length && s.t - data[data.length - 1].t < VOICE_SAMPLE_SEC - 1e-6)) return;
      data.push({ t: s.t, rms: s.rms, clipped: s.clipped });
    },
    snapshot: () => data.map((s) => ({ ...s })),
  };
}

/** Recalculate textual candidates after STT. It never invents acoustic timestamps. */
export function withVoiceTranscript(summary: DeliverySummary, transcript: string): DeliverySummary {
  if (summary.transcriptRevisionMatches === false) return {
    ...summary, transcriptUnits: 0, syllables: 0, totalPacePerMin: null, activeCandidatePacePerMin: null, fillers: [],
    limitations: [...new Set([...summary.limitations, "전사문이 바뀌어 녹음과 연결한 속도·추임새 해석을 표시하지 않습니다. 수치 관찰은 원래 녹음의 값입니다."])],
  };
  const tokens = transcript.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  const candidates = new Set(["어", "음", "그", "저", "그러니까", "이제", "사실", "약간", "아무튼", "뭐", "um", "uh"]);
  const counts = new Map<string, number>();
  for (const token of tokens) if (candidates.has(token)) counts.set(token, (counts.get(token) ?? 0) + 1);
  const transcriptUnits = transcript.trim().split(/\s+/).filter((s) => /[\p{L}\p{N}]/u.test(s)).length;
  const syllables = syllableCount(transcript);
  const measurable = summary.totalSec >= MIN_RATE_SEC && syllables > 0;
  return { ...summary, transcriptUnits, syllables, fillers: [...counts].map(([token, count]) => ({ token, count })),
    totalPacePerMin: measurable && summary.totalSec > 0 ? syllables * 60 / summary.totalSec : null,
    activeCandidatePacePerMin: measurable && summary.quality === "usable" && (summary.activeCandidateSec ?? 0) > 0 ? syllables * 60 / summary.activeCandidateSec! : null };
}

export function summarizeVoice(samples: readonly VoiceSample[], durationSec: number, transcript = ""): DeliverySummary {
  const totalSec = Number.isFinite(durationSec) && durationSec > 0 ? durationSec : 0;
  const out: DeliverySummary = {
    method: "browser-energy-candidates-v1", quality: "unavailable", reasons: [], totalSec,
    analyzedSec: 0, unanalysedSec: totalSec, coverage: 0, activeCandidateSec: null, silenceCandidateSec: null, silenceCandidateRatio: null,
    pauseCount: null, longPauseCount: null, longestPauseSec: null,
    transcriptUnits: 0, syllables: 0, totalPacePerMin: null, activeCandidatePacePerMin: null, fillers: [], limitations: [...LIMITATIONS],
  };
  if (!totalSec) { out.reasons.push("invalid_duration"); return withVoiceTranscript(out, transcript); }
  // Invalid-energy observations are retained as boundaries, so removing one cannot bridge its unknown interval.
  const ordered = samples.filter((s) => Number.isFinite(s.t) && s.t >= 0 && s.t < totalSec).slice(0, 18_000).sort((a, b) => a.t - b.t);
  const cells = ordered.map((s, i) => ({ ...s, d: Math.max(0, Math.min(MAX_REPRESENTED_SEC, (ordered[i + 1]?.t ?? totalSec) - s.t)),
    valid: Number.isFinite(s.rms) && s.rms >= 0 && s.rms <= 1 }));
  const valid = cells.filter((s) => s.valid && s.d > 0);
  out.analyzedSec = Math.min(totalSec, valid.reduce((sum, s) => sum + s.d, 0));
  out.unanalysedSec = Math.max(0, totalSec - out.analyzedSec);
  out.coverage = out.analyzedSec / totalSec;
  if (!valid.length) { out.reasons.push("no_samples"); return withVoiceTranscript(out, transcript); }
  out.quality = "usable";
  if (samples.some((s) => !Number.isFinite(s.t))) { out.quality = "unreliable"; out.reasons.push("invalid_timestamp"); }
  if (ordered[0].t > MAX_REPRESENTED_SEC || ordered.some((s, i) => (ordered[i + 1]?.t ?? totalSec) - s.t > MAX_REPRESENTED_SEC + 1e-6)) {
    out.quality = "unreliable"; out.reasons.push("sampling_gap");
  }
  if (out.coverage < 0.8) { out.quality = "unreliable"; out.reasons.push("partial_coverage"); }
  if (cells.some((s) => !s.valid)) { out.quality = "unreliable"; out.reasons.push("invalid_energy"); }
  if (valid.filter((s) => s.clipped || s.rms >= 0.98).length / valid.length > 0.05) {
    out.quality = "unreliable"; out.reasons.push("clipping");
  }
  const energy = valid.map((s) => s.rms).sort((a, b) => a - b);
  const low = energy[Math.floor((energy.length - 1) * 0.2)], high = energy[Math.floor((energy.length - 1) * 0.8)];
  if (high < 0.008) { if (out.quality === "usable") out.quality = "insufficient"; out.reasons.push("low_energy"); }
  else if (high - low < Math.max(0.004, high * 0.15)) { out.quality = "unreliable"; out.reasons.push("constant_energy"); }
  if (totalSec < 2 || valid.length < 10) {
    if (out.quality === "usable") out.quality = "insufficient";
    out.reasons.push("too_short");
  }
  if (out.quality !== "usable") return withVoiceTranscript(out, transcript);
  const threshold = low + (high - low) * 0.35;
  let active = 0, run = 0, pauses = 0, longPauses = 0, longest = 0;
  const close = () => {
    if (run >= 0.5 - 1e-6) { pauses++; if (run >= 2 - 1e-6) longPauses++; longest = Math.max(longest, run); }
    run = 0;
  };
  cells.forEach((s, i) => {
    if (!s.valid) { close(); return; }
    if (s.rms >= threshold) { active += s.d; close(); } else run += s.d;
    // A missing interval is not a continuation of an observed pause.
    if ((cells[i + 1]?.t ?? totalSec) - s.t > MAX_REPRESENTED_SEC + 1e-6) close();
  });
  close();
  out.activeCandidateSec = active;
  out.silenceCandidateSec = Math.max(0, out.analyzedSec - active);
  out.silenceCandidateRatio = out.analyzedSec > 0 ? out.silenceCandidateSec / out.analyzedSec : null;
  out.pauseCount = pauses; out.longPauseCount = longPauses; out.longestPauseSec = longest;
  return withVoiceTranscript(out, transcript);
}

const reports = new Map<string, Map<string, { revision: string; summary: DeliverySummary; runId:string; sourceTranscript?: string }>>();
export function saveVoiceSegment(sessionId: string, answerId: string, summary: DeliverySummary, recordedAt: string, transcript?: string | null) {
  if (!recordedAt) return;
  if (!reports.has(sessionId)) reports.set(sessionId, new Map());
  const previous=reports.get(sessionId)!.get(answerId);
  reports.get(sessionId)!.set(answerId, { revision: recordedAt, summary, runId:previous?.revision===recordedAt?previous.runId:globalThis.crypto.randomUUID(), sourceTranscript: transcript === undefined ? undefined : (transcript ?? "").trim() });
}
export function getVoiceSegment(sessionId: string, answerId: string, recordedAt: string | null | undefined, transcript?: string | null): DeliverySummary | undefined {
  const item = reports.get(sessionId)?.get(answerId);
  if (!recordedAt || item?.revision !== recordedAt) return undefined;
  return transcript === undefined ? item.summary : { ...item.summary, transcriptRevisionMatches: item.sourceTranscript === (transcript ?? "").trim() };
}
export function getVoiceRunId(sessionId:string,answerId:string,recordedAt:string){const item=reports.get(sessionId)?.get(answerId);return item?.revision===recordedAt?item.runId:undefined;}
export function clearVoiceSegment(sessionId: string, answerId: string) { reports.get(sessionId)?.delete(answerId); }
export function clearSessionVoice(sessionId: string) { reports.delete(sessionId); }
export function clearAllVoice() { reports.clear(); }

/** Same byte-domain analyser calculation for live recorder and PCM integration checks. */
export function byteTimeDomainEnergy(buf: Uint8Array): {rms:number;clipped:boolean} {
  let sum=0,clipped=0;
  for(const v of buf){sum+=((v-128)/128)**2;if(v<=1||v>=254)clipped++;}
  return {rms:buf.length?Math.sqrt(sum/buf.length):0,clipped:buf.length>0&&clipped/buf.length>0.05};
}
