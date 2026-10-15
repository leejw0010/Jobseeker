import type {
  Application,
  ApplicationDetail,
  Category,
  EssayItem,
  PracticeAnswer,
  PracticeSession,
  PracticeSettings,
  Question,
  Rubric,
  SessionSummary,
  Stats,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

/** 로그인(Supabase Auth) 담당 코드가 액세스 토큰을 돌려주는 함수를 등록한다.
 *  등록 전에는 백엔드 개발 모드(AUTH_DISABLED=true)의 고정 사용자로 동작한다. */
let tokenProvider: (() => Promise<string | null>) | null = null;
export function setAuthTokenProvider(fn: () => Promise<string | null>) {
  tokenProvider = fn;
}

async function headers(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  const token = tokenProvider ? await tokenProvider() : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch(BASE + path, {
    method,
    headers: await headers(body && !isForm ? { "Content-Type": "application/json" } : {}),
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, msg);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const qs = (p: Record<string, string | undefined>) => {
  const s = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]).toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => req<{ ok: boolean; openai: boolean; auth_disabled: boolean }>("GET", "/health"),

  // ② Practice
  questions: (f: { category?: string; job_category?: string; source?: string; q?: string } = {}) =>
    req<Question[]>("GET", `/practice/questions${qs(f)}`),
  addQuestion: (b: { category: Category; text: string; job_category?: string | null }) =>
    req<Question>("POST", "/practice/questions", b),
  deleteQuestion: (id: string) => req<void>("DELETE", `/practice/questions/${id}`),
  generateQuestions: (b: {
    application_id?: string;
    company?: string;
    position?: string;
    job_category?: string;
    essay_text?: string;
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
    const res = await fetch(`${BASE}/practice/answers/${answerId}/audio`, { headers: await headers() });
    if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "원본 녹음은 삭제됐어요" : "녹음을 불러오지 못했습니다");
    return URL.createObjectURL(await res.blob());
  },
  retryTranscribe: (answerId: string) => req<PracticeAnswer>("POST", `/practice/answers/${answerId}/transcribe`),
  reflect: (answerId: string, b: { self_rating?: number | null; reflection_note?: string | null; transcript?: string | null }) =>
    req<PracticeAnswer>("PATCH", `/practice/answers/${answerId}`, b),
  feedback: (answerId: string) => req<PracticeAnswer>("POST", `/practice/answers/${answerId}/feedback`),
  deleteAudio: (answerId: string) => req<PracticeAnswer>("DELETE", `/practice/answers/${answerId}/audio`),
  rubric: () => req<Rubric>("GET", "/practice/rubric"),
  debrief: (sessionId: string) => req<PracticeSession>("POST", `/practice/sessions/${sessionId}/debrief`),
  /** answer_ids를 비우면 서버가 고른 약점 질문으로 새 세션을 만든다. */
  redrill: (sessionId: string, answerIds?: string[]) =>
    req<PracticeSession>("POST", `/practice/sessions/${sessionId}/redrill`, answerIds ? { answer_ids: answerIds } : {}),

  // 녹음 동의·보관 설정
  settings: () => req<PracticeSettings>("GET", "/practice/settings"),
  updateSettings: (b: { consent?: boolean; keep_audio?: boolean }) => req<PracticeSettings>("PUT", "/practice/settings", b),
  deleteAllRecordings: () => req<{ deleted: number }>("DELETE", "/practice/recordings"),

  // ③ Track
  applications: (f: { status?: string; stage?: string; job_category?: string; q?: string } = {}) =>
    req<Application[]>("GET", `/track/applications${qs(f)}`),
  application: (id: string) => req<ApplicationDetail>("GET", `/track/applications/${id}`),
  createApplication: (b: Partial<Application> & { company: string; position: string }) =>
    req<ApplicationDetail>("POST", "/track/applications", b),
  updateApplication: (id: string, b: Partial<Application>) =>
    req<ApplicationDetail>("PATCH", `/track/applications/${id}`, b),
  deleteApplication: (id: string) => req<void>("DELETE", `/track/applications/${id}`),
  addEvent: (id: string, b: { stage: string; result: string; event_date?: string; memo?: string }) =>
    req<ApplicationDetail>("POST", `/track/applications/${id}/events`, b),
  deleteEvent: (id: string) => req<void>("DELETE", `/track/events/${id}`),
  addEssay: (appId: string, b: { question_text: string; char_limit?: number | null; content?: string }) =>
    req<EssayItem>("POST", `/track/applications/${appId}/essays`, b),
  deleteEssay: (id: string) => req<void>("DELETE", `/track/essays/${id}`),
  addVersion: (itemId: string, b: { content: string; is_submitted?: boolean }) =>
    req<EssayItem>("POST", `/track/essays/${itemId}/versions`, b),
  restoreVersion: (versionId: string) => req<EssayItem>("POST", `/track/versions/${versionId}/restore`),
  stats: () => req<Stats>("GET", "/track/stats"),
};
