export const STAGES = ["서류", "인적성", "1차면접", "2차면접", "최종"] as const;
export const STATUSES = ["진행중", "합격", "불합격", "보류"] as const;
export const CATEGORIES = ["인성", "직무", "기업", "상황", "인적성"] as const;
export const JOB_CATEGORIES = ["개발", "기획", "마케팅", "데이터", "디자인", "기타"];

export type Stage = (typeof STAGES)[number];
export type Status = (typeof STATUSES)[number];
export type Category = (typeof CATEGORIES)[number];

export interface TaxonomyEntry { key: string; label: string; definition: string }
export interface PracticeTaxonomy { enabled: boolean; taxonomy_version: string; question_types: TaxonomyEntry[]; competencies: TaxonomyEntry[]; max_competencies: number }
export interface QuestionClassification {
 schema_version: number; taxonomy_version: string; question_type: string | null; question_type_label: string | null; question_type_definition: string | null;
 competencies: TaxonomyEntry[]; tagging_source: string | null; question_role: "primary" | "followup"; captured_at: string;
}
export interface CompetencyEvidence {
 status: "analyzed" | "unavailable"; method: "ai"; taxonomy_version?: string; assessment_version?: string; generated_at?: string; model?: string;
 transcript_sha256?: string; question_classification_sha256?: string;
 observations: { competency_key: string; basis: "past_action" | "proposed_action" | "explanation"; quote: string; reason: string }[];
}
export interface ClassificationInput { question_type?: string | null; competency_keys?: string[] }
export interface Question {
  id: string;
  category: Category;
  job_category: string | null;
  text: string;
  source: "bank" | "generated" | "custom";
  question_type?: string | null;
  competency_keys?: string[];
  taxonomy_version?: string | null;
  tagging_source?: string | null;
  application_id: string | null;
}

export interface PracticeAnswer {
  /** Original automatic/first manual transcription still matches this recording; false for legacy or edited text. */
  recording_transcript_current?: boolean;
  question_classification?: QuestionClassification | null;
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

/** 음성 전사 제공자 상태(/health). LLM(AI 코칭·질문 생성·디브리프)의 OpenAI 키(`openai`)와 따로 판단한다 */
export interface SttStatus {
  /** local: 서버 CPU에서 faster-whisper로 전사(외부 전송 없음) · openai: OpenAI 음성 인식 · off: 꺼짐 */
  provider: "local" | "openai" | "off";
  available: boolean;
  model: string | null;
  /** local만: 모델을 아직 안 불렀음(첫 전사 때 불러옴) · 부르는 중 · 준비됨 · 마지막 시도 실패 */
  state: "not_loaded" | "loading" | "ready" | "error" | null;
  /** 마지막으로 모델을 받거나 불러오지 못한 이유(사용자에게 보여도 되는 문장) */
  error: string | null;
}

export interface Health {
  ok: boolean;
  /** OpenAI 키가 있는가: AI 답변 코칭·꼬리질문·맞춤 질문·세션 디브리프 */
  openai: boolean;
  stt: SttStatus;
  auth_disabled: boolean;
}

export interface PracticeSettings {
  consented_at: string | null;
  keep_audio: boolean;
  retention_days: number;
}

/** 원본 녹음 삭제 결과. failed는 저장소 오류로 못 지운 개수(서버가 곧 다시 지운다).
 *  unchecked는 저장소 폴더 목록을 읽지 못해 남은 파일이 있는지 모른다는 뜻(서버가 곧 다시 확인해 지운다) */
export interface DeleteResult {
  deleted: number;
  failed: number;
  unchecked: boolean;
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
  input_status?: "legacy_unverified";
  lesson: string | null;
  next_action: string | null;
  moments: DebriefMoment[];
  generated_at: string;
  model: string;
}

export type DebriefStatus = "none" | "pending" | "done" | "failed" | "unavailable";

export interface CoachingReport {
  input_sha256?: string | null;
  input_status?: "current" | "legacy_unverified";
  competency_evidence?: CompetencyEvidence | null;
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
  essays?: { item_id: string; question_text: string; version_id: string; version_no: number; content: string; selection: "submitted" | "latest"; is_submitted: boolean; submission_confirmation?: "confirmed" | "legacy_unverified" | "none" }[];
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
  /** 디브리프 작업(답변 점검 + 요약)이 아직 도는 중(마지막 진행 신호가 5분 안). 이때는 다시 요청해도 서버가 새로 시작하지 않는다 */
  debrief_running: boolean;
  redrill: WeakAnswer[];
}

export interface SessionSummary {
  competency_keys?: string[];
  classification_missing_count?: number;
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
  state_source?: "events" | "manual" | "legacy";
  state_revision?: number;
  state_requires_baseline?: boolean;
}

/** POST /track/applications 요청(backend ApplicationIn). 서버가 정하는 id·source·시각은 보내지 않는다 */
export interface ApplicationCreate {
  company: string;
  position: string;
  job_category?: string;
  url?: string | null;
  applied_at?: string | null;
  stage?: Stage;
  status?: Status;
  notes?: string | null;
}

/** PATCH /track/applications/{id} 요청(backend ApplicationPatch). 보낸 필드만 바꾼다.
 *  회사·직무·분류·단계·상태는 null로 비울 수 없고(422), URL·지원일·메모는 null이면 비운다 */
export interface ApplicationPatch {
  company?: string;
  position?: string;
  job_category?: string;
  url?: string | null;
  applied_at?: string | null;
  stage?: Stage;
  status?: Status;
  notes?: string | null;
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
  submitted_version_id?: string | null;
  submission_confirmation?: "confirmed" | "legacy_unverified" | "none";
  submission_revision?: number;
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
  hold?: number;
  pass_rate: number | null;
}

export interface Stats {
  total: number;
  status: Record<Status, number>;
  funnel: FunnelRow[];
  by_job_category: { job_category: string; total: number; final_pass: number; funnel: FunnelRow[] }[];
  monthly: { month: string; count: number }[];
  applied_monthly?: { month: string; count: number }[];
  undated_count?: number;
}
