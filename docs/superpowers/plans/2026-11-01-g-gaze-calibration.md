# G. 시선 보정·시선 분석 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 0단계에서 실제 웹캠으로 핵심 가정을 시험한다(H1 렌즈 대 화면 위쪽 구별, H2 처음 보는 위치의 화면 좌표 오차와 필요한 질문 패널 크기, H3 표본 주기). 결과가 기준을 넘으면 1단계에서 보정·실시간 판정·회고를 구현한다.

**Architecture:**
- 기존 `useFaceAnalysis`의 스트림·검출기에 프레임 구독과 가변 주기를 더한다. D는 250ms 격자 표본만 받는다.
- 순수 계산 모듈(`web/src/video/gaze/`)이 특징 → G2 릿지 회귀 / G1 로지스틱 분류기 → 판정을 맡는다.
- 0단계 화면은 개발 전용 "시선 실험실"이고 집계 지표만 보인다.

**Tech Stack:** React 18 + TypeScript + Vite, MediaPipe Face Landmarker 1.1.1(기존), Playwright(계산 테스트·e2e). 새 의존성 없음.

**Spec:** [docs/superpowers/specs/2026-11-01-g-gaze-calibration-design.md](../specs/2026-11-01-g-gaze-calibration-design.md)

## Global Constraints

- 작업 브랜치는 `feature/gaze-calibration`(2026-11-01 승인). 커밋은 로컬에만 하고, push·PR·병합·원격 변경·이력 재작성·강제 옵션은 하지 않는다. 커밋 전 `git diff --cached`와 비밀값·녹음·모델 파일 검사, 커밋 뒤 `git show --stat`.
- `web/`만 바꾼다. 백엔드·API·DB·녹음·STT 코드는 바꾸지 않는다. OpenAI·외부 추론 API·새 의존성을 쓰지 않는다.
- 카메라 스트림(`getUserMedia`)과 검출기는 하나만 쓴다. 두 번째 스트림·검출기를 만들지 않는다. 검출기 설정(`setOptions`, 표정 계수, 변환 행렬)은 바꾸지 않는다.
- D 기준값·분류 규칙·요약 의미는 그대로다. D는 250ms 격자의 각 칸에서 처음 오는 표본만 받는다(시간 기준, 개수 기준이 아님).
- 특징점·좌표·표본·프레임은 메모리에서만 계산하고 버린다. 저장·전송·복사하지 않는다. 실험실이 보이거나 복사하는 것은 집계 지표뿐이다.
- 실험실은 `import.meta.env.DEV && import.meta.env.VITE_GAZE_LAB === "true"`일 때만 경로·모듈을 불러온다. 프로덕션 번들에서 문자열 "시선 실험실"이 나오면 실패다.
- 잠정 기준값은 모두 `web/src/video/gaze/constants.ts` 한 곳에 둔다(스펙 5·7·8·10·13절 값 그대로).
- 묶음(응시 하나)의 id는 실행 안에서 고유하다(같은 지점을 다시 재도 새 id). 교차 검증은 묶음 단위로만 한다.
- 계산 테스트는 `web/e2e/gaze-math.spec.ts`(데스크톱 프로젝트만), 브라우저 흐름은 `web/e2e/gaze-lab.spec.ts`.
- e2e 실행: `cd web && PATH=../backend/.venv/bin:$PATH LD_LIBRARY_PATH=<syslibs> npm run test:e2e -- <파일>`. 스크린샷 보호 절차(AGENTS.md)를 따른다.
- **1단계(Task 8~12)는 사용자가 0단계 결과(Task 7)를 검토하고 진행을 정한 뒤에만 시작한다.** 1단계 Task는 0단계 결과에 따라 고친다.

## Review Focus

