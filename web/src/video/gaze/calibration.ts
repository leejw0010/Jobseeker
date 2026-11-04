/** 0단계 보정 순서와 실현 가능성 지표(설계 7·13절).
 *  - G2(화면 좌표)는 처음 보는 위치에서 좌표 오차와 실제 영역 판정 성능을 함께 낸다.
 *  - G1(렌즈 응시)은 학습에도 임계값 선택에도 쓰지 않은 별도 렌즈·화면 위쪽 응시로만 판정한다.
 *  - 판정(pass/fail/inconclusive)은 1단계로 갈지 정하는 실험 기준이다. 제품의 정확도 보장이 아니다.
 *  특징점·좌표·표본은 메모리에서만 쓰고, aggregate()는 집계 숫자와 판정만 돌려준다. */
import {
  COLLECT_MS, FEASIBILITY, LENS_COLLECT_MS, MIN_VALID, OPEN_MIN_RATIO, POSE_COLLECT_MS, POSE_SETTLE_MS, POS_TOL, SCALE_TOL, SETTLE_MS,
} from "./constants";
import { gazeFeatures, isFeatures, type FeatureInvalid, type GazeFeatures } from "./features";
import { auc, trainLens, type LensModel, type LensSample } from "./lens";
import { CalibrationError, selectG2, type G2Model } from "./regression";
import type { Frame, RateSnapshot } from "./sampler";
import { median, nearestRank } from "../stats";

export type Pose = "forward" | "left" | "right" | "up" | "down" | "near" | "far";
export type Role = "train" | "validate" | "panel" | "distance" | "rate" | "typing" | "rest";
export type Target = { x: number; y: number } | "lens" | "panel" | "typing";
export type Fixation = {
  id: string; role: Role; target: Target; pose: Pose; settleMs: number; collectMs: number; prompt: string;
  /** 화면 위쪽 띠(G1의 어려운 음성) */
  topBand?: boolean;
  panelPx?: number;
  hz?: 4 | 10 | 15;
};
export type Rect = { left: number; top: number; width: number; height: number };
export type Verdict = "pass" | "fail" | "inconclusive";

const pt = (x: number, y: number) => ({ x, y });
const POSE_TEXT: Record<Pose, string> = {
  forward: "고개는 정면 그대로", left: "고개를 살짝 왼쪽으로 돌린 채", right: "고개를 살짝 오른쪽으로 돌린 채",
  up: "고개를 살짝 든 채", down: "고개를 살짝 숙인 채", near: "몸을 약 10cm 앞으로 기울인 채", far: "몸을 약 10cm 뒤로 물린 채",
};
const fx = (id: string, role: Role, target: Target, pose: Pose, settleMs: number, collectMs: number, prompt: string,
  extra: Partial<Fixation> = {}): Fixation => ({ id, role, target, pose, settleMs, collectMs, prompt, ...extra });
const lensPrompt = (pose: Pose) => `${POSE_TEXT[pose]} 카메라 렌즈를 보세요`;
const dotPrompt = (pose: Pose) => `${POSE_TEXT[pose]} 눈으로 점을 보세요`;
const GRID: [number, number][] = [[0.5, 0.5], [0.08, 0.08], [0.5, 0.08], [0.92, 0.08], [0.92, 0.5], [0.08, 0.5],
  [0.08, 0.92], [0.5, 0.92], [0.92, 0.92]];
const pct = (v: number) => Math.round(v * 100);
const distanceBlock = (pose: "near" | "far") => [
  ...([[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]] as const).map(([x, y], i) =>
    fx(`dist-${pose}-${pct(x)}-${pct(y)}`, "distance", pt(x, y), pose, i === 0 ? 2500 : SETTLE_MS, COLLECT_MS, dotPrompt(pose))),
  fx(`dist-${pose}-lens`, "distance", "lens", pose, POSE_SETTLE_MS, LENS_COLLECT_MS, lensPrompt(pose)),
];

