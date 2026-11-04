/** 시선 분석(G)의 잠정 기준값. 실제 웹캠 측정 전에는 맞는지 모르므로 한곳에 모아 두고 0단계 시험 뒤 조정한다
 *  (설계: docs/superpowers/specs/2026-11-01-g-gaze-calibration-design.md 5·7·8·10·13절). */

/** 표본 주기 후보(초당 횟수). 4는 기존 D 주기이고 10·15는 측정으로 고를 후보다 */
export const RATES = [4, 10, 15] as const;
export type Rate = (typeof RATES)[number];

/** 적응 정책: 하나라도 넘으면 한 단계 내리고, 이만큼 괜찮으면 한 단계 올린다 */
export const RATE_POLICY = { busyPct: 25, longTasks: 2, lagP95: 50, healthyMs: 10_000, windowMs: 10_000 };

/** 특징 유효성: 눈 점이 프레임 안 여유, 두 눈 홍채 위치 차이(눈 폭 단위) 최대 */
export const EYE_MARGIN = 0.01;
export const EYE_GAP_MAX = 0.2;
/** 눈 뜬 정도가 기준(렌즈 응시 때)의 이 비율보다 작으면 감은 것으로 본다 */
export const OPEN_MIN_RATIO = 0.5;
/** 보정 때보다 얼굴 크기가 이만큼 넘게 바뀌거나, 위치가 프레임의 이만큼 넘게 옮겨 가면 자세가 바뀐 것으로 본다 */
export const SCALE_TOL = 0.15;
export const POS_TOL = 0.1;
/** 고개 방향 보정 범위의 여유(범위 폭에 대한 비율) */
export const HEAD_RANGE_MARGIN = 0.1;

/** 응시 하나: 점이 나타난 뒤 버리는 시간, 모으는 시간(ms), 최소 유효 표본 수 */
export const SETTLE_MS = 700;
export const COLLECT_MS = 1000;
export const POSE_SETTLE_MS = 1000;
export const POSE_COLLECT_MS = 2000;
export const LENS_COLLECT_MS = 1500;
export const MIN_VALID = 8;
export const MAX_RETRY = 2;

/** G2 회귀: 릿지 λ 후보, 2차 모델을 고르려면 필요한 개선 비율 */
export const LAMBDAS = [0.01, 0.1, 1, 10];
export const M2_GAIN = 0.15;

/** G1 렌즈 분류기 */
export const LENS = { l2: 1.0, hiMin: 0.8, loMax: 0.2, topFalseRate: 0.05, missRate: 0.05, oodPercentile: 0.99, maxIter: 25 };

/** 0단계 판정 기준(스펙 13절). 통과는 1단계로 갈 근거일 뿐 제품의 정확도 보장이 아니다 */
export const FEASIBILITY = {
  h1: { aucPass: 0.85, aucFail: 0.75, lensPass: 0.6, lensTurnedPass: 0.4, lensFail: 0.3, topFalsePass: 0.1, topFalseFail: 0.2 },
  h2: { e50Pass: 0.08, e80Pass: 0.12, e50Fail: 0.15, validPass: 0.8, validFail: 0.6, turnedRatio: 1.5, repeatSpread: 0.3 },
  panel: { heights: [32, 120, 240], hitPass: 0.8, falseQuestionMax: 0.1, hitFail: 0.6 },
  distance: { e50Ratio: 1.5, gatedPass: 0.8, e50FailRatio: 2, gatedFail: 0.5 },
  rate: { achievedMin: 0.9, detectShare: 1 / 3, lagP95: 50, longTasks: 2 },
  /** G2 품질 등급(스펙 7절) */
  grade: { offE50: 0.15, offValid: 0.6, lowE50: 0.08, lowValid: 0.8, minGridPoints: 7 },
};
