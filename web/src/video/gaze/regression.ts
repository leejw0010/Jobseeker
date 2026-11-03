/** G2 화면 좌표 회귀(설계 6절). 표준화한 시선 특징 → 보정할 때의 뷰포트 CSS 픽셀 좌표.
 *  후보는 선형(M1)과 정규화 2차(M2) 릿지. 응시 하나(묶음)의 프레임은 학습과 검증에 나뉘어 들어가지 않는다(누출 금지).
 *  교차 검증 오차는 모델 선택에만 쓰고 정확도로 보고하지 않는다(정확도는 처음 보는 검증 위치로만 잰다). */
import { LAMBDAS, M2_GAIN } from "./constants";
import type { GazeFeatures } from "./features";
import { median } from "../stats";

export class CalibrationError extends Error {
  constructor(readonly code: string) {
    super(code);
    this.name = "CalibrationError";
  }
}

export type GroupedSample = { f: GazeFeatures; target: [number, number]; group: string };
export type ModelKind = "M1" | "M2";
export type G2Model = {
  kind: ModelKind;
  lambda: number;
  /** 묶음 하나씩 뺀 교차 검증에서 묶음별 오차 중앙값의 중앙값(px). 선택용 */
  cvMedianPx: number;
  cvByKind: Record<ModelKind, number>;
  predict(f: GazeFeatures): [number, number];
};

const design = (f: GazeFeatures, kind: ModelKind): number[] =>
  kind === "M1" ? [f.ex, f.ey, f.hx, f.hy] : [f.ex, f.ey, f.hx, f.hy, f.ex * f.ex, f.ey * f.ey, f.ex * f.ey];


/** 열별 평균·표준편차로 표준화한다. 값이 변하지 않는 열은 0이 된다(릿지가 계수를 0으로 둔다) */
export function standardizer(rows: number[][]) {
  const k = rows[0]?.length ?? 0;
  const mean = Array.from({ length: k }, (_, j) => rows.reduce((a, r) => a + r[j], 0) / rows.length);
  const std = mean.map((m, j) => {
    const v = rows.reduce((a, r) => a + (r[j] - m) ** 2, 0) / rows.length;
    return v > 1e-18 ? Math.sqrt(v) : 1;
  });
  return { mean, std, apply: (r: number[]) => r.map((x, j) => (x - mean[j]) / std[j]) };
}

/** 정규방정식 (XᵀX + λD)w = Xᵀy. X의 첫 열은 절편(벌점 없음). 부분 피벗 가우스 소거로 직접 푼다 */
export function fitRidge(X: number[][], y: number[], lambda: number): number[] {
  const k = X[0].length;
  const A = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) => X.reduce((a, r) => a + r[i] * r[j], 0)));
  const b = Array.from({ length: k }, (_, i) => X.reduce((a, r, n) => a + r[i] * y[n], 0));
  for (let i = 1; i < k; i++) A[i][i] += lambda;
  return solve(A, b);
}

/** 작은 선형계 풀이. 특이에 가까우면 대각에 아주 작은 값을 더해 NaN 대신 유한한 해를 낸다 */
export function solve(A0: number[][], b0: number[]): number[] {
  const n = b0.length;
  const A = A0.map((r) => [...r]), b = [...b0];
  const scale = Math.max(1e-12, ...A.map((r, i) => Math.abs(r[i])));
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]];
    [b[c], b[p]] = [b[p], b[c]];
    if (Math.abs(A[c][c]) < 1e-12 * scale) A[c][c] += 1e-9 * scale;
    for (let r = c + 1; r < n; r++) {
      const f = A[r][c] / A[c][c];
      if (!f) continue;
      for (let j = c; j < n; j++) A[r][j] -= f * A[c][j];
      b[r] -= f * b[c];
    }
  }
  const x = new Array<number>(n).fill(0);
  for (let r = n - 1; r >= 0; r--) {
    let s = b[r];
    for (let j = r + 1; j < n; j++) s -= A[r][j] * x[j];
    x[r] = s / A[r][r];
  }
  return x;
}

/** 묶음 하나씩 빼기. 같은 묶음의 프레임은 모두 같은 쪽에 들어간다 */
export function groupedFolds(groups: string[]): { train: number[]; test: number[] }[] {
  return [...new Set(groups)].map((g) => ({
    train: groups.flatMap((x, i) => (x === g ? [] : [i])),
    test: groups.flatMap((x, i) => (x === g ? [i] : [])),
  }));
}

function fit(samples: GroupedSample[], kind: ModelKind, lambda: number) {
  const rows = samples.map((s) => design(s.f, kind));
  const z = standardizer(rows);
  const X = rows.map((r) => [1, ...z.apply(r)]);
  const wx = fitRidge(X, samples.map((s) => s.target[0]), lambda);
  const wy = fitRidge(X, samples.map((s) => s.target[1]), lambda);
  return (f: GazeFeatures): [number, number] => {
    const x = [1, ...z.apply(design(f, kind))];
    return [x.reduce((a, v, j) => a + v * wx[j], 0), x.reduce((a, v, j) => a + v * wy[j], 0)];
  };
}

function cvError(samples: GroupedSample[], kind: ModelKind, lambda: number): number {
  const groups = samples.map((s) => s.group);
  const perGroup = groupedFolds(groups).map(({ train, test }) => {
    const predict = fit(train.map((i) => samples[i]), kind, lambda);
    return median(test.map((i) => {
      const [x, y] = predict(samples[i].f);
      return Math.hypot(x - samples[i].target[0], y - samples[i].target[1]);
    }));
  });
  return median(perGroup);
}

/** M1·M2와 λ를 묶음 단위 교차 검증으로 고르고 전체 표본으로 다시 맞춘다. M2는 M1보다 오차가 15% 이상 작을 때만 */
export function selectG2(samples: GroupedSample[], lambdas: number[] = LAMBDAS): G2Model {
  if (new Set(samples.map((s) => s.group)).size < 3) throw new CalibrationError("insufficient_groups");
  const best = (kind: ModelKind) => lambdas
    .map((lambda) => ({ lambda, err: cvError(samples, kind, lambda) }))
    .reduce((a, b) => (b.err < a.err ? b : a));
  const m1 = best("M1"), m2 = best("M2");
  const pick = m2.err <= (1 - M2_GAIN) * m1.err ? { kind: "M2" as const, ...m2 } : { kind: "M1" as const, ...m1 };
  return { kind: pick.kind, lambda: pick.lambda, cvMedianPx: pick.err, cvByKind: { M1: m1.err, M2: m2.err },
           predict: fit(samples, pick.kind, pick.lambda) };
}
