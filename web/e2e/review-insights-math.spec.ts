import { expect, test } from "@playwright/test";
import { answerMetrics, sessionInsights, splitPoints, syllableCount, type ImprovementPoint } from "../src/review/insights";
import type { CoachingReport, PracticeAnswer, PracticeSession } from "../src/types";

// 회고 한눈에 보기(R1)의 계산 테스트. 브라우저 없이 계산만 확인하므로 desktop 프로젝트에서만 돈다
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop"));

let n = 0;
function ans(over: Partial<PracticeAnswer> = {}): PracticeAnswer {
  n += 1;
  return {
    id: `a${n}`, order_no: n,
    question: { id: `q${n}`, category: "인성", job_category: null, text: `질문 ${n}`, source: "bank", application_id: null },
    audio_path: null, duration_sec: null, transcript: null, stt_status: "none", self_rating: null, reflection_note: null,
    ai_feedback: null, coaching_report: null, parent_answer_id: null, followup_reason: null, recorded_at: null,
    audio_available: false, audio_expires_at: null, audio_deleted_at: null, ...over,
  };
}
/** 녹음으로 답한 답변 */
const rec = (sec: number, transcript: string | null, over: Partial<PracticeAnswer> = {}) =>
  ans({ duration_sec: sec, transcript, recorded_at: "2026-11-03T00:00:00Z", stt_status: transcript ? "done" : "failed", ...over });
function sess(answers: PracticeAnswer[], over: Partial<PracticeSession> = {}): PracticeSession {
  return {
    id: "s1", mode: "free", title: "연습", application_id: null, prep_sec: 30, answer_sec: 60, created_at: "2026-11-03T00:00:00Z",
    finished_at: "2026-11-03T00:10:00Z", answers, context_snapshot: null, followups_enabled: false, debrief: null,
    debrief_status: "none", debrief_running: false, redrill: [], ...over,
  };
}
type Crit = CoachingReport["criteria"][number];
function report(statuses: Partial<Record<Crit["key"], Crit["status"]>>, over: { quote?: string; next_action?: string; reason?: string } = {}): CoachingReport {
  const label = { specificity: "구체성", relevance: "질문 적합성", consistency: "제출본 연결" } as const;
  return {
    method: "ai", rubric_version: "v1", summary: "요약", next_action: over.next_action ?? "보고서의 다음 행동",
    criteria: (["specificity", "relevance", "consistency"] as const).map((key) => ({
      key, label: label[key], status: statuses[key] ?? "충분", reason: over.reason ?? `${label[key]} 이유`,
      answer_quote: over.quote ?? "", source_quote: "", source_version_id: null,
    })),
    followup: { text: "", focus: "specificity", reason: "", answer_quote: "", source_quote: "", source_version_id: null },
  };
}
const keys = (ps: ImprovementPoint[]) => ps.map((p) => p.key);
const orders = (p: ImprovementPoint | undefined) => p?.answers.map((a) => a.order);
/** 역할 표현이 없는 50자 넘는 답변 */
/** 음절 수가 k이고 역할 표현("제가")이 있는 전사문 */
const said = (k: number) => "제가" + "가".repeat(k - 2);
const TEAM = "우리 팀은 서비스 응답 속도를 개선하기 위해 캐시 구조를 바꾸고 배포 과정을 다시 설계해서 결과적으로 사용자 불만을 크게 줄였습니다";

test("syllables count Hangul syllables, Latin letters and digits only", () => {
  expect(syllableCount("안녕하세요, 저는 API 3개를!")).toBe(13);
  expect(syllableCount("  ... ㅋㅋ \n")).toBe(0);
});

test("speech rate needs a recording, a transcript and at least 5 seconds, and is never infinite", () => {
  const S = sess([]);
  expect(answerMetrics(ans({ transcript: said(100) }), S).spm).toBeNull(); // 글로 답함
  expect(answerMetrics(rec(4, "가나다라"), S).spm).toBeNull();
  expect(answerMetrics(rec(0, "가나다라"), S).spm).toBeNull();
  expect(answerMetrics(rec(30, null), S).spm).toBeNull();
  expect(answerMetrics(rec(30, "   "), S).spm).toBeNull();
  expect(answerMetrics(rec(20, said(100)), S).spm).toBe(300);
});

