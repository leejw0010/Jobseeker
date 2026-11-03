import { expect, test } from "@playwright/test";
import { faceFeatures, summarizeSegment, type FaceSample, type Point } from "../src/video/metrics";
import { createDGrid, createRateStats, nextRate, type RateSnapshot } from "../src/video/gaze/sampler";

// 시선 분석(G) 0단계의 계산 테스트. 브라우저 없이 계산만 확인하므로 desktop 프로젝트에서만 돈다
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop"));

/** D 계산용 가운데 얼굴(video-metrics.spec.ts와 같은 모양) */
function dFace(): Point[] {
  const pts: Point[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
  pts[1] = { x: 0.5, y: 0.5 };
  pts[10] = { x: 0.5, y: 0.35 };
  pts[152] = { x: 0.5, y: 0.7 };
  pts[234] = { x: 0.4, y: 0.5 };
  pts[454] = { x: 0.6, y: 0.5 };
  return pts;
}

// ───────── Task 1: D 250ms 격자, 표본 주기 정책 ─────────

test("D grid: 10·15Hz input gives the same D summary as 4Hz", () => {
  const face = dFace();
  const state = (t: number) => (t % 3000 < 2000 ? face : null); // 2초 얼굴, 1초 없음 반복
  const run = (hz: number) => {
    const g = createDGrid();
    const out: FaceSample[] = [];
    for (let t = 0; t < 30_000; t += 1000 / hz) if (g.accept(t)) out.push({ t, ...faceFeatures(state(t)) });
    return summarizeSegment(out, { start: 0, end: 30_000 });
  };
  const [a, b, c] = [run(4), run(10), run(15)];
  for (const k of ["analyzedMs", "detectedMs", "noneMs"] as const) {
    expect(Math.abs(b[k] - a[k])).toBeLessThanOrEqual(250 * 10); // 상태가 20번 바뀌고, 바뀔 때마다 표본 시각 차이는 100ms 이하
    expect(Math.abs(c[k] - a[k])).toBeLessThanOrEqual(250 * 10);
  }
  expect(b.samples).toBeGreaterThanOrEqual(115);
  expect(b.samples).toBeLessThanOrEqual(121); // 평균 초당 4회
  expect(c.samples).toBeGreaterThanOrEqual(115);
  expect(c.samples).toBeLessThanOrEqual(121);
});

test("D grid is time-based across gaps", () => {
  const g = createDGrid();
  expect(g.accept(0)).toBe(true);
  expect(g.accept(100)).toBe(false);
  expect(g.accept(2_100)).toBe(true);
  expect(g.accept(2_200)).toBe(false);
  expect(g.accept(2_250)).toBe(true);
});

test("nextRate steps down on load and up only after 10s healthy, within [4, target]", () => {
  const ok: RateSnapshot = { targetHz: 15, achievedHz: 15, detectP50: 5, detectP95: 8, busyPct: 10, lagP95: 10, longTasks: 0 };
  expect(nextRate(15, 15, { ...ok, busyPct: 30 }, 0)).toBe(10);
  expect(nextRate(10, 15, { ...ok, longTasks: 2 }, 0)).toBe(4);
  expect(nextRate(4, 15, { ...ok, lagP95: 60 }, 0)).toBe(4);
  expect(nextRate(10, 15, ok, 9_000)).toBe(10);
  expect(nextRate(10, 15, ok, 10_000)).toBe(15);
  expect(nextRate(10, 10, ok, 60_000)).toBe(10);
});

test("rate stats summarise the last window: achieved rate, detection percentiles, busy share, lag, long tasks", () => {
  const s = createRateStats(10_000);
  for (let i = 0; i < 100; i++) s.add({ t: i * 100, detectMs: i < 90 ? 10 : 40, lagMs: i % 10 === 0 ? 60 : 5 });
  s.add({ t: 5_000, detectMs: 0, lagMs: 0, longTask: true });
  const r = s.snapshot(10);
  expect(r.targetHz).toBe(10);
  expect(r.achievedHz).toBeCloseTo(10, 0);
  expect(r.detectP50).toBe(10);
  expect(r.detectP95).toBe(40);
  expect(r.busyPct).toBeCloseTo(13, 0); // (90·10 + 10·40) ms / 10초
  expect(r.lagP95).toBe(60);
  expect(r.longTasks).toBe(1);
  s.add({ t: 25_000, detectMs: 10, lagMs: 0 }); // 오래된 표본은 창 밖으로 빠진다
  expect(s.snapshot(10).longTasks).toBe(0);
});

// ───────── Task 2: 눈·고개 특징, 합성 얼굴 ─────────

import { gazeFeatures, type GazeFeatures } from "../src/video/gaze/features";
import { syntheticFace } from "../src/video/gaze/synthetic";

test("features are aspect-corrected and roll-invariant", () => {
  const a = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, aspect: 4 / 3 }), 640, 480) as GazeFeatures;
  const b = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, aspect: 16 / 9 }), 1280, 720) as GazeFeatures;
  const r = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, roll: 0.26 }), 640, 480) as GazeFeatures;
  expect(b.ex).toBeCloseTo(a.ex, 6);
  expect(b.ey).toBeCloseTo(a.ey, 6);
  expect(r.ex).toBeCloseTo(a.ex, 6);
  expect(r.ey).toBeCloseTo(a.ey, 6);
  expect(r.hx).toBeCloseTo(a.hx, 6);
});

