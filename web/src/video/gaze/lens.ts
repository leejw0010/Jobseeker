/** G1 렌즈 응시 분류기(설계 5절). 화면 좌표 회귀로 렌즈 위치를 외삽하지 않고, 같은 보정 세션에서 모은
 *  렌즈 응시(양성)와 화면 응시(음성, 특히 화면 위쪽 띠)로 L2 정규화 로지스틱 회귀를 직접 학습한다.
 *  임계값은 묶음 단위 교차 검증으로 보수적으로 정하고 가운데는 unknown으로 둔다. 학습 분포 밖의 입력도 unknown.
 *  교차 검증 수치는 임계값 결정과 진단용이다. 판정 성능은 학습·임계값 선택에 쓰지 않은 별도 응시로만 잰다(calibration.ts). */
import { LENS } from "./constants";
import type { GazeFeatures } from "./features";
import { CalibrationError, groupedFolds, solve, standardizer } from "./regression";
import { nearestRank } from "../stats";

export type LensSample = { f: GazeFeatures; openRatio: number; lens: boolean; topBand: boolean; group: string };
export type LensDecision = "toward" | "away" | "unknown";
export type LensModel = {
  predict(f: GazeFeatures, openRatio: number): { p: number; decision: LensDecision; ood: boolean };
  /** 교차 검증(묶음 단위) 진단: 렌즈 대 위쪽 띠 AUC, 임계값에서의 민감도, 위쪽 띠 오판 비율 */
  cv: { auc: number | null; sensitivity: number; topBandFalse: number };
  thresholds: { hi: number; lo: number };
};

const row = (f: GazeFeatures, openRatio: number) => [f.ex, f.ey, f.hx, f.hy, openRatio];
const dot = (a: number[], b: number[]) => a.reduce((s, v, i) => s + v * b[i], 0);
const sigmoid = (z: number) => 1 / (1 + Math.exp(-Math.max(-30, Math.min(30, z))));
const frac = (xs: number[], ok: (x: number) => boolean) => (xs.length ? xs.filter(ok).length / xs.length : 0);

/** 가중 L2 로지스틱 회귀(뉴턴법). X의 첫 열은 절편(벌점 없음). 완전히 갈리는 데이터에서도 L2 덕분에 계수가 유한하다 */
export function fitLogistic(X: number[][], y: number[], w: number[], l2: number): number[] {
  const k = X[0].length;
  let b = new Array<number>(k).fill(0);
  for (let it = 0; it < LENS.maxIter; it++) {
    const g = new Array<number>(k).fill(0);
    const H = Array.from({ length: k }, () => new Array<number>(k).fill(0));
    X.forEach((x, n) => {
      const p = sigmoid(dot(x, b)), r = w[n] * (y[n] - p), s = w[n] * p * (1 - p);
      for (let i = 0; i < k; i++) {
        g[i] += r * x[i];
        for (let j = 0; j < k; j++) H[i][j] += s * x[i] * x[j];
      }
    });
    for (let i = 1; i < k; i++) { g[i] -= l2 * b[i]; H[i][i] += l2; }
    H[0][0] += 1e-9;
    const d = solve(H, g);
    b = b.map((v, i) => v + d[i]);
    if (Math.max(...d.map(Math.abs)) < 1e-8) break;
  }
  return b;
}

/** 양성 확률이 음성보다 큰 쌍의 비율(같으면 반). 한쪽이 비면 null */
export function auc(pos: number[], neg: number[]): number | null {
  if (!pos.length || !neg.length) return null;
  let s = 0;
  for (const p of pos) for (const n of neg) s += p > n ? 1 : p === n ? 0.5 : 0;
  return s / (pos.length * neg.length);
}

/** τ_hi = max(0.8, 위쪽 띠 음성의 오판이 5% 이하가 되는 가장 작은 값), τ_lo = min(0.2, 렌즈 양성의 놓침이 5% 이하가 되는 가장 큰 값).
 *  그래서 언제나 τ_lo ≤ 0.2 < 0.8 ≤ τ_hi이고 가운데 unknown 띠가 남는다 */