1. 같은 지점을 두 번 잰 응시가 같은 묶음 id를 쓰면 교차 검증에서 누출이 생긴다 → id 고유성 테스트(Task 5).
2. 탭이 가려지거나 영상이 늦게 준비돼 표본이 끊긴 뒤에도 D 격자가 시간 기준으로 다음 칸의 첫 표본을 받는다 → 공백 테스트(Task 1).
3. 보정 도중 창 크기·배율이 바뀌면 그 실행을 중단하고 다시 시작하게 한다 → 실험실 e2e(Task 6).
4. 사용자가 다른 곳을 봐 유효 표본이 거의 없거나, 특징이 한 값으로 몰려 행렬이 특이해지면 결과를 내지 않고 실패로 알린다(NaN 금지) → Task 3·5 테스트.
5. 로지스틱 회귀가 완전히 분리되는 데이터에서도 L2 정규화로 계수가 유한하고, 임계값이 정의된다 → Task 4 테스트.

---

## 0단계 — 실현 가능성 시험

### Task 1: 프레임 구독, 가변 주기, D 250ms 격자

**Files:**
- Create: `web/src/video/gaze/sampler.ts`, `web/src/video/gaze/constants.ts`
- Modify: `web/src/components/useFaceAnalysis.ts`(`setInterval` → `setTimeout` 연쇄, 구독·주기 API 추가. 기존 반환값·동작 유지)
- Test: `web/e2e/gaze-math.spec.ts`(새), 회귀 `web/e2e/camera.spec.ts`·`video-metrics.spec.ts`

**Interfaces:**
- Produces:
  - `type Frame = { t: number; points: { x: number; y: number; z?: number }[] | null; width: number; height: number; detectMs: number }`
  - `createDGrid(periodMs = SAMPLE_MS): { accept(t: number): boolean }` — 시각 `t`가 아직 표본을 받지 않은 새 격자 칸이면 true.
  - `createRateStats(windowMs = 10_000): { add(s: { t: number; detectMs: number; lagMs: number; longTask?: boolean }): void; snapshot(targetHz: number): RateSnapshot }`.
    `RateSnapshot = { targetHz, achievedHz, detectP50, detectP95, busyPct, lagP95, longTasks }`.
  - `nextRate(current: 4 | 10 | 15, target: 4 | 10 | 15, s: RateSnapshot, healthySinceMs: number): 4 | 10 | 15` — 스펙 10절 규칙.
  - `useFaceAnalysis()` 반환에 `subscribeFrames(cb: (f: Frame) => void): () => void`, `setTargetHz(hz: 4 | 10 | 15): void`, `rate: RateSnapshot | null`(CAMERA_DEBUG일 때만 갱신)를 더한다.

- [ ] **Step 1: 실패 테스트**

```ts
test("D grid: 10·15Hz input gives the same D summary as 4Hz", () => {
  const state = (t: number) => (t % 3000 < 2000 ? face : null);           // 2초 얼굴, 1초 없음 반복
  const run = (hz: number) => { const g = createDGrid(); const out: FaceSample[] = [];
    for (let t = 0; t < 30_000; t += 1000 / hz) if (g.accept(t)) out.push({ t, ...faceFeatures(state(t)) });
    return summarizeSegment(out, { start: 0, end: 30_000 }); };
  const [a, b, c] = [run(4), run(10), run(15)];
  for (const k of ["analyzedMs", "detectedMs", "noneMs"] as const) {
    expect(Math.abs(b[k] - a[k])).toBeLessThanOrEqual(250 * 10);           // 상태가 20번 바뀌고, 바뀔 때마다 표본 시각 차이는 100ms 이하
    expect(Math.abs(c[k] - a[k])).toBeLessThanOrEqual(250 * 10);
  }
  expect(b.samples).toBeGreaterThanOrEqual(115); expect(b.samples).toBeLessThanOrEqual(121); // 평균 초당 4회
});
test("D grid is time-based across gaps", () => {
  const g = createDGrid(); expect(g.accept(0)).toBe(true); expect(g.accept(100)).toBe(false);
  expect(g.accept(2_100)).toBe(true); expect(g.accept(2_200)).toBe(false); expect(g.accept(2_250)).toBe(true);
});
test("nextRate steps down on load and up only after 10s healthy, within [4, target]", () => {
  const ok = { targetHz: 15, achievedHz: 15, detectP50: 5, detectP95: 8, busyPct: 10, lagP95: 10, longTasks: 0 };
  expect(nextRate(15, 15, { ...ok, busyPct: 30 }, 0)).toBe(10);
  expect(nextRate(10, 15, { ...ok, longTasks: 2 }, 0)).toBe(4);
  expect(nextRate(4, 15, { ...ok, lagP95: 60 }, 0)).toBe(4);
  expect(nextRate(10, 15, ok, 9_000)).toBe(10); expect(nextRate(10, 15, ok, 10_000)).toBe(15);
  expect(nextRate(10, 10, ok, 60_000)).toBe(10);
});
```

