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

test("a failed change shows the server message and preserves the unsaved draft", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const app = await newApp(request, `실패처리 ${Date.now()}`);
  await page.route(`**/track/applications/${app.id}`, (route) => route.request().method() === "PATCH"
    ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "저장 실패(테스트)" }) })
    : route.continue());
  await page.goto(`/track/${app.id}`);
  const status = page.locator("label", { hasText: "상태" }).locator("select");
  await status.selectOption("보류");
  await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
  await expect(page.getByText("저장 실패(테스트)")).toBeVisible();
  await expect(status).toHaveValue("보류");
  await expect(page.locator("h1 + .chip")).toHaveText("진행중");
  // 페이지 전체가 오류 화면으로 바뀌지 않고 계속 쓸 수 있다
  await expect(page.getByRole("heading", { name: "기본 정보" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("parallel saves keep all three essay responses", async ({ page, request }) => {
  const app = await newApp(request, `동시문항 ${Date.now()}`);
  for (const question of ["지원 동기", "협업 경험", "성장 과정"]) {
    await request.post(`${API}/track/applications/${app.id}/essays`, { data: { question_text: question, content: "첫 버전" } });
  }
  const one = hold(); const two = hold();
  let count = 0;
  await page.route("**/track/essays/*/versions", async (route) => { const n = ++count; await (n === 1 ? one.gate : two.gate); await route.continue(); });
  await page.goto(`/track/${app.id}`);
  const boxes = page.getByPlaceholder("답변을 입력하세요");
  await boxes.nth(0).fill("첫 문항 수정");
  await boxes.nth(1).fill("둘째 문항 수정");
  await page.getByRole("button", { name: "새 버전 저장", exact: true }).nth(0).click();
  await page.getByRole("button", { name: "새 버전 저장", exact: true }).nth(1).click();
  two.release();
  await expect(page.locator(".version-list").nth(1).getByRole("button")).toHaveCount(2);
  one.release();
  await expect(page.locator(".version-list").nth(0).getByRole("button")).toHaveCount(2);
  await expect(page.locator(".version-list").nth(1).getByRole("button")).toHaveCount(2);
  await expect(boxes.nth(2)).toHaveValue("첫 버전");
});

test("basic info uses explicit save and preserves the draft on failure", async ({ page, request }) => {
  const app = await newApp(request, `정보초안 ${Date.now()}`);
  let patches = 0;
  await page.route(`**/track/applications/${app.id}`, (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patches++;
    return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "기본 정보 저장 실패" }) });
  });
  await page.goto(`/track/${app.id}`);
  await page.getByLabel("회사", { exact: true }).fill("계속 작성할 회사명");
  await page.getByLabel("직무", { exact: true }).click();
  expect(patches).toBe(0);
  await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("기본 정보 저장 실패");
  await expect(page.getByLabel("회사", { exact: true })).toHaveValue("계속 작성할 회사명");
});

test("old version submission is explicit and restore creates a draft", async ({ page, request }) => {
  const app = await newApp(request, `제출확인 ${Date.now()}`);
  const item = await (await request.post(`${API}/track/applications/${app.id}/essays`, { data: { question_text: "지원 동기", content: "실제 제출한 내용" } })).json();
  await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: "작성 중인 내용" } });
  await page.goto(`/track/${app.id}`);
  await page.locator(".version-list button", { hasText: "v1" }).click();
  await page.getByRole("button", { name: "이 버전을 제출본으로 확인" }).click();
  await expect(page.getByText("최근 확인한 제출본: v1")).toBeVisible();
  await page.locator(".version-list button", { hasText: "v1" }).click();
  await page.getByRole("button", { name: "이 버전으로 되돌리기" }).click();
  await expect(page.locator(".version-list button")).toHaveCount(3);
  await expect(page.getByText("최근 확인한 제출본: v1")).toBeVisible();
});

