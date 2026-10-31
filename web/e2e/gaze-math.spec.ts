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