- [ ] **Step 2:** `npx playwright test e2e/gaze-math.spec.ts --project=desktop` → FAIL(모듈 없음)
- [ ] **Step 3:** `sampler.ts`·`constants.ts` 구현.
  - `useFaceAnalysis`: 주기를 `setTimeout`으로 다시 거는 방식으로 바꾼다. `tick`에서 검출 시간을 재고, 구독자에게 `Frame`을 넘긴 뒤, `dGrid.accept(t)`일 때만 D 표본을 `segment`에 넣는다.
  - 목표 주기는 기본 4다. 지연 오차는 예정 시각과 실제 시각의 차이로 잰다.
- [ ] **Step 4:** `gaze-math.spec.ts` PASS, `camera.spec.ts`·`video-metrics.spec.ts` PASS(기존 동작 유지).
- [ ] **Step 5:** `git status --short -- web/` (승인 후에는 commit)

### Task 2: 눈·고개 특징 `features.ts`와 합성 얼굴

**Files:**
- Create: `web/src/video/gaze/features.ts`, `web/src/video/gaze/synthetic.ts`(테스트·가짜 검출기 전용 합성 얼굴)
- Test: `web/e2e/gaze-math.spec.ts`

**Interfaces:**
- Consumes: `Frame`(Task 1).
- Produces:
  - `type GazeFeatures = { ex: number; ey: number; open: number; hx: number; hy: number; faceX: number; faceY: number; scale: number; eyeGap: number }`
  - `type FeatureInvalid = { invalid: "no_face" | "eyes_outside" | "eyes_unreliable" }`
  - `gazeFeatures(points, width, height): GazeFeatures | FeatureInvalid`
    - `open`은 원시 비율(눈꺼풀 거리/눈 폭). 기준값 나눗셈은 Task 5.
    - `eyeGap`은 두 눈 `ex`의 차이로, 불일치 판정에 쓴다.
  - `syntheticFace(p: { gazeX: number; gazeY: number; yaw: number; pitch: number; roll?: number; scale?: number; cx?: number; cy?: number; noise?: number; seed?: number; aspect?: number; eyeOpen?: number }): { x: number; y: number }[]`
    - 숨긴 정답 사상으로 478점을 만든다.
    - 규약: 사용자가 자기 오른쪽(`gazeX` 증가)을 보면 원본 프레임에서 홍채 x가 작아진다.

- [ ] **Step 1: 실패 테스트**

```ts
test("features are aspect-corrected and roll-invariant", () => {
  const a = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, aspect: 4 / 3 }), 640, 480) as GazeFeatures;
  const b = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, aspect: 16 / 9 }), 1280, 720) as GazeFeatures;
  const r = gazeFeatures(syntheticFace({ gazeX: 0.2, gazeY: -0.1, yaw: 0, pitch: 0, roll: 0.26 }), 640, 480) as GazeFeatures;
  expect(b.ex).toBeCloseTo(a.ex, 6); expect(b.ey).toBeCloseTo(a.ey, 6); expect(r.ex).toBeCloseTo(a.ex, 6);
});
test("looking to the user's right lowers ex (raw-frame convention)", () => {
  const right = gazeFeatures(syntheticFace({ gazeX: 0.3, gazeY: 0, yaw: 0, pitch: 0 }), 640, 480) as GazeFeatures;
  const left = gazeFeatures(syntheticFace({ gazeX: -0.3, gazeY: 0, yaw: 0, pitch: 0 }), 640, 480) as GazeFeatures;
  expect(right.ex).toBeLessThan(left.ex);
});
test("invalid inputs are named, never NaN", () => {
  expect(gazeFeatures(null, 640, 480)).toEqual({ invalid: "no_face" });
  expect(gazeFeatures(syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0, cx: -0.02 }), 640, 480)).toEqual({ invalid: "eyes_outside" });
  const pts = syntheticFace({ gazeX: 0, gazeY: 0, yaw: 0, pitch: 0 }); pts[468] = { x: pts[468].x + 0.03, y: pts[468].y };
  expect(gazeFeatures(pts, 640, 480)).toEqual({ invalid: "eyes_unreliable" });
});
```