/** 0단계 시험 순서. 검증(validate)의 위치는 학습(train)에 한 번도 쓰지 않는다 */
export const PROTOCOL: Fixation[] = [
  fx("lens-1", "train", "lens", "forward", SETTLE_MS, LENS_COLLECT_MS, lensPrompt("forward")),
  fx("rest-1", "rest", pt(0.5, 0.5), "forward", 0, COLLECT_MS, "화면 가운데 점을 보세요"),
  fx("lens-2", "train", "lens", "forward", SETTLE_MS, LENS_COLLECT_MS, lensPrompt("forward")),
  ...GRID.map(([x, y]) => fx(`grid-${pct(x)}-${pct(y)}`, "train", pt(x, y), "forward", SETTLE_MS, COLLECT_MS, dotPrompt("forward"),
    x === 0.5 && y === 0.08 ? { topBand: true } : {})),
  ...(["forward", "left", "right", "up", "down"] as const).map((pose) =>
    fx(`head-${pose}`, "train", pt(0.5, 0.5), pose, POSE_SETTLE_MS, POSE_COLLECT_MS, `가운데 점을 계속 보면서 ${POSE_TEXT[pose]} 있으세요`)),
  ...(["left", "right"] as const).map((pose) => fx(`lens-${pose}`, "train", "lens", pose, POSE_SETTLE_MS, POSE_COLLECT_MS, lensPrompt(pose))),
  ...[0.35, 0.5, 0.65].map((x) => fx(`top-${pct(x)}`, "train", pt(x, 0.02), "forward", SETTLE_MS, COLLECT_MS,
    "고개는 그대로, 화면 맨 위 점을 보세요", { topBand: true })),
  ...([[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]] as const).map(([x, y]) =>
    fx(`val-${pct(x)}-${pct(y)}`, "validate", pt(x, y), "forward", SETTLE_MS, COLLECT_MS, dotPrompt("forward"))),
  fx("val-30-50-left", "validate", pt(0.3, 0.5), "left", POSE_SETTLE_MS, COLLECT_MS, dotPrompt("left")),
  fx("val-70-50-right", "validate", pt(0.7, 0.5), "right", POSE_SETTLE_MS, COLLECT_MS, dotPrompt("right")),
  ...[0.4, 0.5, 0.6].map((x) => fx(`val-top-${pct(x)}`, "validate", pt(x, 0.05), "forward", SETTLE_MS, COLLECT_MS,
    "고개는 그대로, 화면 위쪽 점을 보세요", { topBand: true })),
  ...(["forward", "left", "right"] as const).map((pose) =>
    fx(`val-lens-${pose}`, "validate", "lens", pose, POSE_SETTLE_MS, LENS_COLLECT_MS, lensPrompt(pose))),
  ...FEASIBILITY.panel.heights.map((h) => fx(`panel-${h}`, "panel", "panel", "forward", SETTLE_MS, COLLECT_MS,
    "회색 칸의 가운데를 보세요", { panelPx: h })),
  ...distanceBlock("near"),
  ...distanceBlock("far"),
  ...([4, 10, 15] as const).map((hz) => fx(`rate-${hz}`, "rate", pt(0.5, 0.5), "forward", 1000, 20_000,
    `가운데 점을 편하게 보세요(초당 ${hz}회로 재는 중)`, { hz })),
  fx("typing-10", "typing", "typing", "forward", 1000, 20_000, "아래 칸에 아무 글이나 입력하세요(초당 10회로 재는 중)", { hz: 10 }),
];

/** 진행 화면의 질문 글(.runner-q)이 놓이는 자리를 흉내 낸 가상 질문 패널(0단계 전용, 대략적인 위치) */
export function mockPanelRect(view: { w: number; h: number }, heightPx: number): Rect {
  const width = Math.min(760, 0.9 * view.w);
  return { left: (view.w - width) / 2, top: 0.42 * view.h - heightPx / 2, width, height: heightPx };
}