test("looking to the user's right lowers ex (raw-frame convention); looking down raises ey", () => {
  const f = (gazeX: number, gazeY: number) => gazeFeatures(syntheticFace({ gazeX, gazeY, yaw: 0, pitch: 0 }), 640, 480) as GazeFeatures;
  expect(f(0.3, 0).ex).toBeLessThan(f(-0.3, 0).ex);
  expect(f(0, 0.2).ey).toBeGreaterThan(f(0, -0.2).ey);
  expect(f(0, -0.2).open).toBeGreaterThan(f(0, 0.2).open); // 위를 보면 윗눈꺼풀이 올라간다
});

test("head turn moves head features, eyes compensating keeps the gaze source in the eyes", () => {
  const turned = gazeFeatures(syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0.3, pitch: 0 }), 640, 480) as GazeFeatures;
  const front = gazeFeatures(syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0 }), 640, 480) as GazeFeatures;
  expect(turned.hx).toBeLessThan(front.hx); // 사용자 오른쪽으로 돌리면 코끝이 원본 프레임 왼쪽(−x)으로
  expect(turned.ex).toBeGreaterThan(front.ex); // 같은 곳을 보려고 눈은 반대로 돈다
});

test("invalid inputs are named, never NaN", () => {
  expect(gazeFeatures(null, 640, 480)).toEqual({ invalid: "no_face" });
  expect(gazeFeatures([], 640, 480)).toEqual({ invalid: "no_face" });
  expect(gazeFeatures(syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, cx: -0.02 }), 640, 480)).toEqual({ invalid: "eyes_outside" });
  const pts = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0 });
  pts[468] = { x: pts[468].x + 0.03, y: pts[468].y };
  expect(gazeFeatures(pts, 640, 480)).toEqual({ invalid: "eyes_unreliable" });
  expect(gazeFeatures(syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0 }).slice(0, 300), 640, 480)).toEqual({ invalid: "eyes_unreliable" });
  const ok = gazeFeatures(syntheticFace({ gazeX: 0.1, gazeY: 0.1, yaw: 0.1, pitch: 0.1, noise: 0.002, seed: 3 }), 640, 480);
  expect(Object.values(ok).every((v) => typeof v === "number" && Number.isFinite(v))).toBe(true);
});

test("synthetic noise is reproducible by seed", () => {
  const a = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, noise: 0.003, seed: 7 });
  const b = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, noise: 0.003, seed: 7 });
  const c = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, noise: 0.003, seed: 8 });
  expect(a).toEqual(b);
  expect(a).not.toEqual(c);
  expect(a).toHaveLength(478);
});

