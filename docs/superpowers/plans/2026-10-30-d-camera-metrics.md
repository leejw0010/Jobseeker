# D. 카메라 지표 정의 점검 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 회고 화면의 카메라 지표를 서로 겹치지 않는 `none`/`edge` 시간과 답변·분석 시간으로 나누고, 면접 중 `edge` 방향 안내와 개발 전용 진단을 추가한다.

**Architecture:** 계산은 순수 함수 모듈 `web/src/video/metrics.ts`에 모으고(브라우저 없이 테스트), 훅 `useFaceAnalysis`는 답변 시작·끝 시각만 넘긴다. 화면(`VideoReportCard`, `CameraPanel`)은 요약과 표본을 표시만 한다. 카메라 스트림 획득·MediaPipe 검출·녹음 흐름은 그대로 둔다.

**Tech Stack:** React 18 + TypeScript + Vite, `@mediapipe/tasks-vision` 1.1.1, Playwright(계산 테스트와 브라우저 e2e 모두 `web/e2e/`).

**Spec:** [docs/superpowers/specs/2026-10-30-d-camera-metrics-design.md](../specs/2026-10-30-d-camera-metrics-design.md)

## Global Constraints

- 임계값·분류 규칙 변경 금지: `EDGE_MARGIN` 0.01, `YAW_THRESHOLD` 0.12, `PITCH_THRESHOLD` 0.06, `EPISODE_MS` 1000, `MAX_GAP_MS` 1000, `SAMPLE_MS` 250, MediaPipe 옵션 그대로. `faceFeatures`의 `state` 결과는 지금과 같은 입력에 같은 값.
- 상태는 서로 배타적인 `in` / `edge` / `none` 세 가지뿐.
- 옛 이름 `totalMs`, `offMs`, `offEpisodes`, `longestOffMs`와 문구 "화면을 벗어난"을 `web/src`, `web/e2e`, README, `docs/progress.md`에 남기지 않는다(`docs/decisions.md`의 과거 기록과 이 계획·스펙의 설명은 예외).
- `none`을 "자리를 떠남·시선을 돌림"으로 단정하는 문구 금지. 찾지 못한 이유로 "조명·각도·가림"을 함께 적는다.
- 비율의 분모는 `analyzedMs`. 분석하지 못한 시간 = max(0, `answerMs` − `analyzedMs`)은 어느 지표에도 넣지 않는다.
- 좌우 문구는 미리보기(좌우 반전) 기준: 원본 x < 0 쪽 → "오른쪽", x > 1 쪽 → "왼쪽". 위·아래는 그대로.
- 진단 표시는 `import.meta.env.DEV && import.meta.env.VITE_CAMERA_DEBUG === "true"`일 때만. 특징점·영상은 저장·전송하지 않는다.
- 카메라 스트림 획득(`getUserMedia` 호출과 제약), 마이크 녹음(`useRecorder`), 백엔드·API는 바꾸지 않는다.
- **커밋·push·브랜치 변경·stash·reset 금지**(사용자 지시). 각 Task의 "Commit" 단계는 "변경 파일 확인(`git status --short`)"으로 대신한다.
- 코드 주석·화면 문구는 기존처럼 한국어, 주변 코드의 밀도와 말투를 따른다.

## Review Focus

1. 답변 도중 카메라를 끄거나 검출이 멈춤 → 요약은 남고 `answerMs` > `analyzedMs`, 이후 시간은 분석하지 못한 시간으로만 보임 (Task 1 테스트 `samples stop early inside the span`).
2. 표본이 하나도 없는데 구간은 시작됨(카메라 화면 준비 전 답변 종료) → 카드가 NaN 없이 "–"와 분석하지 못한 시간을 보임 (Task 1 테스트 `empty segment with span`).
3. 얼굴이 두 쪽(위+원본 왼쪽)으로 넘음 → 문구가 "위쪽·오른쪽" 둘 다, 미리보기 기준 (Task 2 테스트 `edge label lists every crossed side, mirrored`).
4. 한쪽은 여유(0.005) 안, 다른 쪽이 넘어 `edge` → 문구에는 실제로 넘은 쪽만 (Task 2 같은 테스트).
5. 특징점 배열이 핵심 부위 번호보다 짧음 → `coreInside` false, 예외 없음 (Task 2 테스트 `short landmark list`).

