# R1 회고 한눈에 보기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 세션 회고 화면 맨 위에 코칭 상태 격자, 답변 시간·말 빠르기·자기 평가 막대, 근거가 붙은 보완점 목록을 보인다.

**Architecture:** 순수 계산 모듈 `web/src/review/insights.ts`가 세션 상세(`PracticeSession`)에서 지표와 보완점을 만들고, `ReviewInsights.tsx`가 SVG로 그린다. 백엔드·API·DB는 그대로.

**Tech Stack:** React 18 + TypeScript, Playwright(계산·e2e). 새 의존성 없음.

**Spec:** [docs/superpowers/specs/2026-11-03-r1-review-insights-design.md](../specs/2026-11-03-r1-review-insights-design.md)

## Global Constraints

- `web/`만 바꾼다. 백엔드·API·DB·STT·카메라·G 실험실 코드는 그대로.
- LLM을 새로 부르지 않는다. 같은 입력이면 같은 결과.
- 색: 막대 `#2a78d6`(밝게)·`#3987e5`(어둡게), 충분 `#0ca30c`, 보완 `#fab219`, 중립 회색. 상태는 기호와 글자를 함께 쓴다.
- 기준값: 짧음 40%, 시간 초과 여유 1초, 말 빠르기 편차 25%, 비교 최소 3개, 최소 녹음 5초, 역할 규칙 50자, 낮은 자기 평가 ≤ 2, 보이는 보완점 5개.
- 커밋은 로컬만(push·PR 금지), 파일을 지정해 추가한다.

## Review Focus

1. 답변이 0개, 전사문이 모두 없음, 녹음이 하나도 없음 → 카드가 깨지지 않고 이유 문장을 보인다.
2. 녹음 길이가 0이거나 아주 짧음 → 말 빠르기는 없음(무한대·NaN 아님).
3. 코칭 보고서가 현재 전사문의 것이 아님(`coaching_report: null`) → "점검 전"으로 표시한다.
4. 꼬리질문 답변 → 순서 번호로 정상 표시한다.
5. 아주 긴 질문·인용 → 줄임 표시로 화면이 넘치지 않는다.

---

### Task 1: 계산 모듈 `insights.ts`

**Files:** Create `web/src/review/insights.ts`, Test `web/e2e/review-insights.spec.ts`

**Interfaces (Produces):**
- `syllableCount(text: string): number`
- `answerMetrics(a: PracticeAnswer, s: PracticeSession): AnswerMetrics`
  - `AnswerMetrics = { id; order: number; question: string; durationSec: number | null; syllables: number; spm: number | null; limitSec: number | null; usage: number | null; statuses: Record<CriterionKey, Status | "점검 전">; rating: number | null; hasTranscript: boolean }`
- `sessionInsights(s: PracticeSession): Insights`
  - `Insights = { answers: AnswerMetrics[]; avgSpm: number | null; points: ImprovementPoint[]; untranscribed: number }`
  - `ImprovementPoint = { key: string; rank: number; title: string; answers: { id: string; order: number; quote?: string }[]; evidence: string; action: string; source: "coaching" | "rule" }`

- [ ] **Step 1:** 실패 테스트(스펙 2·3절 규칙마다 1개 이상, Review Focus 1·2·3). 예:

```ts
test("speech rate needs a recording, a transcript and at least 5 seconds", () => {
  expect(answerMetrics(ans({ transcript: "가나다라", duration_sec: 4 }), S).spm).toBeNull();
  expect(answerMetrics(ans({ transcript: "가".repeat(100), duration_sec: 20 }), S).spm).toBe(300);
});
test("coaching 보완 points come first, grouped by criterion, then time, role, speed, rating", () => { ... });
```

- [ ] **Step 2:** 실행 → FAIL(모듈 없음) → **Step 3:** 구현 → **Step 4:** PASS → **Step 5:** 커밋

### Task 2: 그래프와 카드 `ReviewInsights.tsx`

**Files:** Create `web/src/components/ReviewInsights.tsx`, Modify `web/src/pages/SessionReview.tsx`(디브리프 카드 앞에 삽입), `web/src/styles.css`(viz 토큰·격자), Test `web/e2e/review-insights.spec.ts`(브라우저)

- [ ] **Step 1:** 실패 e2e:
  - 글 답변 2개 세션을 API로 만든다.
  - 회고에서 "한눈에 보기", 코칭 상태 격자의 기호·글자, 보완점 항목과 `#answer-…` 링크, 말 빠르기 없음 문장, 표 보기 표를 확인한다.
  - 답변이 없는 세션에서도 깨지지 않는지 본다.
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** PASS → **Step 5:** 커밋

### Task 3: 문서와 전체 검증

- [ ] README 회고 절 한 줄, `docs/progress.md`(구현·테스트 행), `docs/decisions.md` D-22.
- [ ] 전체 e2e(스크린샷 보호), `npm run build`, 백엔드 pytest → 결과 기록, 커밋.