- [ ] **Step 2:** FAIL → **Step 3:** 구현(스펙 4절. 눈 좌표계는 픽셀 좌표의 눈꼬리 벡터 기준). → **Step 4:** PASS → **Step 5:** status/commit

### Task 3: G2 회귀 `regression.ts`

**Files:**
- Create: `web/src/video/gaze/regression.ts`
- Test: `web/e2e/gaze-math.spec.ts`

**Interfaces:**
- Consumes: `GazeFeatures`(Task 2).
- Produces:
  - `type GroupedSample = { f: GazeFeatures; target: [number, number]; group: string }`
  - `fitRidge(X: number[][], y: number[], lambda: number): number[]` — 표준화는 호출자가 하고, 절편(첫 열)은 벌점이 없다.
  - `selectG2(samples: GroupedSample[], lambdas = [0.01, 0.1, 1, 10]): G2Model`
    - `G2Model = { kind: "M1" | "M2"; lambda: number; cvMedianPx: number; predict(f: GazeFeatures): [number, number] }`.
    - 묶음 3개 미만이면 `CalibrationError("insufficient_groups")`.
  - `groupedFolds(groups: string[]): { train: number[]; test: number[] }[]` — 묶음 하나씩 빼기.

- [ ] **Step 1: 실패 테스트**

```ts
test("ridge recovers linear coefficients and stays finite on duplicate columns", () => {
  const X = [...Array(50)].map((_, i) => [1, i / 10, (i % 7) / 7]); const y = X.map(([, a, b]) => 3 + 2 * a - 5 * b);
  const w = fitRidge(X, y, 1e-6); expect(w[0]).toBeCloseTo(3, 3); expect(w[1]).toBeCloseTo(2, 3); expect(w[2]).toBeCloseTo(-5, 3);
  const dup = fitRidge(X.map((r) => [...r, r[1]]), y, 0.1); expect(dup.every(Number.isFinite)).toBe(true);
});
test("grouped folds never put frames of the held-out group in training", () => {
  const groups = ["a", "a", "b", "b", "c", "c", "a"];
  for (const { train, test } of groupedFolds(groups)) {
    const held = new Set(test.map((i) => groups[i])); expect(held.size).toBe(1);
    expect(train.some((i) => held.has(groups[i]))).toBe(false);
  }
});
test("grouped CV error reflects per-group offsets (no frame-level leakage)", () => {
  // 묶음마다 무작위 고정 오차가 있는 데이터: 프레임 단위로 나누면 오차가 0에 가깝지만 묶음 단위면 커야 한다
  const s = syntheticGrid({ groups: 9, framesPerGroup: 12, groupOffsetPx: 60, frameNoisePx: 2, seed: 1 });
  expect(selectG2(s).cvMedianPx).toBeGreaterThan(30);
});
test("model selection prefers M1 unless M2 is 15% better", () => {
  expect(selectG2(syntheticGrid({ curvature: 0, seed: 2 })).kind).toBe("M1");
  expect(selectG2(syntheticGrid({ curvature: 0.8, seed: 3 })).kind).toBe("M2");
});
test("too few groups is an explicit failure", () => {
  expect(() => selectG2(syntheticGrid({ groups: 2, seed: 4 }))).toThrow("insufficient_groups");
});
```