test("session average and fast/slow points need at least 3 measured answers", () => {
  const two = sessionInsights(sess([rec(20, said(100)), rec(20, said(200))]));
  expect(two.avgSpm).toBeNull();
  expect(keys(two.points).filter((k) => k.startsWith("speed"))).toEqual([]);

  const fast = sessionInsights(sess([rec(20, said(100)), rec(20, said(100)), rec(20, said(100)), rec(20, said(150))]));
  expect(fast.avgSpm).toBeCloseTo(337.5, 5);
  expect(keys(fast.points)).toEqual(["speed-fast"]);
  expect(orders(fast.points[0])).toEqual([fast.answers[3].order]);
  expect(fast.points[0].evidence).toContain("450");

  const slow = sessionInsights(sess([rec(20, said(100)), rec(20, said(100)), rec(20, said(100)), rec(20, said(50))]));
  expect(keys(slow.points)).toEqual(["speed-slow"]);
});

test("time rules apply to mock sessions only: over at limit minus 1 second, short below 40%", () => {
  const list = () => [rec(60, said(100)), rec(59.2, said(100)), rec(20, said(100)), rec(24, said(100)), rec(30, said(100))];
  const mock = sessionInsights(sess(list(), { mode: "mock", answer_sec: 60 }));
  const over = mock.points.find((p) => p.key === "time-over");
  const short = mock.points.find((p) => p.key === "time-short");
  expect(orders(over)).toEqual([mock.answers[0].order, mock.answers[1].order]);
  expect(orders(short)).toEqual([mock.answers[2].order]); // 24초는 정확히 40%라 짧지 않음
  expect(over?.evidence).toContain("60초");
  expect(mock.answers[0].limitSec).toBe(60);
  expect(mock.answers[2].usage).toBeCloseTo(20 / 60, 5);

  const free = sessionInsights(sess(list(), { mode: "free", answer_sec: 60 }));
  expect(keys(free.points).filter((k) => k.startsWith("time"))).toEqual([]);
  expect(free.answers[0].limitSec).toBeNull();
  expect(free.answers[0].usage).toBeNull();

  const zero = sessionInsights(sess([rec(30, said(100))], { mode: "mock", answer_sec: 0 }));
  expect(zero.answers[0].usage).toBeNull();
  expect(keys(zero.points).filter((k) => k.startsWith("time"))).toEqual([]);
});

test("role rule: 50+ characters without a role expression, quoting the start of the answer", () => {
  const ins = sessionInsights(sess([
    ans({ transcript: TEAM }),
    ans({ transcript: TEAM + " 제가 캐시를 맡았습니다" }),
    ans({ transcript: TEAM.replace("우리 팀은", "팀에서 배포를 맡아") }),
    ans({ transcript: "우리 팀은 잘했습니다" }),
  ]));
  const role = ins.points.find((p) => p.key === "role");
  expect(orders(role)).toEqual([ins.answers[0].order]);
  const quote = role?.answers[0].quote ?? "";
  expect(quote.length).toBeGreaterThan(0);
  expect(TEAM.includes(quote.replace(/…$/, ""))).toBe(true);
});

