/** 카메라 자세 분석의 계산과 보관. 얼굴 특징점(정규화 좌표)에서 수치만 만들고, 영상·이미지·특징점 원본은 남기지 않는다.
 *  브라우저 API를 쓰지 않아 Node에서도 테스트할 수 있다(web/tests/unit/video-metrics.spec.ts, npm run test:unit). */

import {faceDetectorMetadata,type DetectorMetadata} from "./runtime";
import { median } from "./stats";

export type Point = { x: number; y: number };
/** 표본마다 정확히 하나. in: 특징점 전부가 카메라 프레임 안 · edge: 얼굴은 찾았지만 특징점 일부가 프레임 밖
 *  · none: 얼굴을 찾지 못함(자리를 비웠을 수도, 조명·각도·가림·검출 오류일 수도 있다) */
export type FaceState = "in" | "edge" | "none";
/** 원본 카메라 프레임(좌우 반전 전) 기준으로 특징점이 경계 [0, 1] 밖으로 나간 정도. 안 나간 쪽은 0 */
export type Overshoot = { top: number; bottom: number; left: number; right: number };
/** overshoot·coreInside는 edge일 때만 채운다(실시간 안내와 진단용, 요약 계산에는 쓰지 않음) */
export type FaceSample = { t: number; state: FaceState; yaw?: number; pitch?: number; overshoot?: Overshoot; coreInside?: boolean };

/** 답변 구간(performance.now() 기준 ms) */
export type Span = { start: number; end: number };

/** 한 답변의 요약. inMs + edgeMs + noneMs = analyzedMs이고, 비율은 모두 analyzedMs에 대한 것이다 */
export type SegmentSummary = {
  samples: number;
  /** 답변을 시작해서 마칠 때까지의 실제 시간. 이 중 analyzedMs만 분석했다 */
  answerMs: number;
  /** 표본이 대표하는 시간(탭이 가려졌거나 표본이 끊긴 시간은 빠진다) */
  analyzedMs: number;
  /** 얼굴을 찾은 시간(inMs + edgeMs) */
  detectedMs: number;
  inMs: number;
  edgeMs: number;
  noneMs: number;
  /** none이 EPISODE_MS 이상 이어진 횟수와 가장 긴 none 구간 */
  noneEpisodes: number;
  longestNoneMs: number;
  /** 고개 방향을 잰 시간(얼굴 전체가 화면 안). 표본이 적으면 0 */
  headMs: number;
  turnedMs: number;
  downMs: number;
};

/** 기록 주기. 초당 4회만 검출해 CPU 사용을 줄인다 */
export const SAMPLE_MS = 250;
/** 탭이 숨겨지는 등으로 표본 사이가 벌어져도 한 표본이 이보다 오래 대표하지 않게 한다 */
export const MAX_GAP_MS = 1000;
/** 이보다 길게 얼굴을 찾지 못했을 때만 횟수로 센다(검출이 잠깐 흔들린 것은 세지 않음) */
export const EPISODE_MS = 1000;
/** 고개 방향 기준(중앙값)을 잡기 위한 최소 표본 수(약 2초) */
export const MIN_HEAD_SAMPLES = 8;
/** 코끝이 얼굴 폭의 12% 넘게 옮겨 가면 좌우로 돌린 것으로 본다(대략 20° 안팎, 실제 웹캠으로 조정 전) */
export const YAW_THRESHOLD = 0.12;
/** 코끝이 이마–턱 길이의 6% 넘게 내려가면 숙인 것으로 본다(대략 15° 안팎, 실제 웹캠으로 조정 전) */
export const PITCH_THRESHOLD = 0.06;

// MediaPipe Face Mesh 특징점 번호: 코끝, 이마 위, 턱 끝, 화면 왼쪽·오른쪽 얼굴 가장자리
const NOSE = 1, TOP = 10, CHIN = 152, LEFT = 234, RIGHT = 454;
const EDGE_MARGIN = 0.01;
/** 핵심 부위: 양 눈 바깥·안쪽 끝, 코끝, 입 양끝·위·아래. 분류에는 쓰지 않고 진단에만 쓴다 */
export const CORE_LANDMARKS = [33, 133, 362, 263, 1, 61, 291, 13, 14];

/** 한 프레임의 특징점에서 상태와 고개 방향 지표를 뽑는다. 지표는 각도가 아니라 얼굴 크기에 대한 비율이다 */
export function faceFeatures(points: Point[] | null | undefined): Omit<FaceSample, "t"> {
  if (!points?.length || points.some((p) => !p || !Number.isFinite(p.x) || !Number.isFinite(p.y))) return { state: "none" };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of points) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  }
  if (minX < -EDGE_MARGIN || minY < -EDGE_MARGIN || maxX > 1 + EDGE_MARGIN || maxY > 1 + EDGE_MARGIN) {
    const inside = (p?: Point) => !!p && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;
    return {
      state: "edge",
      overshoot: { top: Math.max(0, -minY), bottom: Math.max(0, maxY - 1), left: Math.max(0, -minX), right: Math.max(0, maxX - 1) },
      coreInside: CORE_LANDMARKS.every((i) => inside(points[i])),
    };
  }
  const [nose, top, chin, left, right] = [NOSE, TOP, CHIN, LEFT, RIGHT].map((i) => points[i]);
  if (!nose || !top || !chin || !left || !right) return { state: "in" };
  const width = Math.abs(right.x - left.x), height = chin.y - top.y;
  if (width < 1e-3 || height < 1e-3) return { state: "in" };
  return { state: "in", yaw: (nose.x - (left.x + right.x) / 2) / width, pitch: (nose.y - top.y) / height };
}