(`syntheticGrid`는 `synthetic.ts`에 두는 테스트 도우미: 격자 지점마다 `syntheticFace`로 프레임을 만들고 `target`·`group`을 붙인다.)

- [ ] **Step 2:** FAIL → **Step 3:** 구현(정규방정식 + 부분 피벗 가우스 소거, 표준화는 학습 묶음 통계로) → **Step 4:** PASS → **Step 5:** status/commit

### Task 4: G1 렌즈 분류기 `lens.ts`

**Files:**
- Create: `web/src/video/gaze/lens.ts`
- Test: `web/e2e/gaze-math.spec.ts`

**Interfaces:**
- Consumes: `GazeFeatures`, `groupedFolds`(Task 3).
- Produces:
  - `type LensSample = { f: GazeFeatures; openRatio: number; lens: boolean; topBand: boolean; group: string }`
  - `fitLogistic(X: number[][], y: number[], w: number[], l2: number): number[]` — 뉴턴법, 최대 25회.
  - `auc(pos: number[], neg: number[]): number`
  - `lensThresholds(cvPosP: number[], cvTopNegP: number[]): { hi: number; lo: number }` — 스펙 5절: `hi = max(0.8, t₁)`, `lo = min(0.2, t₀)`.
  - `trainLens(samples: LensSample[]): LensModel`
    - `LensModel = { predict(f: GazeFeatures, openRatio: number): { p: number; decision: "toward" | "away" | "unknown"; ood: boolean }; cv: { auc: number; sensitivity: number; topBandFalse: number }; thresholds: { hi: number; lo: number } }`.
    - 양성 또는 위쪽 띠 음성 묶음이 2개 미만이면 `CalibrationError("insufficient_lens_groups")`.

- [ ] **Step 1: 실패 테스트**

```ts
test("logistic stays finite on perfectly separable data", () => {
  const X = [[1, -2], [1, -1], [1, 1], [1, 2]], y = [0, 0, 1, 1];
  expect(fitLogistic(X, y, [1, 1, 1, 1], 1.0).every(Number.isFinite)).toBe(true);
});
test("thresholds keep an unknown band even when classes separate", () => {
  expect(lensThresholds([0.95, 0.97, 0.99], [0.01, 0.03, 0.05])).toEqual({ hi: 0.8, lo: 0.2 });
  const t = lensThresholds([0.6, 0.7, 0.9], [0.5, 0.6, 0.85]); expect(t.hi).toBeGreaterThanOrEqual(0.85);
});
test("separable lens data: high CV AUC, toward on lens, unknown far outside training", () => {
  const m = trainLens(syntheticLens({ lensOffset: 0.25, noise: 0.02, seed: 5 }));
  expect(m.cv.auc).toBeGreaterThan(0.95);
  expect(m.predict(lensFeatures(0.25), 1.1).decision).toBe("toward");
  expect(m.predict(farFeatures(), 1.0)).toMatchObject({ decision: "unknown", ood: true });
});
test("inseparable lens vs top band: AUC near 0.5 and low sensitivity", () => {
  const m = trainLens(syntheticLens({ lensOffset: 0, noise: 0.02, seed: 6 }));
  expect(m.cv.auc).toBeLessThan(0.7); expect(m.cv.sensitivity).toBeLessThan(0.3);
});
test("class weights balance 10 positives vs 100 negatives", () => {
  const m = trainLens(syntheticLens({ lensOffset: 0.25, positives: 10, negatives: 100, seed: 7 }));
  expect(m.cv.sensitivity).toBeGreaterThan(0.6);
});
```

(`syntheticLens`·`lensFeatures`·`farFeatures`는 `synthetic.ts`의 테스트 도우미. `lensOffset`은 렌즈와 화면 위쪽 띠 사이의 세로 시선 차이다.)

- [ ] **Step 2:** FAIL → **Step 3:** 구현.
  - 클래스 가중치는 각 클래스 합이 같게 맞춘다.
  - 분포 밖 검사는 학습 표본 공분산의 마할라노비스 거리가 학습 표본 99번째 백분위를 넘는지로 본다.