export type FixationData = {
  fixation: Fixation;
  /** 응시 하나의 묶음 id(실행 안에서 고유. 같은 지점을 다시 재도 새 id) */
  group: string;
  /** 화면 점이면 뷰포트 px, 렌즈·글 입력이면 null */
  target: [number, number] | null;
  frames: number;
  samples: { t: number; f: GazeFeatures }[];
  invalid: Partial<Record<FeatureInvalid["invalid"] | "resolution_changed", number>>;
  rate?: RateSnapshot;
  panelRect?: Rect;
};

let groupSeq = 0;
/** 한 응시 동안의 프레임(정착 시간 뒤의 것) → 유효 특징과 무효 사유별 개수. 특징점은 여기서 버린다 */
export function collect(frames: Frame[], fixation: Fixation,
  opts: { target?: [number, number]; rate?: RateSnapshot; panelRect?: Rect } = {}): FixationData {
  const samples: FixationData["samples"] = [], invalid: FixationData["invalid"] = {};
  const resolution = frames.find((fr) => Number.isFinite(fr.width) && Number.isFinite(fr.height) && fr.width > 0 && fr.height > 0);
  for (const fr of frames) {
    if (!Number.isFinite(fr.t)) { invalid.nonfinite_geometry = (invalid.nonfinite_geometry ?? 0) + 1; continue; }
    if (resolution && Number.isFinite(fr.width) && Number.isFinite(fr.height) && fr.width > 0 && fr.height > 0 && (fr.width !== resolution.width || fr.height !== resolution.height)) {
      invalid.resolution_changed = (invalid.resolution_changed ?? 0) + 1;
      continue;
    }
    const f = gazeFeatures(fr.points, fr.width, fr.height);
    if (isFeatures(f)) samples.push({ t: fr.t, f });
    else invalid[f.invalid] = (invalid[f.invalid] ?? 0) + 1;
  }
  return { fixation, group: `${fixation.id}#${++groupSeq}`, target: opts.target ?? null, frames: frames.length, samples, invalid,
    rate: opts.rate, panelRect: opts.panelRect };
}

/** 예측점의 영역. 여유값 m = e50. 영역이 2·e80보다 작으면 그 영역이라고 하지 않는다(오차가 영역보다 크면 단정하지 않음) */
export function classifyRegion(p: [number, number], rect: Rect, view: { w: number; h: number }, e50: number, e80: number):
  "question" | "ui" | "offscreen" | "unknown" {
  const [x, y] = p;
  const within = (r: Rect, pad: number) =>
    x >= r.left - pad && x <= r.left + r.width + pad && y >= r.top - pad && y <= r.top + r.height + pad;
  const resolvable = Math.min(rect.width, rect.height) >= 2 * e80;
  if (resolvable && within(rect, -e50)) return "question";
  if (within(rect, e50)) return "unknown";
  const vp = { left: 0, top: 0, width: view.w, height: view.h };
  if (within(vp, 0)) return "ui";
  return within(vp, e50) ? "unknown" : "offscreen";
}

// ───────── 평가 ─────────

const frac = <T,>(xs: T[], ok: (x: T) => boolean) => (xs.length ? xs.filter(ok).length / xs.length : null);
/** 실시간 판정과 같은 평활: 최근 0.6초 안의 값으로(점은 중앙값, 확률은 평균) */
const SMOOTH_MS = 600;
const smoothPoints = (ts: number[], ps: [number, number][]) => ps.map((_, i) => {
  const w = ps.filter((__, j) => ts[j] <= ts[i] && ts[j] >= ts[i] - SMOOTH_MS);
  return [median(w.map((p) => p[0])), median(w.map((p) => p[1]))] as [number, number];
});
const smoothMean = (ts: number[], vs: number[]) => vs.map((_, i) => {
  const w = vs.filter((__, j) => ts[j] <= ts[i] && ts[j] >= ts[i] - SMOOTH_MS);
  return w.reduce((a, b) => a + b, 0) / w.length;
});