// ───────── Task 3: G2 화면 좌표 회귀 ─────────

import { fitRidge, groupedFolds, selectG2 } from "../src/video/gaze/regression";
import { syntheticGrid } from "../src/video/gaze/synthetic";

test("ridge recovers linear coefficients and stays finite on duplicate columns", () => {
  const X = [...Array(50)].map((_, i) => [1, i / 10, (i % 7) / 7]);
  const y = X.map(([, a, b]) => 3 + 2 * a - 5 * b);
  const w = fitRidge(X, y, 1e-6);
  expect(w[0]).toBeCloseTo(3, 3);
  expect(w[1]).toBeCloseTo(2, 3);
  expect(w[2]).toBeCloseTo(-5, 3);
  const dup = fitRidge(X.map((r) => [...r, r[1]]), y, 0.1);
  expect(dup.every(Number.isFinite)).toBe(true);
  const constant = fitRidge(X.map(() => [1, 0, 0]), y, 0.1); // 특징이 모두 0이어도 NaN 없이 절편만
  expect(constant.every(Number.isFinite)).toBe(true);
});

test("grouped folds never put frames of the held-out group in training", () => {
  const groups = ["a", "a", "b", "b", "c", "c", "a"];
  const folds = groupedFolds(groups);
  expect(folds).toHaveLength(3);
  for (const { train, test } of folds) {
    const held = new Set(test.map((i) => groups[i]));
    expect(held.size).toBe(1);
    expect(train.some((i) => held.has(groups[i]))).toBe(false);
    expect(train.length + test.length).toBe(groups.length);
  }
});

test("grouped CV error reflects per-fixation offsets (no frame-level leakage)", () => {
  // 응시마다 고정된 치우침이 있는 데이터: 특징으로 설명할 수 없으므로 묶음 단위 교차 검증 오차는 커야 한다
  const s = syntheticGrid({ groups: 9, framesPerGroup: 12, groupOffsetPx: 60, seed: 1 });
  expect(selectG2(s).cvMedianPx).toBeGreaterThan(30);
});

test("model selection prefers M1 unless M2 is at least 15% better", () => {
  const linear = selectG2(syntheticGrid({ curvature: 0, seed: 2 }));
  expect(linear.kind).toBe("M1");
  const curved = selectG2(syntheticGrid({ curvature: 0.8, seed: 3 }));
  expect(curved.kind).toBe("M2");
  expect(curved.cvByKind.M2).toBeLessThanOrEqual(curved.cvByKind.M1 * 0.85);
});

test("the fitted model predicts held-out positions on clean data", () => {
  const train = syntheticGrid({ seed: 4 });
  const m = selectG2(train);
  const probe = syntheticGrid({ groups: 9, framesPerGroup: 1, seed: 5, targets: [[0.25, 0.25], [0.75, 0.75]] });
  for (const s of probe) {
    const [x, y] = m.predict(s.f);
    expect(Math.hypot(x - s.target[0], y - s.target[1])).toBeLessThan(40);
  }
});

test("too few groups is an explicit failure", () => {
  expect(() => selectG2(syntheticGrid({ groups: 2, seed: 6 }))).toThrow("insufficient_groups");
});

// ───────── Task 4: G1 렌즈 응시 분류기 ─────────

import { auc, fitLogistic, lensThresholds, trainLens } from "../src/video/gaze/lens";
import { farFeatures, lensFeatures, syntheticLens } from "../src/video/gaze/synthetic";

test("logistic stays finite on perfectly separable data and learns the direction", () => {
  const X = [[1, -2], [1, -1], [1, 1], [1, 2]], y = [0, 0, 1, 1];
  const b = fitLogistic(X, y, [1, 1, 1, 1], 1.0);
  expect(b.every(Number.isFinite)).toBe(true);
  expect(b[1]).toBeGreaterThan(0);
});

