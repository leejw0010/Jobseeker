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
  coaching_report: CoachingReport | null;
  parent_answer_id: string | null;
  followup_reason: string | null;
  /** 녹음한 시각("녹음으로 답했다"의 기준). 원본은 전사가 끝나면 지워질 수 있다 */
  recorded_at: string | null;
  audio_available: boolean;
  audio_expires_at: string | null;
  audio_deleted_at: string | null;
}

/** GET /practice/rubric: 코칭 기준(무엇을 보는지와 충분/보완 앵커) */
export interface CoachingCriterionDef {
  key: "specificity" | "relevance" | "consistency";
  label: string;
  checks: string;
  anchors: { 충분: string; 보완: string };
  /** 과거 경험 질문에서 보는 행동 앵커(STAR) */
  star?: { when: string; anchors: string[] };
}

export interface CoachingRubric {
  version: string;
  statuses: Record<"충분" | "보완" | "판단유보", string>;
  criteria: CoachingCriterionDef[];
  note: string;
}

export interface PracticeSettings {
  consented_at: string | null;
  keep_audio: boolean;
  retention_days: number;
}

/** 원본 녹음 삭제 결과. failed는 저장소 오류로 못 지운 개수(서버가 곧 다시 지운다) */
export interface DeleteResult {
  deleted: number;
  failed: number;
}

/** PUT /practice/settings 응답. 동의를 철회했으면 삭제 결과가 함께 온다. */
export type PracticeSettingsUpdate = PracticeSettings & DeleteResult;

/** 다시 연습할 답변(서버가 코칭의 보완 항목·자기평가 1~2점으로 계산) */
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

export interface CoachingReport {
  method: "basic" | "ai";
  rubric_version: string;
  summary: string;
  next_action: string;
  criteria: {
    key: "specificity" | "relevance" | "consistency";
    label: string;
    status: "충분" | "보완" | "판단유보";
    reason: string;
    answer_quote: string;
    source_quote: string;
    source_version_id: string | null;
  }[];
  followup: { text: string; focus: string; reason: string; answer_quote: string; source_quote: string; source_version_id: string | null };
}

export interface InterviewContext {
  company?: string;
  position?: string;
  essay_basis?: "submitted" | "latest";
  job_description?: string;
  essays?: { item_id: string; question_text: string; version_id: string; version_no: number; content: string; selection: "submitted" | "latest"; is_submitted: boolean }[];
  origin_session_id?: string;
  drill_targets?: { answer_id: string; question_id: string; focus: string[]; next_action: string }[];
}

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
  context_snapshot: InterviewContext | null;
  followups_enabled: boolean;
  debrief: Debrief | null;
  debrief_status: DebriefStatus;
  /** 디브리프 작업(답변 점검 + 요약)이 아직 도는 중(5분 안). 이때는 다시 요청해도 서버가 새로 시작하지 않는다 */
  debrief_running: boolean;
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