---

### Task 1: 요약 지표 재정의와 회고 카드

**Files:**
- Modify: `web/src/video/metrics.ts` (`SegmentSummary`, `summarizeSegment`, `combineSummaries`)
- Modify: `web/src/components/useFaceAnalysis.ts` (`beginSegment`, `endSegment`)
- Modify: `web/src/components/VideoReportCard.tsx`
- Test: `web/e2e/video-metrics.spec.ts`

**Interfaces:**
- Produces:
  - `type SegmentSummary = { samples; answerMs; analyzedMs; detectedMs; inMs; edgeMs; noneMs; noneEpisodes; longestNoneMs; headMs; turnedMs; downMs }` (모두 `number`)
  - `type Span = { start: number; end: number }` (performance.now() 기준 ms)
  - `summarizeSegment(samples: FaceSample[], span?: Span): SegmentSummary` — span이 있으면 `answerMs = end − start`, 마지막 표본 길이 = clamp(end − t, 0, MAX_GAP_MS). 없으면 마지막 표본 = `SAMPLE_MS`, `answerMs = analyzedMs`.
  - `combineSummaries(list: SegmentSummary[]): SegmentSummary` — `longestNoneMs`는 최댓값, 나머지는 합.
  - `useFaceAnalysis().endSegment(): SegmentSummary | null` — `beginSegment` 때 검출기가 있었으면 표본이 0개여도 요약을 돌려준다(카메라를 켜지 않았으면 null).

- [ ] **Step 1: 실패하는 테스트로 바꾸기** — `video-metrics.spec.ts`의 옛 필드 단언을 새 필드로 바꾸고 아래 테스트를 추가한다.

```ts
test("summarizeSegment separates none and edge time without overlap", () => {
  // 3초 정면, 2초 없음, 0.5초 가장자리, 0.25초 정면
  const s = summarizeSegment(samples([...repeat(12, face()), ...repeat(8, null), ...repeat(2, face(0, 0, 0.45)), face()]));
  expect(s.samples).toBe(23);
  expect(s.analyzedMs).toBe(23 * SAMPLE_MS);
  expect(s.inMs).toBe(13 * SAMPLE_MS);
  expect(s.edgeMs).toBe(2 * SAMPLE_MS);
  expect(s.noneMs).toBe(8 * SAMPLE_MS);
  expect(s.detectedMs).toBe(15 * SAMPLE_MS);
  expect(s.inMs + s.edgeMs + s.noneMs).toBe(s.analyzedMs);
  expect(s.noneEpisodes).toBe(1);
  expect(s.longestNoneMs).toBe(8 * SAMPLE_MS);
  expect(s.answerMs).toBe(s.analyzedMs); // span이 없으면 같다
});

test("edge-only answer is fully detected with zero not-found time", () => {
  const s = summarizeSegment(samples(repeat(20, face(0, 0, 0.45))));
  expect(s.detectedMs).toBe(s.analyzedMs);
  expect(s.noneMs).toBe(0);
  expect(s.edgeMs).toBe(s.analyzedMs);
  expect(s.noneEpisodes).toBe(0);
});

test("flickering none is counted as time but not as episodes", () => {
  const s = summarizeSegment(samples(Array.from({ length: 40 }, (_, i) => (i % 4 === 3 ? null : face()))));
  expect(s.noneMs).toBe(10 * SAMPLE_MS);
  expect(s.noneEpisodes).toBe(0);
});

test("leaving and returning: edge around a long none run", () => {
  const list = [...repeat(8, face()), ...repeat(2, face(0, 0, 0.45)), ...repeat(24, null), ...repeat(2, face(0, 0, 0.45)), ...repeat(8, face())];
  const s = summarizeSegment(samples(list));
  expect(s.noneMs).toBe(24 * SAMPLE_MS);
  expect(s.noneEpisodes).toBe(1);
  expect(s.longestNoneMs).toBe(24 * SAMPLE_MS);
  expect(s.edgeMs).toBe(4 * SAMPLE_MS);
});

test("answer time vs analyzed time: hidden tab gap, last sample clipped, early stop", () => {
  // 탭이 가려져 표본 사이가 5초 벌어짐: 1초만 분석한 것으로 센다
  const gap = summarizeSegment([{ t: 0, state: "in" }, { t: 5000, state: "in" }], { start: 0, end: 5100 });
  expect(gap.answerMs).toBe(5100);
  expect(gap.analyzedMs).toBe(MAX_GAP_MS + 100); // 마지막 표본은 답변 끝에서 잘린다
  // samples stop early inside the span(답변 도중 카메라를 끔)
  const early = summarizeSegment(samples(repeat(8, face())), { start: 0, end: 10_000 });
  expect(early.analyzedMs).toBe(7 * SAMPLE_MS + MAX_GAP_MS);
  expect(early.answerMs).toBe(10_000);
  // empty segment with span
  const empty = summarizeSegment([], { start: 0, end: 3000 });
  expect(empty).toMatchObject({ answerMs: 3000, analyzedMs: 0, noneMs: 0, samples: 0 });
  expect(summarizeSegment([]).analyzedMs).toBe(0);
});
```

