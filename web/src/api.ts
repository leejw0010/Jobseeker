import type {
  Application,
  ApplicationCreate,
  ApplicationDetail,
  ApplicationPatch,
  Category,
  CoachingRubric,
  ClassificationInput,
  PracticeTaxonomy,
  DeleteResult,
  EssayItem,
  Health,
  PracticeAnswer,
  PracticeSession,
  PracticeSettings,
  PracticeSettingsUpdate,
  Question,
  SessionSummary,
  Stats,
} from "./types";

import { clearAllVoice } from "./delivery/voice";
import { clearAllVideo } from "./video/metrics";

const BASE = (import.meta.env?.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type ApiClientOptions = {
  baseUrl?: string;
  getAccessToken?: (() => Promise<string | null>) | null;
  /** Host owns Supabase refresh. Writes are never automatically replayed. */
  onUnauthorized?: () => Promise<void>;
  onSessionReset?: () => void;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Router- and Supabase-SDK-independent transport for a host application. */
export function createApiClient(options: ApiClientOptions = {}) {
  let generation = 0;
  let refresh: Promise<void> | null = null;
  const pending = new Set<AbortController>();
  function resetSession() {
    generation++;
    for (const controller of pending) controller.abort();
    pending.clear();
    options.onSessionReset?.();
  }
  async function request(method: string, path: string, body?: unknown): Promise<Response> {
    const revision = generation;
    const controller = new AbortController();
    pending.add(controller);
    const current = () => {
      if (revision !== generation || controller.signal.aborted) throw new DOMException("사용자가 변경되어 요청을 취소했어요", "AbortError");
    };
    const send = async () => {
      const token = await options.getAccessToken?.();
      current();
      const isForm = body instanceof FormData;
      const headers: Record<string,string> = body !== undefined && !isForm ? {"Content-Type":"application/json"} : {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch((options.baseUrl ?? BASE).replace(/\/$/, "") + path, {
        method, headers, signal: controller.signal,
        body: body === undefined ? undefined : isForm ? body as FormData : JSON.stringify(body),
      });
      current();
      return response;
    };
    try {
      let response = await send();
      if (response.status === 401 && options.onUnauthorized) {
        if (!refresh) refresh = Promise.resolve().then(options.onUnauthorized).finally(() => { refresh = null; });
        await refresh;
        current();
        if (method === "GET") response = await send();
      }
      return response;
    } finally { pending.delete(controller); }
  }
  async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const revision = generation;
    const res = await request(method, path, body);
    if (!res.ok) {
      let msg = res.statusText;
      try {
        const j = await res.json();
        msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      } catch { /* empty response */ }
      throw new ApiError(res.status, msg);
    }
    const value = res.status === 204 ? undefined : await res.json();
    if (revision !== generation) throw new DOMException("사용자가 변경되어 요청을 취소했어요", "AbortError");
    return value as T;
  }
const qs = (p: Record<string, string | string[] | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(p).forEach(([key, value]) => (Array.isArray(value) ? value : [value]).forEach((v) => { if (v) params.append(key, v); }));
  const s = params.toString();
  return s ? `?${s}` : "";
};

return {
  resetSession,
  health: () => req<Health>("GET", "/health"),

  // ② Practice
  taxonomy: () => req<PracticeTaxonomy>("GET", "/practice/taxonomy"),
  classifyQuestion: (id: string, b: ClassificationInput) => req<Question>("PUT", `/practice/questions/${id}/classification`, b),
  questions: (f: { category?: string; job_category?: string; source?: string; q?: string; question_type?: string[]; competency_key?: string[]; competency_match?: "any" | "all" } = {}) =>
    req<Question[]>("GET", `/practice/questions${qs(f)}`),
  addQuestion: (b: { category: Category; text: string; job_category?: string | null } & ClassificationInput) =>
    req<Question>("POST", "/practice/questions", b),
  deleteQuestion: (id: string) => req<void>("DELETE", `/practice/questions/${id}`),
  generateQuestions: (b: ClassificationInput & {
    application_id?: string;
    company?: string;
    position?: string;
    job_category?: string;
    essay_text?: string;
    essay_basis?: "submitted" | "latest";
    count: number;
  }) => req<Question[]>("POST", "/practice/questions/generate", b),
  createSession: (b: {
    mode: "free" | "mock";
    title?: string;
    application_id?: string;
    question_ids?: string[];
    count?: number;
    categories?: Category[];
    job_category?: string;
    prep_sec?: number;
    answer_sec?: number;
    essay_basis?: "submitted" | "latest";
    job_description?: string;
    followups_enabled?: boolean;
    question_types?: string[];
    competency_keys?: string[];
    competency_match?: "any" | "all";
  }) => req<PracticeSession>("POST", "/practice/sessions", b),
  sessions: () => req<SessionSummary[]>("GET", "/practice/sessions"),
  session: (id: string) => req<PracticeSession>("GET", `/practice/sessions/${id}`),
  finishSession: (id: string) => req<PracticeSession>("POST", `/practice/sessions/${id}/finish`),
  deleteSession: (id: string) => req<void>("DELETE", `/practice/sessions/${id}`),
  uploadAudio: (answerId: string, blob: Blob, durationSec: number) => {
    const fd = new FormData();
    const ext = blob.type.includes("mp4") ? "m4a" : "webm";
    fd.append("file", blob, `answer.${ext}`);
    fd.append("duration_sec", durationSec.toFixed(1));
    return req<PracticeAnswer>("POST", `/practice/answers/${answerId}/audio`, fd);
  },
  audioUrl: async (answerId: string) => {
    const revision = generation;
    const res = await request("GET", `/practice/answers/${answerId}/audio`);
    if (!res.ok) {
      // 404는 두 경우다: 원본을 지웠다(서버가 삭제 기록을 보고 알린다) / 지우지 않았는데 저장소에서 파일을 찾지 못했다
      const detail = await res.json().then((j) => j.detail, () => null);
      const deleted = "원본 녹음은 삭제됐어요";
      throw new ApiError(res.status, res.status !== 404 ? "녹음을 불러오지 못했습니다" : detail === deleted ? deleted : "녹음 파일을 찾지 못했어요");
    }
    const blob = await res.blob();
    if (revision !== generation) throw new DOMException("사용자가 변경되어 요청을 취소했어요", "AbortError");
    return URL.createObjectURL(blob);
  },
  retryTranscribe: (answerId: string) => req<PracticeAnswer>("POST", `/practice/answers/${answerId}/transcribe`),
  reflect: (answerId: string, b: { self_rating?: number | null; reflection_note?: string | null; transcript?: string | null; input_mode?: "text" | "transcript" }) =>
    req<PracticeAnswer>("PATCH", `/practice/answers/${answerId}`, b),
  feedback: (answerId: string) => req<PracticeAnswer>("POST", `/practice/answers/${answerId}/feedback`),
  coach: (answerId: string) => req<PracticeAnswer>("POST", `/practice/answers/${answerId}/coach`),
  followup: (answerId: string) => req<PracticeSession>("POST", `/practice/answers/${answerId}/followup`),
  redrill: (sessionId: string) => req<PracticeSession>("POST", `/practice/sessions/${sessionId}/redrill`),
  debrief: (sessionId: string) => req<PracticeSession>("POST", `/practice/sessions/${sessionId}/debrief`),
  rubric: () => req<CoachingRubric>("GET", "/practice/rubric"),
  deleteAudio: (answerId: string) => req<PracticeAnswer>("DELETE", `/practice/answers/${answerId}/audio`),

  // 녹음 동의·보관 설정
  settings: () => req<PracticeSettings>("GET", "/practice/settings"),
  updateSettings: (b: { consent?: boolean; keep_audio?: boolean }) =>
    req<PracticeSettingsUpdate>("PUT", "/practice/settings", b),
  deleteAllRecordings: () => req<DeleteResult>("DELETE", "/practice/recordings"),

  // ③ Track
  applications: (f: { status?: string; stage?: string; job_category?: string; q?: string } = {}) =>
    req<Application[]>("GET", `/track/applications${qs(f)}`),
  application: (id: string) => req<ApplicationDetail>("GET", `/track/applications/${id}`),
  createApplication: (b: ApplicationCreate) =>
    req<ApplicationDetail>("POST", "/track/applications", b),
  updateApplication: (id: string, b: ApplicationPatch) =>
    req<ApplicationDetail>("PATCH", `/track/applications/${id}`, b),
  deleteApplication: (id: string) => req<void>("DELETE", `/track/applications/${id}`),
  addEvent: (id: string, b: { stage: string; result: string; event_date?: string; memo?: string }) =>
    req<ApplicationDetail>("POST", `/track/applications/${id}/events`, b),
  deleteEvent: (id: string) => req<void>("DELETE", `/track/events/${id}`),
  updateEvent: (id: string, b: { stage?: string; result?: string; event_date?: string; memo?: string | null }) =>
    req<ApplicationDetail>("PATCH", `/track/events/${id}`, b),
  useEventState: (id: string, b: { baseline_stage?: string; baseline_status?: string }) =>
    req<ApplicationDetail>("POST", `/track/applications/${id}/state-from-events`, b),
  addEssay: (appId: string, b: { question_text: string; char_limit?: number | null; content?: string }) =>
    req<EssayItem>("POST", `/track/applications/${appId}/essays`, b),
  deleteEssay: (id: string) => req<void>("DELETE", `/track/essays/${id}`),
  addVersion: (itemId: string, b: { content: string; is_submitted?: boolean }) =>
    req<EssayItem>("POST", `/track/essays/${itemId}/versions`, b),
  restoreVersion: (versionId: string) => req<EssayItem>("POST", `/track/versions/${versionId}/restore`),
  submitVersion: (versionId: string) => req<EssayItem>("POST", `/track/versions/${versionId}/submit`),
  stats: () => req<Stats>("GET", "/track/stats"),
};

}

const hostOptions: ApiClientOptions = { onSessionReset: () => { clearAllVoice(); clearAllVideo(); } };
export const api = createApiClient(hostOptions);

/** Existing entry point retained. Call on sign-out/user switch, never store tokens in URLs. */
export function setAuthTokenProvider(fn: (() => Promise<string | null>) | null) {
  hostOptions.getAccessToken = fn;
  api.resetSession();
}
export function configureApiClient(options: Omit<ApiClientOptions, "onSessionReset"> & { onSessionReset?: () => void }) {
  Object.assign(hostOptions, options, { onSessionReset: () => { clearAllVoice(); clearAllVideo(); options.onSessionReset?.(); } });
  api.resetSession();
}
