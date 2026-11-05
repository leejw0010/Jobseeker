// 확장 설정(chrome.storage.sync). 옵션 페이지에서 바꿀 수 있다.
export const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  webUrl: "http://localhost:5173",
  loginUrl: "",
};

export async function getSettings() {
  const saved = await chrome.storage.sync.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...saved };
}

export async function saveSettings(values) {
  await chrome.storage.sync.set(values);
}

// ───────── 로그인 토큰 연결 지점 ─────────
// 로그인(Supabase Auth)을 붙이는 쪽(팀 공통 로그인, ① Apply 확장과 합칠 때 등)이 setAccessToken()으로 액세스 토큰을 넣는다.
// 토큰은 기기 사이에 동기화되는 sync가 아니라 브라우저를 닫으면 지워지는 session 저장소에만 둔다.
// 토큰이 없으면 요청에 Authorization을 붙이지 않는다(백엔드 개발 모드 AUTH_DISABLED=true에서만 동작).
const TOKEN_KEY = "accessToken";

/** 액세스 토큰을 저장한다. null이나 빈 값이면 지운다(로그아웃). */
export async function setAccessToken(token) {
  const area = chrome.storage?.session;
  if (!area) throw new Error("chrome.storage.session을 쓸 수 없는 브라우저예요");
  if (token) await area.set({ [TOKEN_KEY]: token });
  else await area.remove(TOKEN_KEY);
}

/** 저장된 액세스 토큰. 없으면 null. */
export async function getAccessToken() {
  const area = chrome.storage?.session;
  if (!area) return null;
  const value = (await area.get(TOKEN_KEY))[TOKEN_KEY];
  return typeof value === "string" && value ? value : null;
}

// ───────── 주소 권한 확인 ─────────

/** host_permissions 패턴 하나가 이 주소(origin)를 덮는가. "<all_urls>", "scheme://host/*", "*://", "*.도메인"만 다룬다. */
function covers(pattern, url) {
  if (pattern === "<all_urls>") return true;
  const m = /^(\*|https?):\/\/([^/]+)\//.exec(pattern);
  if (!m) return false;
  const [, scheme, host] = m;
  if (scheme !== "*" && `${scheme}:` !== url.protocol) return false;
  if (host === "*") return true;
  if (host.startsWith("*.")) return url.host === host.slice(2) || url.host.endsWith(host.slice(1));
  return url.host === host;
}

/** API 주소가 manifest.json의 host_permissions에 없으면 안내 문구, 있으면 null.
 *  백엔드 CORS가 chrome-extension://을 허용하면 권한 없이도 요청은 되지만, 배포 주소는 두 곳을 함께 맞춘다. */
export function hostPermissionWarning(apiUrl, manifest) {
  let url;
  try {
    url = new URL(apiUrl);
  } catch {
    return "백엔드 API 주소 형식이 올바르지 않아요.";
  }
  const patterns = manifest?.host_permissions ?? [];
  if (patterns.some((p) => covers(p, url))) return null;
  return `${url.origin}이(가) manifest.json의 host_permissions에 없어요. 배포 주소라면 "${url.origin}/*"를 추가하고 확장을 다시 불러오세요.`;
}