`combineSummaries` 테스트는 `analyzedMs`·`answerMs` 합, `noneEpisodes` 2, `longestNoneMs` 12×SAMPLE_MS로 바꾼다. 기존 "long gaps are capped" 테스트의 `gap.totalMs`는 `gap.analyzedMs`(값 `MAX_GAP_MS + SAMPLE_MS`, span 없음)로 바꾼다.

- [ ] **Step 2: 실패 확인** — Run: `cd web && npx playwright test e2e/video-metrics.spec.ts --project=desktop` / Expected: 새 필드가 `undefined`라 FAIL.

- [ ] **Step 3: `metrics.ts` 구현** — 위 Interfaces대로. 연속 구간은 `none`만 센다(`edge`나 `in`이 오면 구간을 닫음). 고개 지표 계산은 그대로.

- [ ] **Step 4: 통과 확인** — 같은 명령 / Expected: PASS.

- [ ] **Step 5: 훅** — `beginSegment`에서 `segStart = performance.now()`를 저장하고(검출기가 없으면 구간 없음, 기존과 같음), `endSegment`는 구간이 있었으면 `summarizeSegment(samples, { start: segStart, end: performance.now() })`(표본 0개여도), 없었으면 null.

- [ ] **Step 6: `VideoReportCard` 문구** — 스펙 4절 표 그대로. 머리말: "답변 n개, 답변 시간 모두 {answer} 중 {analyzed}를 분석했어요(초당 약 4번, 표본 n개)." + 분석하지 못한 시간이 1초 이상이면 "분석하지 못한 시간 {x}(탭이 가려졌거나, 카메라 화면이 준비되지 않았거나, 검출이 멈췄거나, 카메라를 끈 시간)은 아래 수치에 넣지 않았어요." 지표 항목:
  - 얼굴 검출 비율: `{pct(detected, analyzed)}` · 분석한 시간 중 얼굴 특징점을 찾은 시간의 비율(얼굴 일부가 프레임 밖이었던 시간 포함)
  - 얼굴을 찾지 못한 시간: `{sec(none)} ({pct})` · 분석한 시간 중 얼굴 특징점을 찾지 못한 시간. 자리를 비웠을 수도 있지만 조명·각도·가림 때문에 검출하지 못했을 수도 있어요. 1초 이상 이어진 횟수 n번, 가장 길게 이어진 시간 x
  - 얼굴 일부가 프레임 밖: `{sec(edge)} ({pct})` · 얼굴은 찾았지만 이마·턱·볼 가장자리 일부가 카메라 프레임 밖에 있던 시간(검출 비율에 포함)
  - 표 열: 질문 | 답변 시간 | 분석한 시간 | 얼굴 검출 | 찾지 못한 시간 | 일부 프레임 밖 | 좌우 회전 | 숙임

- [ ] **Step 7: 빌드** — Run: `cd web && npm run build` / Expected: 통과(옛 필드 참조가 남으면 타입 오류).

