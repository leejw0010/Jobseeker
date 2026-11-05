// 실제 Chrome 확장 설치 대신 Chrome API 대역을 사용한 팝업 수명주기 검사.
import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "popup lifecycle"));

async function popup(page: import('@playwright/test').Page, existing = false) {
  await page.addInitScript(() => {
    const listeners: ((changes: object, area: string) => void)[] = [];
    const session: Record<string, string> = { accessToken: "account-a-test" };
    let reads = 0;
    (window as any).chrome = {
      tabs: { query: async () => [{ id: 1, url: "https://example.com/job/1", title: "[회사] 개발자" }], create: async () => {} },
      scripting: { executeScript: async () => { reads++; return [{ result: { url: "https://example.com/job/1", title: "[회사] 개발자", ogTitle: "", siteName: "", h1: "" } }]; } },
      storage: {
        sync: { get: async () => ({ apiUrl: location.origin + "/fake-api" }) },
        session: {
          get: async () => ({ ...session }),
          set: async (values: Record<string, string>) => { const oldValue = session.accessToken; Object.assign(session, values); listeners.forEach((f) => f({ accessToken: { oldValue, newValue: session.accessToken } }, "session")); },
          remove: async () => { const oldValue = session.accessToken; delete session.accessToken; listeners.forEach((f) => f({ accessToken: { oldValue } }, "session")); },
        },
        onChanged: { addListener: (f: typeof listeners[number]) => listeners.push(f), removeListener: () => {} },
      },
    };
    (window as any).pageReads = () => reads;
  });
  const saved = { id: "example-id", company: "회사", position: "개발자", job_category: "개발", url: "https://example.com/job/1", stage: "서류", status: "진행중" };
  await page.route("**/extension-fixture/**", async (route) => {
    const name = new URL(route.request().url()).pathname.split('/').pop() || "popup.html";
    await route.fulfill({ body: await readFile(resolve('../extension-track', name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html' });
  });
  await page.route("**/fake-api/track/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({ json: path.endsWith('/stats') ? { total: existing ? 1 : 0, status: { 진행중: 1, 합격: 0 } } : path.endsWith('/sync') ? { created: false } : existing ? [saved] : [] });
  });
  await page.goto('/extension-fixture/popup.html');
  return saved;
}

test("popup reads page metadata only after a user gesture", async ({ page }) => {
  await popup(page);
  await expect(page.locator('#save-form')).toBeVisible();
  expect(await page.evaluate(() => (window as any).pageReads())).toBe(0);
  await page.getByRole('button', { name: '페이지 제목으로 채우기' }).click();
  await expect(page.locator('#company')).toHaveValue('회사');
  expect(await page.evaluate(() => (window as any).pageReads())).toBe(1);
});

test("existing posting can be confirmed as submitted by an explicit click", async ({ page }) => {
  await popup(page, true);
  const body = page.waitForRequest((r) => r.url().endsWith('/track/sync'));
  await page.getByRole('button', { name: '지원 완료로 표시' }).click();
  expect((await body).postDataJSON()).toMatchObject({ submitted: true, essays: [] });
});

test("account switching clears stale recent rows and old request results", async ({ page }) => {
  await popup(page, true);
  await expect(page.locator('#recent')).toContainText('회사');
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await page.route('**/fake-api/track/**', async (route) => { await gate; await route.fulfill({ json: [] }); });
  await page.evaluate(() => (window as any).chrome.storage.session.set({ accessToken: 'account-b-test' }));
  await expect(page.locator('#recent')).toBeEmpty();
  await expect(page.locator('#existing')).toBeHidden();
  release();
});

test("401 clears session and offers login again", async ({ page }) => {
  await popup(page, true);
  await page.route('**/fake-api/track/**', (route) => route.fulfill({ status: 401, json: { detail: '세션이 만료되었습니다' } }));
  await page.getByRole('button', { name: '지원 완료로 표시' }).click();
  await expect(page.getByRole('button', { name: '다시 로그인' })).toBeVisible();
  expect(await page.evaluate(() => (window as any).chrome.storage.session.get())).toEqual({});
  await expect(page.locator('#recent')).toBeEmpty();
});

test("login CTA requires configured team URL instead of assuming a web login route", async ({ page }) => {
  await popup(page, true);
  await page.route('**/fake-api/track/**', (route) => route.fulfill({ status: 401, json: { detail: 'expired' } }));
  await page.getByRole('button', { name: '지원 완료로 표시' }).click();
  await page.getByRole('button', { name: '다시 로그인' }).click();
  await expect(page.getByRole('alert')).toContainText('팀 로그인 주소');
});
