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
}

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