- [ ] **Step 8: 변경 파일 확인(커밋하지 않음)** — `git status --short`.

---

### Task 2: `edge` 방향·핵심 부위 판정, 실시간 문구, 미리보기 `contain`

**Files:**
- Modify: `web/src/video/metrics.ts` (`FaceSample`, `faceFeatures`, 새 `edgeLabel`)
- Modify: `web/src/components/CameraPanel.tsx`, `web/src/components/useFaceAnalysis.ts`(실시간 문구에 쓸 마지막 표본 노출), `web/src/pages/SessionRunner.tsx`(새 prop 전달), `web/src/styles.css`
- Test: `web/e2e/video-metrics.spec.ts`

**Interfaces:**
- Consumes: Task 1의 `FaceSample` 사용처.
- Produces:
  - `type Overshoot = { top: number; bottom: number; left: number; right: number }` — 원본 프레임 기준, 경계([0,1]) 밖으로 나간 정도, 안 나갔으면 0.
  - `FaceSample`에 선택 필드 `overshoot?: Overshoot`, `coreInside?: boolean`. `faceFeatures`는 `edge`일 때만 둘을 채운다(`none`·`in`의 반환값은 지금과 같음).
  - `CORE_LANDMARKS = [33, 133, 362, 263, 1, 61, 291, 13, 14]`(양 눈 바깥·안쪽 끝, 코끝, 입 양끝·위·아래). `coreInside` = 이 점들이 모두 존재하고 [0,1] 안.
  - `edgeLabel(o: Overshoot): string` — `EDGE_MARGIN`보다 크게 넘은 쪽만, 순서 위쪽·아래쪽·왼쪽·오른쪽(미리보기 기준), 예: `"얼굴 위쪽·오른쪽이 화면 밖에 있어요"`. 넘은 쪽이 없으면 기존 문구 `"얼굴 일부가 화면 밖에 있어요"`.
  - `useFaceAnalysis()`가 `edge: Overshoot | null`을 추가로 돌려준다(마지막 표본이 `edge`일 때만, 바뀔 때만 setState). `CameraPanel` prop `edge: Overshoot | null`.

- [ ] **Step 1: 실패하는 테스트**

```ts
/** 실제 메시처럼 이마 위(10)와 턱(152)을 가장 바깥에 두고, 핵심 부위는 얼굴 안쪽에 둔 얼굴 */
function meshFace(topY = 0.3, chinY = 0.75, leftX = 0.38, rightX = 0.62): Point[] { /* CORE 점은 0.42~0.58 안, 234·454는 leftX·rightX */ }

test("forehead beyond the top edge with core features inside is edge with overshoot", () => {
  const f = faceFeatures(meshFace(-0.02));
  expect(f.state).toBe("edge");
  expect(f.coreInside).toBe(true);
  expect(f.overshoot!.top).toBeCloseTo(0.02);
  expect(f.overshoot).toMatchObject({ bottom: 0, left: 0, right: 0 });
  expect(faceFeatures(meshFace()).overshoot).toBeUndefined(); // in은 그대로
});

test("edge label lists every crossed side, mirrored", () => {
  expect(edgeLabel({ top: 0.02, bottom: 0, left: 0, right: 0 })).toBe("얼굴 위쪽이 화면 밖에 있어요");
  expect(edgeLabel({ top: 0.02, bottom: 0, left: 0.05, right: 0 })).toBe("얼굴 위쪽·오른쪽이 화면 밖에 있어요"); // 원본 왼쪽 = 미리보기 오른쪽
  expect(edgeLabel({ top: 0, bottom: 0.03, left: 0, right: 0.04 })).toBe("얼굴 아래쪽·왼쪽이 화면 밖에 있어요");
  expect(edgeLabel({ top: 0.005, bottom: 0, left: 0, right: 0.02 })).toBe("얼굴 왼쪽이 화면 밖에 있어요"); // 여유 안은 빼고
});

test("short landmark list: coreInside is false without throwing", () => {
  const pts = Array.from({ length: 20 }, () => ({ x: 0.5, y: 0.5 }));
  pts[0] = { x: 0.5, y: -0.05 };
  expect(faceFeatures(pts)).toMatchObject({ state: "edge", coreInside: false });
});

test("classification is unchanged for the existing fixtures", () => {
  expect(faceFeatures(face()).state).toBe("in");
  expect(faceFeatures(face(0, 0, 0.45)).state).toBe("edge");
  expect(faceFeatures(null)).toEqual({ state: "none" });
});
```