- [ ] **Step 4:** PASS → **Step 5:** status/commit

### Task 5: 보정 순서와 실현 가능성 지표 `calibration.ts`

**Files:**
- Create: `web/src/video/gaze/calibration.ts`
- Test: `web/e2e/gaze-math.spec.ts`

**Interfaces:**
- Consumes: Task 2~4.
- Produces:
  - `PROTOCOL: Fixation[]`
    - `Fixation = { id: string; role: "train" | "validate" | "distance" | "panel" | "rate"; target: { x: number; y: number } | "lens"; pose: "forward" | "left" | "right" | "up" | "down" | "near" | "far"; settleMs: number; collectMs: number; topBand?: boolean; panelPx?: number; hz?: 4 | 10 | 15 }`
    - 스펙 7·13절 순서와 값.
  - `collect(frames: Frame[], fx: Fixation, baseline?: Baseline): FixationData` — 정착 시간을 버리고 유효 표본만 남긴다. 묶음 id는 실행 안에서 고유하다(`${fx.id}#${n}`).
  - `evaluateRun(data: FixationData[], viewport: { w: number; h: number }, panelRects: Record<number, DOMRectLike>): FeasibilityReport` — 스펙 13절 표의 각 행: 수치 + `"pass" | "fail" | "inconclusive"`.
    - G1 판정은 학습·임계값 선택에 쓰지 않은 검증 응시(렌즈 3개, 위쪽 띠 3개)로만 계산한다. 교차 검증 AUC는 진단용으로 따로 둔다.
    - G2는 좌표 오차와 영역 판정 성능(패널 높이별 적중·`unknown`·다른 영역, 패널 밖 점의 `question` 오판·`ui` 정답)을 함께 낸다.
  - `aggregate(r: FeasibilityReport): Record<string, number | string>` — 집계 숫자·판정만(배열·좌표 없음).

- [ ] **Step 1: 실패 테스트**

```ts
test("lens and top-band validation fixations are separate from training", () => {
  const val = PROTOCOL.filter((f) => f.role === "validate");
  expect(val.filter((f) => f.target === "lens").map((f) => f.pose).sort()).toEqual(["forward", "left", "right"]);
  expect(val.filter((f) => f.topBand).map((f) => f.target)).toEqual([{ x: 0.4, y: 0.05 }, { x: 0.5, y: 0.05 }, { x: 0.6, y: 0.05 }]);
});
test("validation positions are never used for training", () => {
  const key = (f: Fixation) => (f.target === "lens" ? `lens/${f.pose}` : `${f.target.x},${f.target.y}`);
  const train = new Set(PROTOCOL.filter((f) => f.role === "train").map(key));
  const validate = PROTOCOL.filter((f) => f.role === "validate").filter((f) => f.target !== "lens");
  expect(validate.length).toBeGreaterThanOrEqual(7); expect(validate.some((f) => train.has(key(f)))).toBe(false);
});
test("group ids are unique per run even when a point is re-measured", () => {
  const a = collect(fakeFrames(20), PROTOCOL[3]), b = collect(fakeFrames(20), PROTOCOL[3]);
  expect(a.group).not.toBe(b.group);
});
test("evaluateRun passes clean synthetic data and fails noisy data", () => {
  expect(evaluateRun(syntheticRun({ noise: 0.01, seed: 8 }), VIEW, PANELS).g2.verdict).toBe("pass");
  expect(evaluateRun(syntheticRun({ noise: 0.2, seed: 9 }), VIEW, PANELS).g2.verdict).toBe("fail");
  expect(evaluateRun(syntheticRun({ lensOffset: 0, seed: 10 }), VIEW, PANELS).g1.verdict).toBe("fail");
});
test("no usable samples is a failure, not NaN", () => {
  const r = evaluateRun(syntheticRun({ validRatio: 0, seed: 11 }), VIEW, PANELS);
  expect(r.g2.verdict).toBe("fail"); expect(JSON.stringify(r)).not.toContain("NaN");
});
test("aggregate exposes no samples or coordinates", () => {
  const out = aggregate(evaluateRun(syntheticRun({ seed: 12 }), VIEW, PANELS));
  expect(Object.values(out).every((v) => typeof v === "number" || typeof v === "string")).toBe(true);
  expect(Object.keys(out).some((k) => /sample|point|landmark|frame|coord/i.test(k))).toBe(false);
});
```