export type FeasibilityReport = {
  view: { w: number; h: number };
  validRatio: number;
  g2: { verdict: Verdict; reason: string | null; grade: "ok" | "low" | "off"; model: "M1" | "M2" | null; cvMedianPx: number | null;
        gridValid: number; e50Px: number | null; e80Px: number | null; e50Pct: number | null; e80Pct: number | null;
        turnedPx: number | null; turnedRatio: number | null };
  g1: { verdict: Verdict; reason: string | null; cvAuc: number | null; valAuc: number | null; lensForward: number | null;
        lensTurned: number | null; topFalse: number | null; screenFalse: number | null; hi: number | null; lo: number | null };
  panels: { heightPx: number; resolvable: boolean; hit: number | null; unknown: number | null; wrong: number | null;
            falseQuestion: number | null; correctUi: number | null; outsideUnknown: number | null }[];
  minPanelPx: number | null;
  panelVerdict: Verdict;
  distance: { pose: "near" | "far"; gated: number | null; e50Px: number | null; ratio: number | null; lensToward: number | null;
              verdict: Verdict }[];
  rates: { hz: number; achievedHz: number | null; detectP50: number | null; detectP95: number | null; busyPct: number | null;
           lagP95: number | null; longTasks: number | null; valid: number | null; dDetected: number | null; pass: boolean }[];
  typing: { lagP95: number | null; longTasks: number | null; busyPct: number | null } | null;
  /** 진단(판정에는 쓰지 않음): 검증 응시별 렌즈 확률·분포 밖 비율, 시험 앞(렌즈 학습)→끝(렌즈 검증) 자세·눈 변화,
   *  처음 보는 위치의 응시별 오차(errors)와 학습 격자의 맞춤 잔차(fit, 같은 데이터로 학습했으므로 정확도 아님) */
  diag: {
    quality: {
      total: number; accepted: number; poseFlags: number;
      rejected: Partial<Record<FeatureInvalid["invalid"] | "resolution_changed" | "blink", number>>;
    };
    lens: { id: string; n: number; medianP: number | null; oodRate: number | null; toward: number | null; away: number | null;
            unknown: number | null }[];
    drift: Record<"open" | "scale" | "faceX" | "faceY" | "hx" | "hy" | "ex" | "ey", number | null>;
    errors: Record<string, number | null>;
    fit: Record<string, number | null>;
  };
  rateVerdict: Verdict;
  recommendedHz: 4 | 10 | 15;
};

/** 비율 지표의 분모 하한(뷰포트 너비의 2%). 아주 작은 오차끼리의 비율은 의미가 없어서 */
const RATIO_FLOOR = 0.02;