- [ ] **Step 2: 실패 확인** — `npx playwright test e2e/video-metrics.spec.ts --project=desktop` / Expected: `edgeLabel` 없음, `overshoot` undefined로 FAIL.

- [ ] **Step 3: `metrics.ts` 구현** — 위 Interfaces대로. 분류 조건(`EDGE_MARGIN` 비교)은 그대로 두고, `edge`로 판정한 분기에서만 `overshoot`(경계 0/1 기준)과 `coreInside`를 계산한다.

- [ ] **Step 4: 통과 확인** — 같은 명령 / Expected: PASS.

- [ ] **Step 5: 훅·패널·미리보기** — `tick`에서 `edge` 상태와 `overshoot`를 갱신(값이 바뀐 쪽 이름 목록이 달라질 때만 setState). `CameraPanel`은 `face === "edge" && edge ? edgeLabel(edge) : FACE_LABEL[face]`. `.camera-preview`의 `object-fit: cover` → `contain`(`transform: scaleX(-1)` 유지). 카메라 안내 문구 중 이 변경과 관계없는 것은 그대로.

- [ ] **Step 6: 빌드** — `cd web && npm run build` / Expected: 통과.

- [ ] **Step 7: 변경 파일 확인(커밋하지 않음)**.

---

### Task 3: 개발 전용 진단 표시

**Files:**
- Create: `web/src/video/debug.ts`
- Create: `web/src/components/CameraDiagnostics.tsx`
- Modify: `web/src/components/useFaceAnalysis.ts`, `web/src/components/CameraPanel.tsx`, `web/src/vite-env.d.ts`(없으면 `env` 타입은 기존 방식대로 `as string | undefined`)

**Interfaces:**
- Consumes: Task 2의 `FaceSample.overshoot`, `coreInside`.
- Produces:
  - `export const CAMERA_DEBUG: boolean = import.meta.env.DEV && import.meta.env.VITE_CAMERA_DEBUG === "true"` (`debug.ts`)
  - `type CameraDiag = { sample: FaceSample | null; width: number; height: number; counts: { in: number; edge: number; none: number; edgeCore: number } }`
  - `useFaceAnalysis()`가 `diag: CameraDiag | null`을 돌려준다. `CAMERA_DEBUG`가 false면 항상 null이고 진단용 setState를 하지 않는다. `counts`는 `beginSegment`마다 0으로, 구간 밖에서는 카메라를 켠 뒤부터 센다.
  - `CameraDiagnostics({ diag }: { diag: CameraDiag })` — 제목 "카메라 진단(개발용)", 상태, 넘은 쪽(원본 기준 수치와 `edgeLabel` 문구), `coreInside`, 해상도 `{width}×{height}`, 상태별 표본 수와 "edge이면서 핵심 부위 안" 수. 저장·전송 없음.

- [ ] **Step 1: 구현** — `CameraPanel`이 `diag`가 있을 때만 `<CameraDiagnostics>`를 그린다. `CameraDiagnostics`는 `CAMERA_DEBUG`가 참일 때만 동적 `import()`한다(프로덕션 번들에서 빠지도록).

- [ ] **Step 2: 프로덕션 제외 확인** — Run: `cd web && npm run build && grep -rl "카메라 진단" dist/ ; echo "exit=$?"` / Expected: 일치하는 파일 없음(`exit=1`).

- [ ] **Step 3: 개발 서버에서 표시 확인** — `VITE_CAMERA_DEBUG=true VITE_E2E_FAKE_FACE=true`로 개발 서버를 띄워 Playwright로 카메라를 켜고 "카메라 진단(개발용)"과 해상도가 보이는지, 플래그 없이 띄우면 안 보이는지 확인(일회성 확인, 결과를 보고에 적음).