- [ ] **Step 2:** FAIL → **Step 3:** 구현.
  - 기준값은 `constants.ts`.
  - 패널 적중률: 예측 중앙값이 패널을 `e50`만큼 줄인 사각형 안이면 적중이다. 패널이 `2·e80`보다 작으면 `unresolvable`로 기록한다.
  - 거리 변화는 `position_changed`로 막힌 비율과 `e50` 비율로 본다.
- [ ] **Step 4:** PASS → **Step 5:** status/commit

### Task 6: 개발 전용 시선 실험실과 가짜 검출기 `gaze` 모드

**Files:**
- Create: `web/src/pages/GazeLab.tsx`, `web/e2e/gaze-lab.spec.ts`
- Modify:
  - `web/src/App.tsx`: 조건부 `lazy` 경로 `/dev/gaze-lab`.
  - `web/src/video/fakeDetector.ts`: `gaze`·`gaze-inseparable`·`gaze-noisy` 모드.
  - `web/playwright.config.ts`: 웹 서버 env에 `VITE_GAZE_LAB: "true"`.

**Interfaces:**
- Consumes:
  - `useFaceAnalysis().subscribeFrames/setTargetHz/rate`(Task 1).
  - `PROTOCOL/collect/evaluateRun/aggregate`(Task 5).
  - `syntheticFace`(Task 2).
- 실험실 화면:
  - 현재 응시 대상 요소에 `data-gaze-target`(화면 점) 또는 `data-gaze-lens`(렌즈 단계)를 붙인다.
  - 가짜 검출기 `gaze` 모드는 그 요소의 위치를 읽어 `syntheticFace`로 "그곳을 보는" 특징점을 만든다(e2e 전용 코드).
  - 끝나면 집계표와 "집계 복사" 버튼(`navigator.clipboard.writeText(JSON.stringify(aggregate))`)을 보인다.
  - 진행 중 뷰포트·배율이 바뀌면 "보정이 무효가 됐어요, 다시 시작" 상태로 바꾼다.

- [ ] **Step 1: 실패 테스트** (`gaze-lab.spec.ts`, 데스크톱)
  1. `gaze` 모드로 끝까지 진행:
     - H1·H2 판정 `통과`, 질문 패널 행에 높이 3종(32·120·240px)과 영역 판정 성능(적중·`unknown`·오판)이 있다.
     - 네트워크 요청 본문에 `ex|ey|landmark|gaze` 값이 없다.
  2. `gaze-inseparable` → H1 `실패`, 화면에 "화면 위쪽과 렌즈를 구별할 수 없음".
  3. `gaze-noisy` → H2 `실패`.
  4. 진행 중 `page.setViewportSize` → "다시 시작" 상태.
  5. 페이지를 떠났다 돌아오면 이전 결과가 없다.
  6. `VITE_GAZE_LAB` 없이 띄운 빌드(`npm run build` 결과)에 "시선 실험실"이 없다(셸 단계에서 `grep -r "시선 실험실" dist` → 0건).
- [ ] **Step 2:** `npx playwright test e2e/gaze-lab.spec.ts --project=desktop` → FAIL
- [ ] **Step 3:** 구현. 실험실은 기존 `CameraPanel`·`useFaceAnalysis`를 그대로 쓴다(스트림 1개).
- [ ] **Step 4:** PASS. `npm run build` 통과 + grep 0건. 전체 e2e 회귀(스크린샷 보호 절차).
- [ ] **Step 5:** status/commit

### Task 7: 실제 웹캠 시험 절차와 멈춤

**Files:**
- Modify: `docs/progress.md`(G 0단계 시험 표: 실행 3번 × 스펙 13절 각 행, 결과 칸 "미실행"), `README.md`(개발 전용 실험실 실행법 한 줄)