export function evaluateRun(data: FixationData[], view: { w: number; h: number }, panelRects: Record<number, Rect> = {}): FeasibilityReport {
  const F = FEASIBILITY;
  const of = (pred: (f: Fixation) => boolean) => data.filter((d) => pred(d.fixation));
  const enough = (d: FixationData) => usable(d).length >= MIN_VALID;
  const isScreen = (f: Fixation) => typeof f.target === "object";
  // 기준값: 정면 렌즈 응시(학습)
  const baseF = of((f) => f.role === "train" && f.target === "lens" && f.pose === "forward").flatMap((d) => d.samples.map((s) => s.f));
  const base = baseF.length >= MIN_VALID && median(baseF.map((f) => f.open)) > 0 ? { open: median(baseF.map((f) => f.open)), scale: median(baseF.map((f) => f.scale)),
    x: median(baseF.map((f) => f.faceX)), y: median(baseF.map((f) => f.faceY)) } : null;
  const blink = (f: GazeFeatures) => f.open <= 0 || (!!base && f.open / base.open < OPEN_MIN_RATIO);
  const usable = (d: FixationData) => d.samples.filter((s) => !blink(s.f));
  const poseFlag = (f: GazeFeatures) => !!base && (Math.abs(f.scale / base.scale - 1) > SCALE_TOL
    || Math.abs(f.faceX - base.x) > POS_TOL || Math.abs(f.faceY - base.y) > POS_TOL);
  const calib = of((f) => ["train", "validate", "panel", "distance"].includes(f.role));
  const totalFrames = calib.reduce((a, d) => a + d.frames, 0);
  const validRatio = totalFrames ? calib.reduce((a, d) => a + usable(d).length, 0) / totalFrames : 0;

  // ── G2 ──
  const trainScreen = of((f) => f.role === "train" && isScreen(f)).filter(enough);
  const gridValid = trainScreen.filter((d) => d.fixation.id.startsWith("grid-")).length;
  let g2: G2Model | null = null, g2Reason: string | null = null;
  if (gridValid < F.grade.minGridPoints) g2Reason = "insufficient_grid";
  else {
    try {
      g2 = selectG2(trainScreen.flatMap((d) => usable(d).map((s) => ({ f: s.f, target: d.target!, group: d.group }))));
    } catch (e) {
      g2Reason = e instanceof CalibrationError ? e.code : "fit_failed";
    }
  }
  const preds = (d: FixationData): ([number, number] | null)[] => {
    if (!g2) return [];
    const valid = usable(d), smoothed = smoothPoints(valid.map((s) => s.t), valid.map((s) => g2!.predict(s.f)));
    let i = 0;
    return d.samples.map((s) => blink(s.f) ? null : smoothed[i++]);
  };
  const fixError = (d: FixationData) => {
    const p = g2 && d.target && enough(d) ? usable(d).map((s) => g2!.predict(s.f)) : null;
    return p ? Math.hypot(median(p.map((q) => q[0])) - d.target![0], median(p.map((q) => q[1])) - d.target![1]) : null;
  };
  const val4 = of((f) => f.role === "validate" && isScreen(f) && f.pose === "forward" && !f.topBand);
  const valTurned = of((f) => f.role === "validate" && isScreen(f) && (f.pose === "left" || f.pose === "right"));
  const errs = val4.map(fixError).filter((e): e is number => e !== null);
  const sufficientValidation = val4.length >= 4 && errs.length === val4.length;
  const e50 = sufficientValidation ? median(errs) : null, e80 = sufficientValidation ? nearestRank(errs, 0.8) : null;
  const turnedErrs = valTurned.map(fixError).filter((e): e is number => e !== null);
  const turned = turnedErrs.length ? median(turnedErrs) : null;
  const floor = RATIO_FLOOR * view.w;
  const turnedRatio = turned !== null && e50 !== null ? turned / Math.max(e50, floor) : null;
  const e50Pct = e50 !== null ? e50 / view.w : null, e80Pct = e80 !== null ? e80 / view.w : null;
  const grade: "ok" | "low" | "off" = !g2 || e50Pct === null || validRatio < F.grade.offValid || e50Pct > F.grade.offE50 ? "off"
    : e50Pct > F.grade.lowE50 || validRatio < F.grade.lowValid ? "low" : "ok";
  const g2Verdict: Verdict = !g2 || e50Pct === null || e50Pct > F.h2.e50Fail || validRatio < F.h2.validFail ? "fail"
    : e50Pct <= F.h2.e50Pass && e80Pct! <= F.h2.e80Pass && (turnedRatio ?? Infinity) <= F.h2.turnedRatio && validRatio >= F.h2.validPass
      ? "pass" : "inconclusive";

  // ── G1: 학습(train)으로 만들고, 처음 보는 검증 응시로만 판정 ──
  const openRatio = (f: GazeFeatures) => (base ? f.open / base.open : 1);
  const lensSamples: LensSample[] = of((f) => f.role === "train" && (f.target === "lens" || isScreen(f))).flatMap((d) =>
    usable(d).map((s) => ({ f: s.f, openRatio: openRatio(s.f), lens: d.fixation.target === "lens", topBand: !!d.fixation.topBand,
      group: d.group })));
  let lens: LensModel | null = null, g1Reason: string | null = null;
  if (!base) g1Reason = "no_lens_baseline";
  else {
    try { lens = trainLens(lensSamples); } catch (e) { g1Reason = e instanceof CalibrationError ? e.code : "fit_failed"; }
  }
  const lensRun = (d: FixationData) => {
    if (!lens) return [];
    const valid = usable(d), ts = valid.map((s) => s.t), out = valid.map((s) => lens!.predict(s.f, openRatio(s.f)));
    const p = smoothMean(ts, out.map((o) => o.p));
    let i = 0;
    // Blink observations stay in held-out decision denominators as unknown. They never enter fitting or AUC scores.
    return d.samples.map((s): { p: number | null; ood: boolean; decision: "unknown" | "toward" | "away" } => {
      if (blink(s.f)) return { p: null, ood: false, decision: "unknown" };
      const j = i++, o = out[j];
      return { p: p[j], ood: o.ood, decision: o.ood ? "unknown" : p[j] >= lens!.thresholds.hi ? "toward"
        : p[j] <= lens!.thresholds.lo ? "away" : "unknown" };
    });
  };
  const lensVal = (pose: Pose) => of((f) => f.role === "validate" && f.target === "lens" && f.pose === pose).flatMap(lensRun);
  const lensFwd = lensVal("forward"), lensTurn = [...lensVal("left"), ...lensVal("right")];
  const topVal = of((f) => f.role === "validate" && !!f.topBand).flatMap(lensRun);
  const screenVal = val4.flatMap(lensRun);
  const probabilities = (xs: { p: number | null }[]) => xs.flatMap((o) => o.p === null ? [] : [o.p]);
  const valAuc = auc(probabilities([...lensFwd, ...lensTurn]), probabilities(topVal));
  const lensForward = frac(lensFwd, (o) => o.decision === "toward"), lensTurned = frac(lensTurn, (o) => o.decision === "toward");
  const topFalse = frac(topVal, (o) => o.decision === "toward"), screenFalse = frac(screenVal, (o) => o.decision === "toward");
  const g1Verdict: Verdict = !lens || valAuc === null || lensForward === null || topFalse === null
    || valAuc < F.h1.aucFail || lensForward < F.h1.lensFail || topFalse > F.h1.topFalseFail ? "fail"
    : valAuc >= F.h1.aucPass && lensForward >= F.h1.lensPass && (lensTurned ?? 0) >= F.h1.lensTurnedPass && topFalse <= F.h1.topFalsePass
      ? "pass" : "inconclusive";
  if (lens && g1Verdict === "fail" && !g1Reason) g1Reason = "lens_vs_top_inseparable";

  // ── G2 영역 판정 성능(패널 높이별) ──
  const outsideVal = [...val4, ...valTurned];
  const panels = F.panel.heights.map((h) => {
    const d = of((f) => f.role === "panel" && f.panelPx === h)[0];
    const rect = d?.panelRect ?? panelRects[h] ?? mockPanelRect(view, h);
    const resolvable = e80 !== null && Math.min(rect.width, rect.height) >= 2 * e80;
    if (!g2 || e50 === null || e80 === null) return { heightPx: h, resolvable, hit: null, unknown: null, wrong: null,
      falseQuestion: null, correctUi: null, outsideUnknown: null };
    const cls = (dd: FixationData) => preds(dd).map((p) => p ? classifyRegion(p, rect, view, e50, e80) : "unknown");
    const inside = d ? cls(d) : [];
    const outside = outsideVal.filter((v) => v.target && !(v.target[0] >= rect.left && v.target[0] <= rect.left + rect.width
      && v.target[1] >= rect.top && v.target[1] <= rect.top + rect.height)).flatMap(cls);
    return { heightPx: h, resolvable, hit: frac(inside, (c) => c === "question"), unknown: frac(inside, (c) => c === "unknown"),
      wrong: frac(inside, (c) => c === "ui" || c === "offscreen"), falseQuestion: frac(outside, (c) => c === "question"),
      correctUi: frac(outside, (c) => c === "ui"), outsideUnknown: frac(outside, (c) => c === "unknown") };
  });
  const usablePanels = panels.filter((p) => (p.hit ?? 0) >= F.panel.hitPass && (p.falseQuestion ?? 1) <= F.panel.falseQuestionMax);
  const minPanelPx = usablePanels.length ? Math.min(...usablePanels.map((p) => p.heightPx)) : null;
  const panelVerdict: Verdict = minPanelPx !== null ? "pass" : Math.max(...panels.map((p) => p.hit ?? 0)) < F.panel.hitFail ? "fail"
    : "inconclusive";

  // ── 거리 변화 ──
  const distance = (["near", "far"] as const).map((pose) => {
    const block = of((f) => f.role === "distance" && f.pose === pose);
    const gatedOf = (f: GazeFeatures) => !!base && (Math.abs(f.scale / base.scale - 1) > SCALE_TOL
      || Math.abs(f.faceX - base.x) > POS_TOL || Math.abs(f.faceY - base.y) > POS_TOL);
    const all = block.flatMap((d) => d.samples);
    const gated = frac(all, (s) => gatedOf(s.f));
    const screenErrs = block.filter((d) => d.target).map((d) => fixError({ ...d, samples: usable(d).filter((s) => !gatedOf(s.f)) }))
      .filter((e): e is number => e !== null);
    const e = screenErrs.length ? median(screenErrs) : null;
    const ratio = e !== null && e50 !== null ? e / Math.max(e50, floor) : null;
    const lensToward = frac(block.filter((d) => d.fixation.target === "lens").flatMap(lensRun), (o) => o.decision === "toward");
    const verdict: Verdict = gated === null ? "inconclusive"
      : (ratio === null && gated > 0) || (ratio !== null && ratio <= F.distance.e50Ratio) || gated >= F.distance.gatedPass ? "pass"
        : ratio !== null && ratio > F.distance.e50FailRatio && gated < F.distance.gatedFail ? "fail" : "inconclusive";
    return { pose, gated, e50Px: e, ratio, lensToward, verdict };
  });

  // ── 표본 주기 ──
  const rates = ([4, 10, 15] as const).map((hz) => {
    const d = of((f) => f.role === "rate" && f.hz === hz)[0], r = d?.rate;
    const pass = !!r && r.achievedHz >= F.rate.achievedMin * hz && r.detectP95 <= (1000 / hz) * F.rate.detectShare
      && r.lagP95 <= F.rate.lagP95 && r.longTasks <= F.rate.longTasks;
    return { hz, achievedHz: r?.achievedHz ?? null, detectP50: r?.detectP50 ?? null, detectP95: r?.detectP95 ?? null,
      busyPct: r?.busyPct ?? null, lagP95: r?.lagP95 ?? null, longTasks: r?.longTasks ?? null,
      valid: d && d.frames ? d.samples.length / d.frames : null,
      dDetected: d && d.frames ? 1 - (d.invalid.no_face ?? 0) / d.frames : null, pass };
  });
  const typingD = of((f) => f.role === "typing")[0];
  const typing = typingD?.rate ? { lagP95: typingD.rate.lagP95, longTasks: typingD.rate.longTasks, busyPct: typingD.rate.busyPct } : null;
  // ── 진단 ──
  const LENS_DIAG = ["val-lens-forward", "val-lens-left", "val-lens-right", "val-top-40", "val-top-50", "val-top-60"];
  const diagLens = LENS_DIAG.map((id) => {
    const runs = of((f) => f.id === id).flatMap(lensRun);
    return { id, n: runs.length, medianP: probabilities(runs).length ? median(probabilities(runs)) : null, oodRate: frac(runs, (o) => o.ood),
      toward: frac(runs, (o) => o.decision === "toward"), away: frac(runs, (o) => o.decision === "away"),
      unknown: frac(runs, (o) => o.decision === "unknown") };
  });
  const endF = of((f) => f.id === "val-lens-forward").flatMap((d) => usable(d).map((s) => s.f));
  const mid = (fs: GazeFeatures[], k: keyof GazeFeatures) => median(fs.map((f) => f[k]));
  const delta = (k: keyof GazeFeatures) => (baseF.length && endF.length ? mid(endF, k) - mid(baseF, k) : null);
  const ratio = (k: keyof GazeFeatures) => {
    if (!baseF.length || !endF.length) return null;
    const baseline = mid(baseF, k);
    const value = baseline > 0 ? mid(endF, k) / baseline - 1 : NaN;
    return Number.isFinite(value) ? value : null;
  };
  const drift = { open: ratio("open"), scale: ratio("scale"), faceX: delta("faceX"), faceY: delta("faceY"), hx: delta("hx"),
    hy: delta("hy"), ex: delta("ex"), ey: delta("ey") };
  const errors = Object.fromEntries(of((f) => f.role === "validate" && isScreen(f)).map((d) => [d.fixation.id, fixError(d)]));
  const fit = Object.fromEntries(of((f) => f.role === "train" && f.id.startsWith("grid-")).map((d) => [d.fixation.id, fixError(d)]));

  const quality: FeasibilityReport["diag"]["quality"] = { total: 0, accepted: 0, poseFlags: 0, rejected: {} };
  for (const d of data) {
    quality.total += d.frames;
    quality.accepted += usable(d).length;
    quality.poseFlags += d.samples.filter((s) => poseFlag(s.f)).length;
    for (const [reason, count] of Object.entries(d.invalid)) {
      const k = reason as keyof typeof quality.rejected;
      quality.rejected[k] = (quality.rejected[k] ?? 0) + (count ?? 0);
    }
    const n = d.samples.filter((s) => blink(s.f)).length;
    if (n) quality.rejected.blink = (quality.rejected.blink ?? 0) + n;
  }

  const r10 = rates.find((r) => r.hz === 10)!, r15 = rates.find((r) => r.hz === 15)!;
  const rateVerdict: Verdict = r10.achievedHz === null ? "inconclusive" : r10.pass ? "pass" : "fail";
  const recommendedHz = r15.pass && r10.pass ? 15 : r10.pass ? 10 : 4;

  return {
    view, validRatio,
    g2: { verdict: g2Verdict, reason: g2Reason, grade, model: g2?.kind ?? null, cvMedianPx: g2?.cvMedianPx ?? null, gridValid,
      e50Px: e50, e80Px: e80, e50Pct, e80Pct, turnedPx: turned, turnedRatio },
    g1: { verdict: g1Verdict, reason: g1Reason, cvAuc: lens?.cv.auc ?? null, valAuc, lensForward, lensTurned, topFalse, screenFalse,
      hi: lens?.thresholds.hi ?? null, lo: lens?.thresholds.lo ?? null },
    panels, minPanelPx, panelVerdict, distance, rates, typing, rateVerdict, recommendedHz,
    diag: { lens: diagLens, drift, errors, fit, quality },
  };
}

