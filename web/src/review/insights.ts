// 회고 한눈에 보기(R1): 세션 상세에 이미 있는 값만으로 답변별 지표와 보완점을 계산한다.
// LLM을 부르지 않으며 같은 입력이면 같은 결과가 나온다. 기준값은 잠정이다(docs/decisions.md D-22).
import type { CoachingReport, PracticeAnswer, PracticeSession } from "../types";

export const SHORT_RATIO = 0.4; // 모의시험 녹음이 제한 시간의 40% 미만이면 짧음
export const OVER_MARGIN_SEC = 1; // 제한 − 1초 이상이면 제한 시간을 다 씀
export const SPEED_DEVIATION = 0.25; // 세션 평균보다 25% 넘게 빠르거나 느림
export const MIN_SPEED_ANSWERS = 3; // 평균·비교에 필요한 말 빠르기 측정 답변 수
export const MIN_RATE_SEC = 5; // 이보다 짧은 녹음은 말 빠르기를 내지 않는다
export const LOW_RATING = 2; // 자기 평가가 이 값 이하면 보완점
export const VISIBLE_POINTS = 5;
export const MAX_QUOTES = 2; // 한 보완점에 인용을 보일 답변 수

const QUOTE_CHARS = 60;

export type CriterionKey = CoachingReport["criteria"][number]["key"];
export type CriterionState = CoachingReport["criteria"][number]["status"] | "점검 전";
export const CRITERIA: { key: CriterionKey; label: string; action: string }[] = [
  { key: "specificity", label: "구체성", action: "상황·내 행동·결과 중 빠진 것을 숫자나 사례 하나로 채워 다시 답해 보기" },
  { key: "relevance", label: "질문 적합성", action: "질문이 묻는 것에 대한 답을 첫 문장에 두고 다시 답해 보기" },
  { key: "consistency", label: "제출본 연결", action: "제출한 자소서의 같은 경험과 맞춰 보고, 다른 점이 있으면 그 이유를 한 문장으로 설명해 보기" },
];

export interface AnswerMetrics {
  id: string;
  order: number;
  question: string;
  /** 녹음 길이(녹음으로 답했을 때만) */
  durationSec: number | null;
  syllables: number;
  /** 음절/분. 녹음 길이 기준이라 앞뒤 침묵이 들어 있다 */
  spm: number | null;
  /** 모의시험 답변 제한 시간 */
  limitSec: number | null;
  /** 녹음 길이 ÷ 제한 시간(모의시험만) */
  usage: number | null;
  statuses: Record<CriterionKey, CriterionState>;
  rating: number | null;
  hasTranscript: boolean;
  recorded: boolean;
}

export interface ImprovementPoint {
  key: string;
  rank: number;
  title: string;
  answers: { id: string; order: number; quote?: string }[];
  evidence: string;
  action: string;
  source: "coaching" | "rule";
}

export interface Insights {
  answers: AnswerMetrics[];
  /** 말 빠르기 세션 평균(측정 답변이 MIN_SPEED_ANSWERS개 이상일 때만) */
  avgSpm: number | null;
  points: ImprovementPoint[];
  /** 녹음했지만 전사문이 없는 답변 수 */
  untranscribed: number;
}

/** 한글 음절 + 영문자 + 숫자 개수(영문·숫자는 글자당 한 음절로 보는 근사) */
export function syllableCount(text: string): number {
  return text.match(/[가-힣A-Za-z0-9]/g)?.length ?? 0;
}

const currentReport = (a: PracticeAnswer) => a.coaching_report?.input_status === "legacy_unverified" ? null : a.coaching_report;

const transcriptOf = (a: PracticeAnswer) => a.transcript?.trim() ?? "";

export function answerMetrics(a: PracticeAnswer, s: PracticeSession): AnswerMetrics {
  const text = transcriptOf(a);
  const recorded = !!a.recorded_at;
  const durationSec = recorded && a.duration_sec != null && Number.isFinite(a.duration_sec) ? a.duration_sec : null;
  const syllables = syllableCount(text);
  const spm = a.recording_transcript_current === true && durationSec != null && durationSec >= MIN_RATE_SEC && syllables > 0 ? Math.round((syllables / durationSec) * 60) : null;
  const limitSec = s.mode === "mock" && s.answer_sec > 0 ? s.answer_sec : null;
  const statuses = Object.fromEntries(
    CRITERIA.map(({ key }) => [key, currentReport(a)?.criteria.find((c) => c.key === key)?.status ?? "점검 전"]),
  ) as Record<CriterionKey, CriterionState>;
  return {
    id: a.id, order: a.order_no, question: a.question.text, durationSec, syllables, spm, limitSec,
    usage: limitSec != null && durationSec != null ? durationSec / limitSec : null,
    statuses, rating: a.self_rating, hasTranscript: text.length > 0, recorded,
  };
}

/** 답변 앞부분 인용(줄이면 끝에 …) */
const head = (text: string) => (text.length > QUOTE_CHARS ? `${text.slice(0, QUOTE_CHARS)}…` : text);
const secs = (v: number) => `${Math.round(v)}초`;

