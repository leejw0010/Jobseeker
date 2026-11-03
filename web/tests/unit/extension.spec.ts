// extension-track(빌드 없는 MV3 확장)의 순수 함수. chrome API는 가짜 객체로 대신한다(브라우저·확장 설치 없음)
import { expect, test } from "@playwright/test";
import { guessJobCategory, guessPosting } from "../../../extension-track/extract.js";
import { getAccessToken, hostPermissionWarning, setAccessToken } from "../../../extension-track/settings.js";

const page = (p: Partial<{ url: string; title: string; ogTitle: string; siteName: string; h1: string }>) =>
  ({ url: "https://example.com/jobs/1", title: "", ogTitle: "", siteName: "", h1: "", ...p });

test("bracketed company titles split into company and position", () => {
  expect(guessPosting(page({ ogTitle: "[토스] 서버 개발자 채용 | 원티드" }))).toMatchObject({
    company: "토스", position: "서버 개발자", job_category: "개발" });
});

test("platform names are dropped and the next part becomes the company", () => {
  expect(guessPosting(page({ title: "데이터 분석가 모집 - 카카오 - 사람인" }))).toMatchObject({
    company: "카카오", position: "데이터 분석가", job_category: "데이터" });
});

test("falls back to the site name and host when the title has no company", () => {
  expect(guessPosting(page({ title: "프로덕트 디자이너", siteName: "당근" })).company).toBe("당근");
  expect(guessPosting(page({ title: "프로덕트 디자이너", url: "https://careers.example.co.kr/1" })).company).toBe("example");
});

test("job categories follow the rule order", () => {
  expect(guessJobCategory("ML 엔지니어")).toBe("데이터");
  expect(guessJobCategory("UX 디자이너")).toBe("디자인");
  expect(guessJobCategory("회계 담당")).toBe("기타");
});

/** chrome.storage.session 대역(메모리) */
function fakeChrome(withSession = true) {
  const store: Record<string, unknown> = {};
  const area = {
    get: async (k: string) => (k in store ? { [k]: store[k] } : {}),
    set: async (v: Record<string, unknown>) => { Object.assign(store, v); },
    remove: async (k: string) => { delete store[k]; },
  };
  (globalThis as { chrome?: unknown }).chrome = { storage: withSession ? { session: area, sync: area } : { sync: area } };
  return store;
}

test("access token lives in session storage and can be cleared", async () => {
  const store = fakeChrome();
  expect(await getAccessToken()).toBeNull();
  await setAccessToken("token-for-test");
  expect(await getAccessToken()).toBe("token-for-test");
  await setAccessToken(null);
  expect(await getAccessToken()).toBeNull();
  expect(store).toEqual({});
});

test("no session storage means no token (dev mode)", async () => {
  fakeChrome(false);
  expect(await getAccessToken()).toBeNull();
});

test("warns when the API address is not covered by host_permissions", () => {
  const manifest = { host_permissions: ["http://localhost:8000/*", "https://*.example.com/*"] };
  expect(hostPermissionWarning("http://localhost:8000", manifest)).toBeNull();
  expect(hostPermissionWarning("https://api.example.com/", manifest)).toBeNull();
  expect(hostPermissionWarning("https://jobseeker.onrender.com", manifest)).toContain("host_permissions");
  expect(hostPermissionWarning("http://localhost:8001", manifest)).toContain("http://localhost:8001");
  expect(hostPermissionWarning("https://anything.dev", { host_permissions: ["<all_urls>"] })).toBeNull();
  expect(hostPermissionWarning("not a url", manifest)).toContain("주소");
});