test("auc counts pairs, ties as half, and refuses empty input", () => {
  expect(auc([0.9, 0.8], [0.1, 0.2])).toBe(1);
  expect(auc([0.5], [0.5])).toBe(0.5);
  expect(auc([0.1], [0.9])).toBe(0);
  expect(auc([], [0.1])).toBeNull();
});

test("thresholds keep an unknown band even when classes separate", () => {
  expect(lensThresholds([0.95, 0.97, 0.99], [0.01, 0.03, 0.05])).toEqual({ hi: 0.8, lo: 0.2 });
  const t = lensThresholds([0.6, 0.7, 0.9], [0.5, 0.6, 0.85]);
  expect(t.hi).toBeGreaterThanOrEqual(0.85);
  expect(t.lo).toBeLessThanOrEqual(0.2);
});

test("separable lens data: high CV AUC, toward on a lens look, unknown far outside training", () => {
  const m = trainLens(syntheticLens({ lensOffset: 0.25, noise: 0.0002, seed: 5 }));
  expect(m.cv.auc!).toBeGreaterThan(0.95);
  expect(m.cv.sensitivity).toBeGreaterThan(0.8);
  const at = (openRatio: number) => m.predict(lensFeatures(0.25), openRatio);
  expect(at(1.0).decision).toBe("toward");
  expect(at(1.1)).toMatchObject({ decision: "unknown", ood: true }); // 학습 범위 밖의 눈 뜬 정도: 확신하지 않는다
  expect(m.predict(lensFeatures(0.25, 0.3), 1.0).decision).not.toBe("toward"); // 화면 아래쪽(렌즈 아님)
  expect(m.predict(farFeatures(), 1.0)).toMatchObject({ decision: "unknown", ood: true });
});

test("lens at the top-centre of the screen: sensitivity collapses at the conservative threshold", () => {
  const separable = trainLens(syntheticLens({ lensOffset: 0.25, noise: 0.0002, seed: 6 }));
  const m = trainLens(syntheticLens({ lensOffset: 0, noise: 0.0002, seed: 6 }));
  expect(m.cv.sensitivity).toBeLessThan(0.3);
  expect(m.cv.auc!).toBeLessThan(separable.cv.auc!);
});

test("class weights balance 10 positives vs 100 negatives", () => {
  const m = trainLens(syntheticLens({ lensOffset: 0.25, positives: 10, negatives: 100, noise: 0.0002, seed: 7 }));
  expect(m.cv.sensitivity).toBeGreaterThan(0.6);
});

test("too few lens or top-band fixations is an explicit failure", () => {
  const s = syntheticLens({ lensOffset: 0.25, seed: 8 });
  expect(() => trainLens(s.filter((x) => !x.lens || x.group.endsWith("lens-0")))).toThrow("insufficient_lens_groups");
});

// ───────── Task 5: 보정 순서와 실현 가능성 지표 ─────────

import { PROTOCOL, aggregate, classifyRegion, collect, evaluateRun, mockPanelRect, type Fixation } from "../src/video/gaze/calibration";
import { VIEW, fakeFrames, syntheticRun } from "../src/video/gaze/synthetic";

const PANELS = Object.fromEntries([32, 120, 240].map((h) => [h, mockPanelRect(VIEW, h)]));
const noNaN = (v: unknown): boolean => (typeof v === "number" ? !Number.isNaN(v)
  : Array.isArray(v) ? v.every(noNaN) : v && typeof v === "object" ? Object.values(v).every(noNaN) : true);

test("lens and top-band validation fixations are separate from training", () => {
  const val = PROTOCOL.filter((f) => f.role === "validate");
  expect(val.filter((f) => f.target === "lens").map((f) => f.pose).sort()).toEqual(["forward", "left", "right"]);
  expect(val.filter((f) => f.topBand).map((f) => f.target)).toEqual([{ x: 0.4, y: 0.05 }, { x: 0.5, y: 0.05 }, { x: 0.6, y: 0.05 }]);
  expect(PROTOCOL.filter((f) => f.role === "train" && f.target === "lens")).toHaveLength(4);
  expect(new Set(PROTOCOL.map((f) => f.id)).size).toBe(PROTOCOL.length);
});