/** 면접 중 안내 문구. 실제로 edge를 만든 쪽(EDGE_MARGIN보다 크게 넘은 쪽)만 위쪽·아래쪽·왼쪽·오른쪽 순서로 알린다.
 *  미리보기가 좌우 반전이라 원본의 왼쪽(x < 0)은 화면 오른쪽, 원본의 오른쪽(x > 1)은 화면 왼쪽이다 */
export function edgeLabel(o: Overshoot): string {
  const sides = ([[o.top, "위쪽"], [o.bottom, "아래쪽"], [o.right, "왼쪽"], [o.left, "오른쪽"]] as const)
    .filter(([v]) => v > EDGE_MARGIN).map(([, name]) => name);
  return sides.length ? `얼굴 ${sides.join("·")}이 화면 밖에 있어요` : "얼굴 일부가 화면 밖에 있어요";
}


/** 한 답변 동안의 표본을 요약한다. 각 표본은 다음 표본까지(마지막은 답변 끝까지, 끝을 모르면 SAMPLE_MS) 이어진 것으로
 *  보되 MAX_GAP_MS를 넘지 않는다. 고개 방향은 이 답변의 중앙값을 기준으로 한 상대 변화다(처음부터 숙이고 있었으면 숙임으로
 *  잡히지 않는다). */
export function summarizeSegment(samples: FaceSample[], span?: Span): SegmentSummary {
  // Reject unknown timestamps; sort without mutating input and clip every interval to the answer.
  span = span && Number.isFinite(span.start) && Number.isFinite(span.end) && span.end >= span.start ? span : undefined;
  samples = samples.filter((s) => Number.isFinite(s.t)).slice().sort((a, b) => a.t - b.t);
  const out: SegmentSummary = {
    samples: samples.length, answerMs: 0, analyzedMs: 0, detectedMs: 0, inMs: 0, edgeMs: 0, noneMs: 0,
    noneEpisodes: 0, longestNoneMs: 0, headMs: 0, turnedMs: 0, downMs: 0,
  };
  const last = (t: number) => (span ? span.end - t : SAMPLE_MS);
  const gap = samples.map((s, i) => (samples[i + 1]?.t ?? s.t + last(s.t)) - s.t);
  const dur = gap.map((g, i) => Math.max(0, Math.min(samples[i].t + Math.min(MAX_GAP_MS, g), span?.end ?? Infinity) - Math.max(samples[i].t, span?.start ?? -Infinity)));
  let run = 0;
  const closeRun = () => {
    if (run >= EPISODE_MS) out.noneEpisodes++;
    out.longestNoneMs = Math.max(out.longestNoneMs, run);
    run = 0;
  };
  samples.forEach((s, i) => {
    out.analyzedMs += dur[i];
    if (s.state === "none") {
      out.noneMs += dur[i];
      run += dur[i];
      // 다음 표본까지 MAX_GAP_MS보다 오래 분석하지 못했다: 그 공백 너머의 none과 이어진 구간으로 세지 않는다
      if (gap[i] > MAX_GAP_MS) closeRun();
      return;
    }
    closeRun();
    if (s.state === "in") out.inMs += dur[i];
    else out.edgeMs += dur[i];
  });
  closeRun();
  out.detectedMs = out.inMs + out.edgeMs;
  out.answerMs = span ? Math.max(0, span.end - span.start) : out.analyzedMs;
  const head = samples.map((s, i) => ({ ...s, d: dur[i] })).filter((s) => s.state === "in" && s.d > 0 && Number.isFinite(s.yaw) && Number.isFinite(s.pitch));
  if (head.length >= MIN_HEAD_SAMPLES) {
    const yaw0 = median(head.map((s) => s.yaw!)), pitch0 = median(head.map((s) => s.pitch!));
    for (const s of head) {
      out.headMs += s.d;
      if (Math.abs(s.yaw! - yaw0) > YAW_THRESHOLD) out.turnedMs += s.d;
      if (s.pitch! - pitch0 > PITCH_THRESHOLD) out.downMs += s.d;
    }
  }
  return out;
}

/** Retain at most one hour at 4Hz. The rest remains unanalysed in the answer span. */
export function createFaceSampler(maxSamples = 14_400) {
  const samples: FaceSample[] = [];
  const cap = Number.isFinite(maxSamples) ? Math.max(0, Math.floor(maxSamples)) : 14_400;
  return {
    add(sample: FaceSample) { if (samples.length < cap) samples.push({ ...sample }); },
    snapshot: () => samples.slice(),
  };
}

