/** 카메라 자세 분석의 계산과 보관. 얼굴 특징점(정규화 좌표)에서 수치만 만들고, 영상·이미지·특징점 원본은 남기지 않는다.
 *  브라우저 API를 쓰지 않아 Node에서도 테스트할 수 있다(web/e2e/video-metrics.spec.ts). */

export type Point = { x: number; y: number };
/** in: 얼굴 전체가 화면 안 · edge: 얼굴 일부가 화면 밖 · none: 얼굴을 찾지 못함 */
export type FaceState = "in" | "edge" | "none";
export type FaceSample = { t: number; state: FaceState; yaw?: number; pitch?: number };

export type SegmentSummary = {
  samples: number;
  totalMs: number;
  /** 얼굴을 찾은 시간(edge 포함) */
  detectedMs: number;
  /** 얼굴을 찾지 못했거나 일부가 화면 밖에 있던 시간 */
  offMs: number;
  offEpisodes: number;
  longestOffMs: number;
  /** 고개 방향을 잰 시간(얼굴 전체가 화면 안). 표본이 적으면 0 */
  headMs: number;
  turnedMs: number;
  downMs: number;
};

/** 기록 주기. 초당 4회만 검출해 CPU 사용을 줄인다 */
export const SAMPLE_MS = 250;
/** 탭이 숨겨지는 등으로 표본 사이가 벌어져도 한 표본이 이보다 오래 대표하지 않게 한다 */
export const MAX_GAP_MS = 1000;
/** 이보다 길게 벗어났을 때만 '벗어난 횟수'로 센다(검출이 잠깐 흔들린 것은 세지 않음) */
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

/** 한 프레임의 특징점에서 상태와 고개 방향 지표를 뽑는다. 지표는 각도가 아니라 얼굴 크기에 대한 비율이다 */
export function faceFeatures(points: Point[] | null | undefined): Omit<FaceSample, "t"> {
  if (!points?.length) return { state: "none" };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of points) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  }
  if (minX < -EDGE_MARGIN || minY < -EDGE_MARGIN || maxX > 1 + EDGE_MARGIN || maxY > 1 + EDGE_MARGIN) return { state: "edge" };
  const [nose, top, chin, left, right] = [NOSE, TOP, CHIN, LEFT, RIGHT].map((i) => points[i]);
  if (!nose || !top || !chin || !left || !right) return { state: "in" };
  const width = Math.abs(right.x - left.x), height = chin.y - top.y;
  if (width < 1e-3 || height < 1e-3) return { state: "in" };
  return { state: "in", yaw: (nose.x - (left.x + right.x) / 2) / width, pitch: (nose.y - top.y) / height };
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** 한 답변 동안의 표본을 요약한다. 각 표본은 다음 표본까지(마지막은 SAMPLE_MS) 이어진 것으로 본다.
 *  고개 방향은 이 답변의 중앙값을 기준으로 한 상대 변화다(처음부터 숙이고 있었으면 숙임으로 잡히지 않는다). */
export function summarizeSegment(samples: FaceSample[]): SegmentSummary {
  const out: SegmentSummary = { samples: samples.length, totalMs: 0, detectedMs: 0, offMs: 0, offEpisodes: 0, longestOffMs: 0, headMs: 0, turnedMs: 0, downMs: 0 };
  const dur = samples.map((s, i) => Math.max(0, Math.min(MAX_GAP_MS, (samples[i + 1]?.t ?? s.t + SAMPLE_MS) - s.t)));
  let run = 0;
  const closeRun = () => {
    if (run >= EPISODE_MS) out.offEpisodes++;
    out.longestOffMs = Math.max(out.longestOffMs, run);
    run = 0;
  };
  samples.forEach((s, i) => {
    out.totalMs += dur[i];
    if (s.state !== "none") out.detectedMs += dur[i];
    if (s.state === "in") closeRun();
    else { out.offMs += dur[i]; run += dur[i]; }
  });
  closeRun();
  const head = samples.map((s, i) => ({ ...s, d: dur[i] })).filter((s) => s.state === "in" && s.yaw !== undefined && s.pitch !== undefined);
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

/** 여러 답변의 요약을 합친다(시간은 더하고 가장 길게 벗어난 시간은 최댓값) */
export function combineSummaries(list: SegmentSummary[]): SegmentSummary {
  const out = summarizeSegment([]);
  for (const s of list) {
    for (const k of Object.keys(out) as (keyof SegmentSummary)[]) if (k !== "longestOffMs") out[k] += s[k];
    out.longestOffMs = Math.max(out.longestOffMs, s.longestOffMs);
  }
  return out;
}

// 이 탭의 메모리에만 보관한다(서버·브라우저 저장소에 쓰지 않음). 새로고침하거나 탭을 닫으면 사라진다
const reports = new Map<string, Map<string, SegmentSummary>>();

export function saveVideoSegment(sessionId: string, answerId: string, summary: SegmentSummary) {
  if (!reports.has(sessionId)) reports.set(sessionId, new Map());
  reports.get(sessionId)!.set(answerId, summary);
}
export const sessionVideo = (sessionId: string) => reports.get(sessionId);
export const clearSessionVideo = (sessionId: string) => { reports.delete(sessionId); };