test("event editing and deletion keep manual state until explicit recalculation", async ({ page, request }) => {
  const app = await newApp(request, `전형편집 ${Date.now()}`);
  await request.post(`${API}/track/applications/${app.id}/events`, { data: { stage: "서류", result: "합격", event_date: "2026-11-01", memo: "처음 기록" } });
  await request.patch(`${API}/track/applications/${app.id}`, { data: { stage: "1차면접", status: "보류" } });
  await page.goto(`/track/${app.id}`);
  await expect(page.getByText("수동으로 정한 단계와 상태를 유지합니다.", { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '수정', exact: true }).click();
  await page.getByLabel('수정 메모').fill('내용 수정');
  await page.getByLabel('수정 결과').selectOption('불합격');
  await page.getByRole('button', { name: '기록 수정 저장' }).click();
  await expect(page.getByText('내용 수정', { exact: true })).toBeVisible();
  await expect(page.locator('h1 + .chip')).toHaveText('보류');
  await page.getByRole('button', { name: '기록으로 현재 상태 계산' }).click();
  await expect(page.locator('h1 + .chip')).toHaveText('불합격');
  await expect(page.getByRole('combobox', { name: '상태', exact: true })).toHaveValue('불합격');
  await page.getByRole('button', { name: '서류 2026-11-01 기록 삭제' }).click();
  await expect(page.locator('h1 + .chip')).toHaveText('진행중');
});

test("detail ignores an older id response after client navigation", async ({ page, request }) => {
  const first = await newApp(request, `오래된상세 ${Date.now()}`);
  const second = await newApp(request, `새상세 ${Date.now()}`);
  const delayed = hold();
  await page.route(`**/track/applications/${first.id}`, async (route) => { await delayed.gate; await route.continue(); });
  await page.goto(`/track/${first.id}`);
  await page.evaluate((nextId) => {
    history.pushState({}, '', `/track/${nextId}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, second.id);
  await expect(page.getByRole('heading', { name: `${second.company} · 백엔드` })).toBeVisible();
  delayed.release();
  await page.waitForResponse((r) => r.url().endsWith(first.id));
  await expect(page.getByRole('heading', { name: `${second.company} · 백엔드` })).toBeVisible();
});

for (const action of ["basic info", "event", "reload"] as const) {
  for (const essayChange of ["version", "submission"] as const) {
    test(`late ${action} detail keeps newer essay ${essayChange}`, async ({ page, request }) => {
      const app = await newApp(request, `상세경합 ${Date.now()}`);
      const item = await (await request.post(`${API}/track/applications/${app.id}/essays`, { data: { question_text: "지원 동기", content: "같은 답변" } })).json();
      if (essayChange === "submission") {
        const next = await (await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: "다른 초안" } })).json();
        await request.post(`${API}/track/versions/${next.versions[1].id}/submit`);
      }
      let eventId = "";
      if (action === "reload") {
        const detail = await (await request.post(`${API}/track/applications/${app.id}/events`, { data: { stage: "서류", result: "대기", event_date: "2026-11-01" } })).json();
        eventId = detail.events[0].id;
      }
      await page.goto(`/track/${app.id}`);
      await expect(page.getByRole("heading", { name: `${app.company} · 백엔드` })).toBeVisible();
      const delayed = hold();
      let captured!: () => void;
      const capturedResponse = new Promise<void>((resolve) => { captured = resolve; });
      const path = action === "basic info" ? `/track/applications/${app.id}` : action === "event" ? `/track/applications/${app.id}/events` : `/track/applications/${app.id}`;
      const method = action === "basic info" ? "PATCH" : action === "event" ? "POST" : "GET";
      await page.route((url) => url.port === "8011" && url.pathname === path, async (route) => {
        if (route.request().method() !== method) return route.continue();
        const response = await route.fetch();
        const body = await response.body();
        captured();
        await delayed.gate;
        await route.fulfill({ response, body });
      });
      if (action === "basic info") {
        await page.getByLabel("회사", { exact: true }).fill(`${app.company} 수정`);
        await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
      } else if (action === "event") {
        await page.getByRole("button", { name: "기록", exact: true }).click();
      } else {
        await page.getByRole("button", { name: "수정", exact: true }).click();
        await page.getByLabel("수정 메모").fill(`수정 ${eventId}`);
        await page.getByRole("button", { name: "기록 수정 저장" }).click();
      }
      await capturedResponse;
      if (essayChange === "version") {
        await page.getByPlaceholder("답변을 입력하세요").fill("더 최신인 답변");
        await page.getByRole("button", { name: "새 버전 저장", exact: true }).click();
        await expect(page.locator(".version-list button")).toHaveCount(2);
      } else {
        await page.locator(".version-list button", { hasText: "v1" }).click();
        await page.getByRole("button", { name: "이 버전을 제출본으로 확인" }).click();
        await expect(page.getByText("최근 확인한 제출본: v1")).toBeVisible();
      }
      const lateResponse = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === method);
      delayed.release();
      await lateResponse;
      if (action === "basic info") await expect(page.getByRole("heading", { name: `${app.company} 수정 · 백엔드` })).toBeVisible();
      if (essayChange === "version") {
        await expect(page.locator(".version-list button")).toHaveCount(2);
        await expect(page.getByPlaceholder("답변을 입력하세요")).toHaveValue("더 최신인 답변");
      } else {
        await expect(page.getByText("최근 확인한 제출본: v1")).toBeVisible();
        await expect(page.locator(".version-list button")).toHaveCount(2);
      }
    });
  }
}

test("manually edited legacy application still asks for its unknown event baseline", async ({ page, request }) => {
  const app = await newApp(request, `레거시기준 ${Date.now()}`);
  let detail = { ...app, state_source: "legacy", state_requires_baseline: true, essay_items: [], events: [] };
  await page.route((url) => url.port === "8011" && url.pathname === `/track/applications/${app.id}`, async (route) => {
    if (route.request().method() === "PATCH") detail = { ...detail, ...route.request().postDataJSON(), state_source: "manual" };
    await route.fulfill({ json: detail });
  });
  let resetBody: Record<string, string> | undefined;
  await page.route(`**/track/applications/${app.id}/state-from-events`, async (route) => {
    resetBody = route.request().postDataJSON();
    if (!resetBody?.baseline_stage || !resetBody?.baseline_status) return route.fulfill({ status: 422, json: { detail: "기록 전 기준이 필요합니다" } });
    detail = { ...detail, stage: resetBody.baseline_stage, status: resetBody.baseline_status, state_source: "events", state_requires_baseline: false };
    await route.fulfill({ json: detail });
  });
  await page.goto(`/track/${app.id}`);
  await page.getByRole("combobox", { name: "상태", exact: true }).selectOption("보류");
  await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
  await expect(page.locator("h1 + .chip")).toHaveText("보류");
  await expect(page.getByRole("combobox", { name: "기록 전 기준 단계", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "기록 전 기준 단계", exact: true }).selectOption("인적성");
  await page.getByRole("combobox", { name: "기록 전 기준 상태", exact: true }).selectOption("진행중");
  await page.getByRole("button", { name: "기록으로 현재 상태 계산" }).click();
  await expect(page.locator("h1 + .chip")).toHaveText("진행중");
  expect(resetBody).toEqual({ baseline_stage: "인적성", baseline_status: "진행중" });
});
