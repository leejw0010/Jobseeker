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

/** chrome.storage 대역(메모리). session과 sync는 서로 다른 저장소다. */
function fakeChrome(withSession = true) {
  const session: Record<string, unknown> = {};
  const sync: Record<string, unknown> = {};
  const area = (store: Record<string, unknown>) => ({
    get: async (k: string) => (k in store ? { [k]: store[k] } : {}),
    set: async (v: Record<string, unknown>) => { Object.assign(store, v); },
    remove: async (k: string) => { delete store[k]; },
  });
  (globalThis as { chrome?: unknown }).chrome = {
    storage: withSession ? { session: area(session), sync: area(sync) } : { sync: area(sync) },
  };
  return { session, sync };
}

test("access token lives in session storage and can be cleared", async () => {
  const { session, sync } = fakeChrome();
  expect(await getAccessToken()).toBeNull();
  await setAccessToken("token-for-test");
  expect(session).toEqual({ accessToken: "token-for-test" });
  expect(sync).toEqual({});
  expect(await getAccessToken()).toBe("token-for-test");
  await setAccessToken(null);
  expect(await getAccessToken()).toBeNull();
  expect(session).toEqual({});
  expect(sync).toEqual({});
});

test("no session storage means no token (dev mode)", async () => {
  const { sync } = fakeChrome(false);
  sync.accessToken = "synchronized-token-for-test";
  expect(await getAccessToken()).toBeNull();
  await expect(setAccessToken("token-for-test")).rejects.toThrow("chrome.storage.session");
  expect(sync).toEqual({ accessToken: "synchronized-token-for-test" });
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

import * as extensionApi from "../../../extension-track/api.js";

test("savePosting always sends explicit submitted false and no harvested essays", async () => {
  fakeChrome();
  const previous = globalThis.fetch;
  let payload: Record<string, unknown> = {};
  globalThis.fetch = async (_url, init) => {
    payload = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ created: true }), { status: 200 });
  };
  try {
    await extensionApi.api.savePosting({ company: "회사", position: "개발", url: "https://example.com/jobs/1" });
    expect(payload.submitted).toBe(false);
    expect(payload.essays).toEqual([]);
  } finally { globalThis.fetch = previous; }
});

test("401 preserves typed status and clears only the token used by the failed request", async () => {
  const { session } = fakeChrome();
  await setAccessToken("expired-test-token");
  const previous = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "다시 로그인하세요" }), { status: 401 });
  try {
    const err = await extensionApi.api.stats().catch((error: unknown) => error);
    expect(err).toMatchObject({ status: 401, message: "다시 로그인하세요" });
    expect(err.constructor.name).toBe("ApiError");
    expect(session).toEqual({});
    await setAccessToken("old-test-token");
    globalThis.fetch = async () => {
      await setAccessToken("new-test-token");
      return new Response(JSON.stringify({ detail: "expired" }), { status: 401 });
    };
    await extensionApi.api.stats().catch(() => {});
    expect(await getAccessToken()).toBe("new-test-token");
  } finally { globalThis.fetch = previous; }
});