test("validation positions are never used for training", () => {
  const key = (f: Fixation) => (typeof f.target === "object" ? `${f.target.x},${f.target.y}` : `${f.target}/${f.pose}`);
  const train = new Set(PROTOCOL.filter((f) => f.role === "train").map(key));
  const validate = PROTOCOL.filter((f) => f.role === "validate" && typeof f.target === "object");
  expect(validate.length).toBeGreaterThanOrEqual(9);
  expect(validate.some((f) => train.has(key(f)))).toBe(false);
});

test("group ids are unique per run even when a point is re-measured", () => {
  const a = collect(fakeFrames(20), PROTOCOL[3]), b = collect(fakeFrames(20), PROTOCOL[3]);
  expect(a.group).not.toBe(b.group);
  expect(a.samples).toHaveLength(20);
  const empty = collect([{ t: 0, points: null, width: 640, height: 480, detectMs: 1 }], PROTOCOL[3]);
  expect(empty.samples).toHaveLength(0);
  expect(empty.invalid).toEqual({ no_face: 1 });
});

test("region classification refuses to claim a region smaller than the error", () => {
  const big = { left: 300, top: 200, width: 600, height: 240 }, small = { left: 300, top: 300, width: 600, height: 32 };
  expect(classifyRegion([600, 320], big, VIEW, 40, 60)).toBe("question");
  expect(classifyRegion([600, 205], big, VIEW, 40, 60)).toBe("unknown"); // 경계 띠
  expect(classifyRegion([600, 316], small, VIEW, 40, 60)).toBe("unknown"); // 패널 높이 32 < 2·e80
  expect(classifyRegion([100, 600], big, VIEW, 40, 60)).toBe("ui");
  expect(classifyRegion([600, -200], big, VIEW, 40, 60)).toBe("offscreen");
  expect(classifyRegion([600, -10], big, VIEW, 40, 60)).toBe("unknown"); // 뷰포트 경계 띠
});

test("evaluateRun passes clean synthetic data and fails noisy or inseparable data", () => {
  const clean = evaluateRun(syntheticRun({ noise: 0.0001, seed: 8 }), VIEW, PANELS);
  expect(clean.g2.verdict).toBe("pass");
  expect(clean.g1.verdict).toBe("pass");
  expect(clean.panels.find((p) => p.heightPx === 240)!.hit).toBeGreaterThan(0.8);
  const usable = clean.panels.filter((p) => (p.hit ?? 0) >= 0.8 && (p.falseQuestion ?? 1) <= 0.1).map((p) => p.heightPx);
  expect(clean.minPanelPx).toBe(Math.min(...usable)); // 판정이 쓸모 있는 가장 작은 패널
  const noisier = evaluateRun(syntheticRun({ noise: 0.0004, seed: 14 }), VIEW, PANELS);
  const p32 = noisier.panels.find((p) => p.heightPx === 32)!;
  expect(noisier.g2.e80Px!).toBeGreaterThan(16);
  expect(p32.resolvable).toBe(false); // 오차보다 작은 영역은
  expect(p32.hit).toBe(0); // 봤다고 하지 않는다
  expect(clean.rateVerdict).toBe("pass");
  expect(evaluateRun(syntheticRun({ noise: 0.003, seed: 9 }), VIEW, PANELS).g2.verdict).toBe("fail");
  const inseparable = evaluateRun(syntheticRun({ noise: 0.0001, lensOffset: 0, seed: 10 }), VIEW, PANELS);
  expect(inseparable.g1.verdict).toBe("fail");
  expect(inseparable.g2.verdict).toBe("pass"); // G1이 안 돼도 G2는 그대로
});

test("distance change: either accuracy holds or the position gate blocks most samples", () => {
  const r = evaluateRun(syntheticRun({ noise: 0.0001, seed: 11 }), VIEW, PANELS);
  for (const d of r.distance) expect(d.verdict).toBe("pass");
  expect(r.distance.map((d) => d.pose).sort()).toEqual(["far", "near"]);
});