- [ ] **Step 1:** 절차를 적는다.
  - 실행: `cd web && VITE_GAZE_LAB=true npm run dev` + 백엔드 → `http://localhost:5173/dev/gaze-lab`.
  - 노트북 내장 웹캠, 평소 거리·조명으로 3번(매번 새로 보정). 가능하면 안경·어두운 조명 1번.
  - 화면 크기·뷰포트·카메라 위치를 기록한다.
  - 초당 4·10·15회 단계 동안 OS 작업 관리자의 브라우저 CPU 사용률을 적는다.
- [ ] **Step 2:** `cd backend && .venv/bin/python -m pytest -q`, `cd web && npm run build` → 통과 확인
- [ ] **Step 3: 멈춤.** 사용자에게 시험을 요청하고, 결과(집계 복사본)를 받아 `docs/progress.md`에 적는다.
  - 받은 결과로 G1 포함 여부, 질문 패널 크기, 기본 주기를 사용자와 정한 뒤 1단계 Task를 고친다.
  - 그 전에는 Task 8 이후를 시작하지 않는다.

---

## 1단계 — 본 구현 (0단계 결과로 고친 뒤 시작)

아래는 인터페이스 수준 초안이다. 0단계 결과에 따라 범위가 줄 수 있다(예: G1 제외, 질문 패널 확대 별도 결정).

### Task 8: 보정 화면 `GazeCalibration.tsx`
- 실험실과 같은 `PROTOCOL`의 학습·검증 부분만(거리·패널·주기 단계 제외) 쓰는 진행 화면 오버레이.
- 결과 화면: G2 등급, G1 켜짐·꺼짐 사유, 다시 보정 / 이대로 사용 / 끄기.
- 시선 분석 동의가 없으면 열지 않는다. 답변 중에는 막는다.
- 테스트(e2e): 보정 완료 → 등급 표시, 품질 낮음 → 사용 안 함, 건너뜀 → 결과 없음, 다시 보정, 보정 지우기, 카메라 끔 → 모델·구독·타이머 정리.

### Task 9: 실시간 판정 `classify.ts`·`regions.ts`
- 스펙 8·9절: 사유별 `unknown`, 평활·히스테리시스, 영역 등록부·우선순위·판정 불가 영역, 뷰포트·배율 무효화, `position_changed`(거리 변화).
- 테스트(계산 + e2e): 사유별 `unknown`, 창 크기 변경 → `calibration_stale`, 가짜 얼굴 크기 변경 → `position_changed`, 고개만 돌리고 렌즈 → `camera` 유지, 화면 오른쪽 → 예측 오른쪽.

### Task 10: 진행 화면 통합
- `CameraPanel`: 시선 분석 동의(별도 문구), 보정 버튼·상태·품질, 실시간 한 줄(숨기기).
- `SessionRunner`: `.runner-q`를 `useGazeRegion("question")`으로 등록, 답변 구간에 G 구간 시작·끝.
- 시선 분석을 켜면 표본 주기를 0단계에서 정한 값으로 올린다.
- 동의 문구 변경(스펙 12절).
- 회귀: 카메라만 쓰는 모드, STT·녹음 흐름, D 지표 e2e.

### Task 11: 회고 `GazeReport.tsx`·`summary.ts`
- 스펙 11절 데이터 구조(`anchor` 포함), 답변별 표·타임라인(글 대체), 보정 품질, 판정한 시간 기준 비율.
- `unknown`은 범주에 넣지 않는다.
- 테스트: 요약 계산, 타임라인 접근성 이름, 서버 요청에 시선 값 없음, 새로고침하면 사라짐.

### Task 12: 문서·최종 검증
- README 카메라·시선 절, `docs/decisions.md` D-21, `docs/progress.md`(1단계 수동 절차: 보정 반복 일관성, 고개·눈 분리, 안경·조명, 창 크기·확대/축소, 카메라 끔).
- 전체 e2e·build·pytest, 프로덕션 번들 검사(실험실·진단·가짜 검출기 제외).