test("coaching: no report shows 점검 전; 보완 items are grouped by criterion, quoting only text that is in the transcript", () => {
  const t1 = "저는 로그를 분석해서 원인을 찾았습니다. 그 뒤로 배포 전에 점검표를 만들었습니다.";
  const t3 = "제가 데이터를 정리했고 발표를 맡았습니다.";
  const a1 = ans({ transcript: t1, coaching_report: report({ specificity: "보완" }, { quote: "로그를 분석해서", next_action: "Q1에 맞는 다음 행동", reason: "결과 수치가 없어요" }) });
  const a2 = ans({ transcript: "제가 고객 문의를 맡았습니다.", coaching_report: report({ relevance: "보완", consistency: "보완" }) });
  const a3 = ans({ transcript: t3, coaching_report: report({ specificity: "보완" }, { quote: "전사문에 없는 인용" }) });
  const a4 = ans({ transcript: "제가 했습니다.", coaching_report: null });
  const ins = sessionInsights(sess([a1, a2, a3, a4]));

  expect(ins.answers[3].statuses).toEqual({ specificity: "점검 전", relevance: "점검 전", consistency: "점검 전" });
  expect(ins.answers[1].statuses).toEqual({ specificity: "충분", relevance: "보완", consistency: "보완" });
  expect(keys(ins.points)).toEqual(["coaching-specificity", "coaching-relevance", "coaching-consistency"]);
  const spec = ins.points[0];
  expect(spec.title).toContain("구체성");
  expect(spec.source).toBe("coaching");
  expect(orders(spec)).toEqual([a1.order_no, a3.order_no]);
  expect(spec.answers[0].quote).toBe("로그를 분석해서");
  expect(spec.answers[1].quote).toBeUndefined(); // 전사문에 없는 인용은 보이지 않는다
  expect(spec.evidence).toContain("결과 수치가 없어요");
  expect(spec.action).toBe("Q1에 맞는 다음 행동"); // 보완이 이 기준 하나뿐이면 보고서의 다음 행동
  expect(ins.points[1].action).not.toBe("보고서의 다음 행동"); // 보완이 둘이면 기준별 기본 문구
  expect(ins.points[1].action.length).toBeGreaterThan(0);
});

test("points are ordered coaching, time over, time short, role, speed, self-rating", () => {
  const base = said(100);
  const ins = sessionInsights(sess([
    rec(20, base, { self_rating: 2 }),
    rec(20, base, { self_rating: 1 }),
    rec(60, base),
    rec(20, TEAM.repeat(3), { coaching_report: report({ relevance: "보완" }) }), // 역할 표현 없음, 빠름(분당 495음절, 평균 299)
    rec(20, base, { self_rating: 3 }),
  ], { mode: "mock", answer_sec: 60 }));
  expect(keys(ins.points)).toEqual(["coaching-relevance", "time-over", "time-short", "role", "speed-fast", "speed-slow", "rating"]);
  const ranks = ins.points.map((p) => p.rank);
  expect([...ranks].sort((a, b) => a - b)).toEqual(ranks);
  expect(orders(ins.points.find((p) => p.key === "rating"))).toEqual([ins.answers[0].order, ins.answers[1].order]);
});

test("only five points are shown at once; the rest are folded", () => {
  const p = (i: number): ImprovementPoint => ({ key: `k${i}`, rank: i, title: "", answers: [], evidence: "", action: "", source: "rule" });
  const { shown, more } = splitPoints([1, 2, 3, 4, 5, 6, 7].map(p));
  expect(keys(shown)).toEqual(["k1", "k2", "k3", "k4", "k5"]);
  expect(keys(more)).toEqual(["k6", "k7"]);
  expect(splitPoints([p(1)]).more).toEqual([]);
});

test("empty and unanswered sessions produce no points and no NaN", () => {
  const empty = sessionInsights(sess([]));
  expect(empty).toEqual({ answers: [], avgSpm: null, points: [], untranscribed: 0 });

  const ins = sessionInsights(sess([ans(), rec(30, null), rec(0, null), ans({ transcript: "" })], { mode: "mock", answer_sec: 60 }));
  expect(ins.untranscribed).toBe(2); // 녹음했는데 전사문이 없는 답변만 센다(아직 안 한 답변은 빼고)
  for (const m of ins.answers)
    for (const v of [m.durationSec, m.spm, m.usage, m.limitSec, m.rating, m.syllables])
      if (v !== null) expect(Number.isFinite(v)).toBe(true);
  expect(keys(ins.points).filter((k) => k !== "time-short")).toEqual([]); // 녹음 0초는 짧음일 뿐 다른 규칙은 안 걸린다
});

test("answers are listed by order number, follow-ups included", () => {
  const a = ans({ order_no: 3, transcript: "셋" });
  const b = ans({ order_no: 1, transcript: "하나" });
  const c = ans({ order_no: 2, transcript: "둘", parent_answer_id: b.id });
  expect(sessionInsights(sess([a, b, c])).answers.map((m) => m.order)).toEqual([1, 2, 3]);
});