export function lensThresholds(cvPos: number[], cvTopNeg: number[]): { hi: number; lo: number } {
  const neg = [...cvTopNeg].sort((a, b) => b - a), allowNeg = Math.floor(LENS.topFalseRate * neg.length);
  const t1 = neg.length && allowNeg < neg.length ? neg[allowNeg] + 1e-9 : 0;
  const pos = [...cvPos].sort((a, b) => a - b), allowPos = Math.floor(LENS.missRate * pos.length);
  const t0 = pos.length && allowPos < pos.length ? pos[allowPos] - 1e-9 : 1;
  return { hi: Math.max(LENS.hiMin, t1), lo: Math.min(LENS.loMax, t0) };
}

export function trainLens(samples: LensSample[]): LensModel {
  const posGroups = new Set(samples.filter((s) => s.lens).map((s) => s.group));
  const topGroups = new Set(samples.filter((s) => !s.lens && s.topBand).map((s) => s.group));
  if (posGroups.size < 2 || topGroups.size < 2) throw new CalibrationError("insufficient_lens_groups");
  const rows = samples.map((s) => row(s.f, s.openRatio)), y = samples.map((s) => (s.lens ? 1 : 0));
  const fitOn = (idx: number[]) => {
    const z = standardizer(idx.map((i) => rows[i]));
    const nPos = idx.filter((i) => y[i]).length, nNeg = idx.length - nPos;
    // 양성(렌즈 응시)이 적으므로 두 클래스의 가중치 합을 같게 맞춘다
    const w = idx.map((i) => idx.length / (2 * Math.max(1, y[i] ? nPos : nNeg)));
    const b = fitLogistic(idx.map((i) => [1, ...z.apply(rows[i])]), idx.map((i) => y[i]), w, LENS.l2);
    return { z, p: (r: number[]) => sigmoid(dot([1, ...z.apply(r)], b)) };
  };
  const cvP = new Array<number>(samples.length).fill(0);
  for (const { train, test } of groupedFolds(samples.map((s) => s.group))) {
    const m = fitOn(train);
    for (const i of test) cvP[i] = m.p(rows[i]);
  }
  const cvPos = samples.flatMap((s, i) => (s.lens ? [cvP[i]] : []));
  const cvTop = samples.flatMap((s, i) => (!s.lens && s.topBand ? [cvP[i]] : []));
  const thresholds = lensThresholds(cvPos, cvTop);
  const all = fitOn(samples.map((_, i) => i));
  // 분포 밖 검사: 표준화한 학습 표본의 공분산(조금 줄여 안정화)으로 잰 마할라노비스 거리의 99번째 백분위
  const Z = rows.map((r) => all.z.apply(r)), k = Z[0].length;
  const cov = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) =>
    Z.reduce((a, r) => a + r[i] * r[j], 0) / Z.length + (i === j ? 0.05 : 0)));
  const inv = Array.from({ length: k }, (_, j) => solve(cov, Array.from({ length: k }, (_, i) => (i === j ? 1 : 0))));
  const dist = (zr: number[]) => Math.sqrt(Math.max(0, zr.reduce((a, zi, i) => a + zi * zr.reduce((b, zj, j) => b + inv[j][i] * zj, 0), 0)));
  const cutoff = nearestRank(Z.map(dist), LENS.oodPercentile);
  return {
    thresholds,
    cv: { auc: auc(cvPos, cvTop), sensitivity: frac(cvPos, (p) => p >= thresholds.hi), topBandFalse: frac(cvTop, (p) => p >= thresholds.hi) },
    predict(f, openRatio) {
      const r = row(f, openRatio), ood = dist(all.z.apply(r)) > cutoff, p = all.p(r);
      return { p, ood, decision: ood ? "unknown" : p >= thresholds.hi ? "toward" : p <= thresholds.lo ? "away" : "unknown" };
    },
  };
}