export function sessionInsights(s: PracticeSession): Insights {
  const sorted = [...s.answers].sort((a, b) => a.order_no - b.order_no);
  const answers = sorted.map((a) => answerMetrics(a, s));
  const measured = answers.filter((m) => m.spm != null);
  const avgSpm = measured.length >= MIN_SPEED_ANSWERS ? measured.reduce((t, m) => t + (m.spm as number), 0) / measured.length : null;
  const points: ImprovementPoint[] = [];
  const ref = (m: AnswerMetrics, quote?: string) => ({ id: m.id, order: m.order, ...(quote ? { quote } : {}) });
  const push = (p: Omit<ImprovementPoint, "source"> & { source?: ImprovementPoint["source"] }) => {
    if (!p.answers.length) return;
    // 인용은 앞의 MAX_QUOTES개 답변만 남긴다(목록이 길어지지 않게). 나머지 답변은 번호 링크로만 보인다
    const answers = p.answers.map((a, i) => (i < MAX_QUOTES ? a : { id: a.id, order: a.order }));
    points.push({ source: "rule", ...p, answers });
  };

  // 1. 코칭 기준이 '보완'인 답변을 기준별로 묶는다
  for (const c of CRITERIA) {
    const hits = sorted.filter((a) => currentReport(a)?.criteria.some((x) => x.key === c.key && x.status === "보완"));
    if (!hits.length) continue;
    const first = currentReport(hits[0]) as CoachingReport;
    const crit = first.criteria.find((x) => x.key === c.key)!;
    // 보고서의 다음 행동은 답변 전체에 대한 것이다: 보완이 이 기준 하나뿐일 때만 이 기준의 행동으로 쓴다
    const only = first.criteria.filter((x) => x.status === "보완").length === 1;
    push({
      key: `coaching-${c.key}`, rank: 1, source: "coaching", title: `${crit.label || c.label} 보완`,
      answers: hits.map((a) => {
        const q = currentReport(a)?.criteria.find((x) => x.key === c.key)?.answer_quote?.trim();
        // 전사문에 그대로 있는 인용만 보인다(AI가 고쳐 쓴 인용은 근거가 되지 못한다)
        return ref(answers.find((m) => m.id === a.id)!, q && transcriptOf(a).includes(q) ? head(q) : undefined);
      }),
      evidence: `Q${hits[0].order_no}: ${crit.reason}${hits.length > 1 ? ` (외 ${hits.length - 1}개 답변)` : ""}`,
      action: only && first.next_action.trim() ? first.next_action : c.action,
    });
  }

  // 2·3. 모의시험 제한 시간
  const timed = answers.filter((m) => m.limitSec != null && m.durationSec != null);
  const over = timed.filter((m) => (m.durationSec as number) >= (m.limitSec as number) - OVER_MARGIN_SEC);
  push({
    key: "time-over", rank: 2, title: "제한 시간을 다 썼어요", answers: over.map((m) => ref(m)),
    evidence: `${over.map((m) => `Q${m.order} ${secs(m.durationSec as number)}`).join(" · ")} / 제한 ${secs(s.answer_sec)}`,
    action: "결론을 먼저 말하고 근거를 두 가지로 줄여 다시 답해 보기",
  });
  const short = timed.filter((m) => (m.usage as number) < SHORT_RATIO);
  push({
    key: "time-short", rank: 3, title: "제한 시간보다 많이 짧았어요", answers: short.map((m) => ref(m)),
    evidence: `${short.map((m) => `Q${m.order} ${secs(m.durationSec as number)}(${Math.round((m.usage as number) * 100)}%)`).join(" · ")} / 제한 ${secs(s.answer_sec)}`,
    action: "상황 → 내 행동 → 결과 순서로 한 번 더 채워 보기",
  });

  // 5. 세션 평균 대비 말 빠르기
  if (avgSpm != null) {
    const dev = (m: AnswerMetrics) => ((m.spm as number) - avgSpm) / avgSpm;
    const avgText = `이 세션 평균 ${Math.round(avgSpm)}음절(녹음 길이 기준, 침묵 포함)`;
    const fast = measured.filter((m) => dev(m) > SPEED_DEVIATION);
    const slow = measured.filter((m) => dev(m) < -SPEED_DEVIATION);
    push({
      key: "speed-fast", rank: 5, title: "평소보다 빠르게 말했어요", answers: fast.map((m) => ref(m)),
      evidence: `${fast.map((m) => `Q${m.order} 분당 ${m.spm}음절`).join(" · ")} · ${avgText}`,
      action: "문장과 문장 사이에 한 박자 쉬어 가며 다시 답해 보기",
    });
    push({
      key: "speed-slow", rank: 5, title: "평소보다 느리게 말했어요", answers: slow.map((m) => ref(m)),
      evidence: `${slow.map((m) => `Q${m.order} 분당 ${m.spm}음절`).join(" · ")} · ${avgText}`,
      action: "핵심 문장을 먼저 말하고 설명을 덧붙여 다시 답해 보기",
    });
  }

  // 6. 자기 평가 1~2점
  const low = answers.filter((m) => m.rating != null && m.rating <= LOW_RATING);
  push({
    key: "rating", rank: 6, title: "스스로 아쉬웠다고 평가했어요", answers: low.map((m) => ref(m)),
    evidence: low.map((m) => `Q${m.order} ${m.rating}점`).join(" · "),
    action: "아쉬웠던 이유를 회고 메모에 한 줄 적고 다시 연습하기",
  });

  return { answers, avgSpm, points, untranscribed: answers.filter((m) => m.recorded && !m.hasTranscript).length };
}

/** 보완점은 VISIBLE_POINTS개까지 보이고 나머지는 접는다 */
export function splitPoints(points: ImprovementPoint[]) {
  return { shown: points.slice(0, VISIBLE_POINTS), more: points.slice(VISIBLE_POINTS) };
}
