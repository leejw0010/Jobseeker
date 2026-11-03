import { expect, test, type APIRequestContext } from "@playwright/test";
import { API } from "./env";

// 지원 관리 화면의 비동기 흐름(저장 중 입력, 응답 순서, 실패 처리). 화면 크기와 무관해 desktop에서만 돈다
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop", "흐름 검사: 화면 크기와 무관"));

async function newApp(request: APIRequestContext, company: string) {
  return (await request.post(`${API}/track/applications`, { data: { company, position: "백엔드", job_category: "개발" } })).json();
}

/** 다음 요청이 올 때까지 붙잡아 두는 경로 처리기. release()를 부르면 그때 서버로 보낸다 */
function hold() {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  return { gate, release: () => release() };
}

test("typing while a version is saving keeps the newer draft", async ({ page, request }) => {
  const app = await newApp(request, `자소서저장 ${Date.now()}`);
  await request.post(`${API}/track/applications/${app.id}/essays`, { data: { question_text: "지원 동기", content: "첫 버전" } });
  const { gate, release } = hold();
  await page.route("**/track/essays/*/versions", async (route) => { await gate; await route.continue(); });
  await page.goto(`/track/${app.id}`);
  const box = page.getByPlaceholder("답변을 입력하세요");
  await box.fill("A");
  const saved = page.waitForResponse((r) => r.url().includes("/versions") && r.request().method() === "POST");
  await page.getByRole("button", { name: "새 버전 저장" }).click();
  await box.fill("AB"); // 저장 응답이 오기 전에 이어서 입력한다
  release();
  await saved;
  await expect(page.locator(".version-list button")).toHaveCount(2);
  await expect(box).toHaveValue("AB");
  await expect(page.getByRole("button", { name: "새 버전 저장" })).toBeEnabled();
});

test("restoring an old version puts it in the editor", async ({ page, request }) => {
  const app = await newApp(request, `자소서복원 ${Date.now()}`);
  const item = await (await request.post(`${API}/track/applications/${app.id}/essays`, {
    data: { question_text: "지원 동기", content: "첫 버전" } })).json();
  await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: "둘째 버전" } });
  await page.goto(`/track/${app.id}`);
  await page.locator(".version-list button", { hasText: "v1" }).click();
  await page.getByRole("button", { name: "이 버전으로 되돌리기" }).click();
  await expect(page.locator(".version-list button")).toHaveCount(3);
  await expect(page.getByPlaceholder("답변을 입력하세요")).toHaveValue("첫 버전");
});

test("an older filter response never replaces the newer one", async ({ page, request }) => {
  const tok = `역전${Date.now()}`;
  await newApp(request, `${tok}가`);
  await newApp(request, `${tok}가나다`);
  const isList = (u: URL, q: string) => u.pathname === "/track/applications" && u.searchParams.get("q") === q;
  // 먼저 보낸 검색(tok)의 응답만 늦게 온다
  await page.route((u) => isList(u, tok), async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto("/track");
  const search = page.getByPlaceholder("회사·직무 검색");
  const slow = page.waitForResponse((r) => isList(new URL(r.url()), tok));
  await search.fill(tok);
  await page.waitForRequest((r) => isList(new URL(r.url()), tok));
  await search.fill(`${tok}가나다`);
  await page.waitForResponse((r) => isList(new URL(r.url()), `${tok}가나다`));
  await slow;
  await page.waitForTimeout(100);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText(`${tok}가나다`);
});

test("a failed change shows the server message and keeps the saved value", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const app = await newApp(request, `실패처리 ${Date.now()}`);
  await page.route(`**/track/applications/${app.id}`, (route) => route.request().method() === "PATCH"
    ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "저장 실패(테스트)" }) })
    : route.continue());
  await page.goto(`/track/${app.id}`);
  const status = page.locator("label", { hasText: "상태" }).locator("select");
  await status.selectOption("보류");
  await expect(page.getByText("저장 실패(테스트)")).toBeVisible();
  await expect(status).toHaveValue("진행중");
  // 페이지 전체가 오류 화면으로 바뀌지 않고 계속 쓸 수 있다
  await expect(page.getByRole("heading", { name: "기본 정보" })).toBeVisible();
  expect(errors).toEqual([]);
});