- [ ] **Step 4: 변경 파일 확인(커밋하지 않음)**.

---

### Task 4: 브라우저 e2e(가짜 검출기 `edge-top`)

**Files:**
- Modify: `web/src/video/fakeDetector.ts`
- Modify: `web/e2e/camera.spec.ts`

**Interfaces:**
- Consumes: Task 1 카드 문구·표 열 순서, Task 2 `edgeLabel` 문구와 `.camera-preview` 스타일.
- Produces: `localStorage "e2e-face-detector"` 값 `"edge-top"` → 매 프레임 이마 위(10)만 y = −0.03이고 핵심 부위는 안인 얼굴.

- [ ] **Step 1: 기존 테스트를 새 문구로 고치고 새 테스트 추가**
  - 기존 테스트: `"화면을 벗어난 시간"` → `"얼굴을 찾지 못한 시간"`, 표 셀 `nth(2)`(검출) → `nth(3)`, `nth(4)`(좌우) → `nth(6)`, 카드에 `"분석한 시간"` 포함, 카드에 `"화면을 벗어난"` 없음.
  - 새 테스트 `"edge-top: face partly outside is shown as detected, not as not-found"`: `edge-top` 설정 → 카메라 켜기 → 패널 status `"얼굴 위쪽이 화면 밖에 있어요"` → 미리보기 `getComputedStyle(el).objectFit === "contain"`이고 `transform`이 `matrix(-1`로 시작 → 1500ms 답변 후 회고 → 첫 행 `td.nth(3)` `"100%"`, `td.nth(4)` `"0초"`, `td.nth(5)`가 `"0초"`가 아님, 카드에 `"화면을 벗어난"` 없음.

- [ ] **Step 2: 실패 확인** — `PATH=../backend/.venv/bin:$PATH npx playwright test e2e/camera.spec.ts`(AGENTS.md 스크린샷 보호 절차 함께) / Expected: `edge-top` 미구현으로 새 테스트 FAIL. (이 머신에서는 `LD_LIBRARY_PATH`로 브라우저 라이브러리 지정 필요, `docs/progress.md` 참고)

- [ ] **Step 3: `fakeDetector.ts`에 `edge-top` 추가** — 기본 순서·`fail`은 그대로.

- [ ] **Step 4: 통과 확인** — 같은 명령 / Expected: camera.spec 전부 PASS.

- [ ] **Step 5: 변경 파일 확인(커밋하지 않음)**.

---

### Task 5: 문서와 전체 회귀

**Files:**
- Modify: `README.md`("카메라 자세 분석" 지표 목록과 한계), `docs/progress.md`(구현 표·자동 테스트 표·실행 결과, 수동 검증 항목 3·4를 스펙 6절 V4 표 8개 항목으로 대체), `docs/decisions.md`(D-19: 지표 분리, `contain`, 분석·답변 시간 구분, 임계값 미변경 근거와 V4 뒤 재검토), `docs/architecture.md`(웹 절의 지표 설명이 옛 정의면 고침)

- [ ] **Step 1: 문서 갱신** — Global Constraints의 문구 규칙을 따른다. V4 절차에 실행 방법 `cd web && VITE_CAMERA_DEBUG=true npm run dev`를 적는다.

- [ ] **Step 2: 옛 이름이 남지 않았는지** — Run: `grep -rn "totalMs\|offMs\|offEpisodes\|longestOffMs\|화면을 벗어난" web/src web/e2e README.md docs/progress.md docs/architecture.md` / Expected: 출력 없음.

- [ ] **Step 3: 회귀** — `cd backend && .venv/bin/python -m pytest -q`(Expected: 161 passed), `cd web && npm run build`(통과), `npm run test:e2e`(AGENTS.md 스크린샷 보호 절차, Expected: 실패 0, 기존 21 + 새 테스트), 실행 전후 `git status --short -- docs/screenshots/` 같음.

- [ ] **Step 4: 변경 파일 목록 확인(커밋하지 않음)** — `git status --short`, `feature/local-stt`의 기존 미커밋 변경이 그대로인지 함께 확인.