/** 여러 답변의 요약을 합친다(시간은 더하고 가장 길게 찾지 못한 시간은 최댓값) */
export function combineSummaries(list: SegmentSummary[]): SegmentSummary {
  const out = summarizeSegment([]);
  for (const s of list) {
    for (const k of Object.keys(out) as (keyof SegmentSummary)[]) if (k !== "longestNoneMs") out[k] += Number.isFinite(s[k]) ? s[k] : 0;
    out.longestNoneMs = Math.max(out.longestNoneMs, Number.isFinite(s.longestNoneMs) ? s.longestNoneMs : 0);
  }
  return out;
}

// 이 탭의 메모리에만 보관한다(서버·브라우저 저장소에 쓰지 않음). 새로고침하거나 탭을 닫으면 사라진다
const reports = new Map<string, Map<string, SegmentSummary>>();

const runIds = new Map<string,Map<string,string>>();
const detectorMetadata = new Map<string,Map<string,DetectorMetadata>>();
const revisions = new Map<string, Map<string, string>>();

/** Optional revision preserves existing callers; revision-aware reads never accept legacy unkeyed values. */
export function saveVideoSegment(sessionId: string, answerId: string, summary: SegmentSummary, recordedAt?: string) {
  if (!reports.has(sessionId)) reports.set(sessionId, new Map());
  if(!runIds.has(sessionId))runIds.set(sessionId,new Map());
  if(revisions.get(sessionId)?.get(answerId)!==recordedAt||!runIds.get(sessionId)!.has(answerId))runIds.get(sessionId)!.set(answerId,globalThis.crypto.randomUUID());
  if(!detectorMetadata.has(sessionId))detectorMetadata.set(sessionId,new Map());
  detectorMetadata.get(sessionId)!.set(answerId,faceDetectorMetadata());
  reports.get(sessionId)!.set(answerId, summary);
  if (!revisions.has(sessionId)) revisions.set(sessionId, new Map());
  if (recordedAt) revisions.get(sessionId)!.set(answerId, recordedAt);
  else revisions.get(sessionId)!.delete(answerId);
}
export function getVideoSegments(sessionId: string, answerId: string, recordedAt?: string | null): SegmentSummary | undefined {
  if (recordedAt !== undefined && (!recordedAt || revisions.get(sessionId)?.get(answerId) !== recordedAt)) return undefined;
  return reports.get(sessionId)?.get(answerId);
}
export function getVideoRunId(sessionId:string,answerId:string,recordedAt:string){return getVideoSegments(sessionId,answerId,recordedAt)?runIds.get(sessionId)?.get(answerId):undefined;}
export function getVideoSegmentMetadata(sessionId:string,answerId:string,recordedAt:string){
  return getVideoSegments(sessionId,answerId,recordedAt)?detectorMetadata.get(sessionId)?.get(answerId):undefined;
}
export const sessionVideo = (sessionId: string) => reports.get(sessionId);
export function clearVideoSegment(sessionId: string, answerId: string) {
  reports.get(sessionId)?.delete(answerId); revisions.get(sessionId)?.delete(answerId); detectorMetadata.get(sessionId)?.delete(answerId);runIds.get(sessionId)?.delete(answerId);
}
export function clearSessionVideo(sessionId: string) { reports.delete(sessionId); revisions.delete(sessionId); detectorMetadata.delete(sessionId);runIds.delete(sessionId); }

/** Derived comments describe detector coverage and positioning, never gaze, attention or confidence. */
export function videoDiagnostics(summary: SegmentSummary): {
  quality: "insufficient" | "partial" | "measured"; coverage: number; unanalysedMs: number; comments: string[];
} {
  const finite = (v: number) => Number.isFinite(v) ? Math.max(0, v) : 0;
  const answer = finite(summary.answerMs), analyzed = Math.min(answer, finite(summary.analyzedMs));
  const coverage = answer > 0 ? analyzed / answer : 0;
  const unanalysedMs = Math.max(0, answer - analyzed);
  const comments: string[] = [];
  if (unanalysedMs > 0) comments.push(`답변 중 ${(unanalysedMs / 1000).toFixed(1)}초는 분석하지 못한 구간입니다. 이 시간을 얼굴 이탈로 세지 않습니다.`);
  if (summary.noneMs > 0) comments.push("얼굴을 찾지 못한 구간이 있습니다. 조명·가림·각도·검출 오류도 원인일 수 있습니다.");
  if (summary.edgeMs > 0) comments.push("얼굴 일부가 프레임 밖에 있었습니다. 카메라 위치·거리를 확인해 보세요.");
  if (summary.headMs > 0) comments.push("고개 방향은 이 답변의 중앙 자세에 대한 상대 변화이며 시선·집중도·자신감을 뜻하지 않습니다.");
  if (!analyzed) comments.push("분석한 영상이 없어 자세를 판단할 수 없습니다.");
  return { quality: !analyzed ? "insufficient" : coverage < 0.8 ? "partial" : "measured", coverage, unanalysedMs, comments };
}
export function clearAllVideo() { reports.clear(); revisions.clear(); detectorMetadata.clear();runIds.clear(); }