/** 사용자가 복사해 기록할 집계(숫자와 판정만, 특징점·좌표·표본 없음) */
export function aggregate(r: FeasibilityReport): Record<string, number | string | null> {
  const out: Record<string, number | string | null> = {};
  const put = (prefix: string, o: Record<string, unknown>) => {
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === "number") out[`${prefix}${k}`] = Number.isFinite(v) ? Math.round(v * 1000) / 1000 : null;
      else if (typeof v === "string" || v === null) out[`${prefix}${k}`] = v as string | null;
      else if (typeof v === "boolean") out[`${prefix}${k}`] = v ? "yes" : "no";
    }
  };
  put("view.", r.view);
  out.validRatio = Math.round(r.validRatio * 1000) / 1000;
  put("g2.", r.g2);
  put("g1.", r.g1);
  r.panels.forEach((p) => put(`panel.${p.heightPx}.`, p));
  out.minPanelPx = r.minPanelPx;
  out["panel.verdict"] = r.panelVerdict;
  r.distance.forEach((d) => put(`distance.${d.pose}.`, d));
  r.rates.forEach((x) => put(`rate.${x.hz}.`, x));
  if (r.typing) put("typing.", r.typing);
  out["rate.verdict"] = r.rateVerdict;
  out["rate.recommendedHz"] = r.recommendedHz;
  r.diag.lens.forEach((g) => put(`diag.lens.${g.id}.`, g));
  put("diag.drift.", r.diag.drift);
  put("diag.err.", r.diag.errors);
  put("diag.fit.", r.diag.fit);
  put("diag.quality.", r.diag.quality);
  put("diag.quality.rejected.", r.diag.quality.rejected);
  return out;
}
