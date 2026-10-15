export const STAGES = ["서류", "인적성", "1차면접", "2차면접", "최종"] as const;
export const STATUSES = ["진행중", "합격", "불합격", "보류"] as const;
export const CATEGORIES = ["인성", "직무", "기업", "상황", "인적성"] as const;
export const JOB_CATEGORIES = ["개발", "기획", "마케팅", "데이터", "디자인", "기타"];

export type Stage = (typeof STAGES)[number];
export type Status = (typeof STATUSES)[number];
export type Category = (typeof CATEGORIES)[number];

export interface Question {
  id: string;
  category: Category;
  job_category: string | null;
  text: string;
  source: "bank" | "generated" | "custom";
  application_id: string | null;
}

/** 루브릭 판정 단계. 점수 대신 3단계 + 해당 없음. */
export type Band = "충분" | "일부" | "부족" | "해당 없음";

/** 답변 하나에 대한 기준별 판정. quote는 전사문에서 그대로 찾은 문장만 남는다. */
export interface RubricCriterion {
  key: string;
  label: string;
  band: Band;
  quote: string | null;
  quote_verified: boolean | null;
  comment: string | null;
}

export interface RubricFeedback {
  rubric: string;
  model: string;
  criteria: RubricCriterion[];
  rewrite: string[];
  summary: string | null;
  graded_at: string;
  stale: boolean;
}

/** GET /practice/rubric: 채점 기준(행동 앵커) 정의 */
export interface RubricCriterionDef {
  key: string;
  label: string;
  question: string;
  anchors: Partial<Record<Band, string>>;
}

export interface Rubric {
  version: string;
  bands: Band[];
  criteria: RubricCriterionDef[];
  note: string;
}

export interface PracticeSettings {
  consented_at: string | null;
  keep_audio: boolean;
  retention_days: number;
}

export interface PracticeAnswer {
  id: string;
  order_no: number;
  question: Question;
  audio_path: string | null;
  duration_sec: number | null;
  transcript: string | null;
  stt_status: "none" | "done" | "failed" | "unavailable";
  self_rating: number | null;
  reflection_note: string | null;
  ai_feedback: string | null;
  recorded_at: string | null;
  audio_available: boolean;
  audio_expires_at: string | null;
  audio_deleted_at: string | null;
  feedback: RubricFeedback | null;
}

/** 다시 연습할 약점 질문(서버가 자기평가·루브릭으로 계산) */
export interface WeakAnswer {
  answer_id: string;
  question_id: string;
  order_no: number;
  question_text: string;
  reasons: string[];
}

export interface DebriefMoment {
  answer_id: string;
  order_no: number;
  quote: string;
  why: string | null;
}

/** 서버는 교훈·다음 행동 중 하나만 있어도 저장한다(빈 값은 null). */
export interface Debrief {
  lesson: string | null;
  next_action: string | null;
  moments: DebriefMoment[];
  generated_at: string;
  model: string;
}

export type DebriefStatus = "none" | "pending" | "done" | "failed" | "unavailable";

export interface PracticeSession {
  id: string;
  mode: "free" | "mock";
  title: string;
  application_id: string | null;
  prep_sec: number;
  answer_sec: number;
  created_at: string;
  finished_at: string | null;
  answers: PracticeAnswer[];
  debrief: Debrief | null;
  debrief_status: DebriefStatus;
  redrill_of: string | null;
  redrill: WeakAnswer[];
}

export interface SessionSummary {
  id: string;
  mode: "free" | "mock";
  title: string;
  created_at: string;
  finished_at: string | null;
  answer_count: number;
  recorded_count: number;
  avg_rating: number | null;
  redrill_of: string | null;
}

export interface Application {
  id: string;
  company: string;
  position: string;
  job_category: string;
  url: string | null;
  applied_at: string | null;
  stage: Stage;
  status: Status;
  notes: string | null;
  source: "web" | "extension";
  created_at: string;
  updated_at: string;
}

export interface StageEvent {
  id: string;
  stage: Stage;
  result: "대기" | "합격" | "불합격";
  event_date: string;
  memo: string | null;
}

export interface AnswerVersion {
  id: string;
  version_no: number;
  content: string;
  char_count: number;
  source: "web" | "extension";
  is_submitted: boolean;
  created_at: string;
}

export interface EssayItem {
  id: string;
  question_text: string;
  char_limit: number | null;
  versions: AnswerVersion[];
}

export interface ApplicationDetail extends Application {
  events: StageEvent[];
  essay_items: EssayItem[];
}

export interface FunnelRow {
  stage: Stage;
  reached: number;
  passed: number;
  failed: number;
  pending: number;
  pass_rate: number | null;
}

export interface Stats {
  total: number;
  status: Record<Status, number>;
  funnel: FunnelRow[];
  by_job_category: { job_category: string; total: number; final_pass: number; funnel: FunnelRow[] }[];
  monthly: { month: string; count: number }[];
}