test("no usable samples is a failure, not NaN", () => {
  const r = evaluateRun(syntheticRun({ validRatio: 0, seed: 12 }), VIEW, PANELS);
  expect(r.g2.verdict).toBe("fail");
  expect(r.g1.verdict).toBe("fail");
  expect(noNaN(r)).toBe(true);
});

test("aggregate exposes only summary numbers and verdicts", () => {
  const out = aggregate(evaluateRun(syntheticRun({ noise: 0.0001, seed: 13 }), VIEW, PANELS));
  expect(Object.values(out).every((v) => typeof v === "number" || typeof v === "string" || v === null)).toBe(true);
  expect(Object.keys(out).some((k) => /sample|point|landmark|frame|coord/i.test(k))).toBe(false);
  expect(out["g1.verdict"]).toBe("pass");
  expect(typeof out["g2.e50Pct"]).toBe("number");
});

// ───────── 0단계 진단(2026-11-03): 렌즈 응시별 확률·분포 밖 비율, 앞→끝 자세 변화, 점별 오차 ─────────

test("diagnostics: per-group lens probabilities, start→end drift, per-point errors", () => {
  const r = evaluateRun(syntheticRun({ noise: 0.0001, seed: 21 }), VIEW, PANELS);
  expect(r.diag.lens.map((g) => g.id)).toEqual(["val-lens-forward", "val-lens-left", "val-lens-right", "val-top-40", "val-top-50", "val-top-60"]);
  const fwd = r.diag.lens.find((g) => g.id === "val-lens-forward")!;
  expect(fwd.medianP!).toBeGreaterThan(0.8);
  expect(fwd.oodRate!).toBeLessThan(0.2);
  expect(fwd.toward! + fwd.away! + fwd.unknown!).toBeCloseTo(1, 6);
  expect(Math.abs(r.diag.drift.open!)).toBeLessThan(0.05);
  expect(Math.abs(r.diag.drift.scale!)).toBeLessThan(0.05);
  expect(Object.keys(r.diag.errors)).toEqual(expect.arrayContaining(["val-25-25", "val-75-75", "val-30-50-left", "val-top-50"]));
  expect(Object.keys(r.diag.fit)).toEqual(expect.arrayContaining(["grid-50-50", "grid-92-92"]));
  expect(r.diag.errors["val-25-25"]!).toBeLessThan(60);
});

test("diagnostics expose a late posture change and refused (out-of-range) lens looks", () => {
  // 끝쪽 렌즈 검증 응시만 고개를 많이 돌리고 눈을 덜 뜬 경우
  const late = (fx: Fixation) => (fx.id === "val-lens-forward" ? { yaw: 0.45, eyeOpen: 0.7 } : {});
  const r = evaluateRun(syntheticRun({ noise: 0.0001, seed: 22, override: late }), VIEW, PANELS);
  expect(r.diag.lens.find((g) => g.id === "val-lens-forward")!.oodRate!).toBeGreaterThan(0.5);
  expect(r.diag.drift.open!).toBeLessThan(-0.2);
  expect(r.diag.drift.hx!).toBeLessThan(0); // 사용자 오른쪽으로 돌리면 코끝이 원본 프레임 −x로
});

test("aggregate includes diagnostics without coordinates", () => {
  const out = aggregate(evaluateRun(syntheticRun({ noise: 0.0001, seed: 23 }), VIEW, PANELS));
  expect(typeof out["diag.lens.val-lens-forward.medianP"]).toBe("number");
  expect(typeof out["diag.drift.open"]).toBe("number");
  expect(typeof out["diag.err.val-25-25"]).toBe("number");
  expect(typeof out["diag.fit.grid-50-50"]).toBe("number");
  expect(Object.keys(out).some((k) => /sample|point|landmark|frame|coord/i.test(k))).toBe(false);
});
