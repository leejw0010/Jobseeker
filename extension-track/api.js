// FastAPI 백엔드(③ Track) 호출. 웹 대시보드와 같은 API를 쓴다.
import { getSettings } from "./settings.js";

/** 로그인(Supabase Auth)을 붙이면 액세스 토큰을 돌려주도록 이 함수를 바꾼다.
 *  지금은 백엔드 개발 모드(AUTH_DISABLED=true)의 고정 사용자로 동작한다. */
async function getToken() {
  return null;
}

async function req(method, path, body) {
  const { apiUrl } = await getSettings();
  const token = await getToken();
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(apiUrl.replace(/\/$/, "") + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`백엔드(${apiUrl})에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.`);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* 본문 없음 */
    }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const qs = (p) => {
  const s = new URLSearchParams(Object.entries(p).filter(([, v]) => v)).toString();
  return s ? `?${s}` : "";
};

export const api = {
  applications: (filter = {}) => req("GET", `/track/applications${qs(filter)}`),
  stats: () => req("GET", "/track/stats"),
  /** URL 기준으로 지원 건을 만들거나 갱신한다(① 자동입력과 같은 엔드포인트). */
  savePosting: (p) =>
    req("POST", "/track/sync", {
      company: p.company,
      position: p.position,
      job_category: p.job_category,
      url: p.url,
      essays: [],
      submitted: p.submitted,
    }),
};
