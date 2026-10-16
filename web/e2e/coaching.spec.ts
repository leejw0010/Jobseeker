import { expect, test, type APIRequestContext } from "@playwright/test";

const API = "http://127.0.0.1:8011";
async function seed(request: APIRequestContext, mode: "free" | "mock" = "free") {
  // 녹음 동의가 없는 상태에서 시작한다(글 답변은 동의 없이, 녹음은 동의 패널을 거쳐야 한다)
  await request.put(`${API}/practice/settings`, { data: { consent: false } });
  const suffix = `${Date.now()}-${Math.random()}`;
  const app = await (await request.post(`${API}/track/applications`, { data: {
    company: "검증용 소프트웨어", position: "백엔드 개발자", job_category: "개발",
  } })).json();
  const item = await (await request.post(`${API}/track/applications/${app.id}/essays`, { data: {
    question_text: "성과 경험", content: `성능 개선 프로젝트 ${suffix.slice(-5)}에서 캐시를 도입하여 응답 시간을 40% 개선했습니다.`,
  } })).json();
  await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: item.versions[0].content, is_submitted: true } });
  await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: "다른 프로젝트에서 70% 개선했습니다." } });
  const q = await (await request.post(`${API}/practice/questions`, { data: { category: "직무", text: "성과를 어떻게 측정하셨나요?" } })).json();
  const session = await (await request.post(`${API}/practice/sessions`, { data: {
    mode, application_id: app.id, question_ids: [q.id], followups_enabled: true,
    prep_sec: 0, answer_sec: 10, job_description: "API 성능 측정과 캐시 운영 경험",
  } })).json();
  return { app, session };
}

test("submitted source → text answer → follow-up → evidence review → focused re-drill", async ({ page, request }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const { app } = await seed(request);
  await page.goto(`/practice?application=${app.id}`);
  await expect(page.getByRole("heading", { name: "이번 면접의 기준" })).toBeVisible();
  const generate = page.locator("section").filter({ has: page.getByRole("heading", { name: "맞춤 질문 만들기" }) });
  await generate.getByRole("spinbutton").fill("1");
  await generate.getByRole("button", { name: "질문 생성" }).click();
  await expect(page.getByText("1개 선택됨")).toBeVisible();
  await page.getByRole("button", { name: "선택한 질문으로 자유 연습" }).click();
  await expect(page.getByRole("heading", { name: "이번 면접의 기준 자료" })).toBeVisible();
  await page.locator(".source-detail summary").first().click();
  await expect(page.locator(".evidence-text").first()).toContainText("40%");
  await expect(page.locator(".evidence-text").first()).not.toContainText("70%");
  await page.getByRole("radio", { name: "글로 답변" }).check();
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await page.getByLabel("내 답변", { exact: true }).fill("프로젝트에서 제가 개선했습니다.");
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  await page.getByRole("button", { name: "꼬리질문 받기" }).click();
  await expect(page.locator(".followup-reason")).toContainText("수치");
  await expect(page.locator(".runner-q")).toContainText("측정");
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await page.getByLabel("내 답변", { exact: true }).fill("동일한 요청 1000개를 보내 제가 응답 시간을 측정했습니다. 평균 500ms에서 300ms로 감소했습니다.");
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  await page.getByRole("button", { name: "면접 마치고 회고 보기" }).click();
  await expect(page.locator(".coaching-panel").first()).toContainText("기본 점검");
  await expect(page.locator(".criterion").first()).toContainText("프로젝트에서 제가 개선했습니다.");
  await page.getByRole("button", { name: "답변 점검", exact: true }).last().click();
  await expect(page.locator(".coaching-panel")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "보완 항목 1개 다시 연습" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: `../docs/screenshots/coaching-review-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "보완 항목 1개 다시 연습" }).click();
  await expect(page.getByRole("heading", { name: /보완 연습/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "이전 답변과 회고 보기" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "글로 답변" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("recording upload failure retains audio for retry and blocks advancing", async ({ page, request }) => {
  const { session } = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  // 첫 녹음 전에는 녹음 동의가 필요하다(글 답변에는 묻지 않는다). 동의하면 바로 답변을 시작한다
  await page.getByRole("button", { name: "동의하고 시작" }).click();
  await expect(page.getByText("녹음 중 · 경과 시간")).toBeVisible();
  // A short capture interval supplies actual fake-device audio to MediaRecorder.
  await page.waitForTimeout(750);
  let failed = false;
  await page.route("**/practice/answers/*/audio", async (route) => {
    if (!failed && route.request().method() === "POST") { failed = true; await route.abort("failed"); }
    else await route.continue();
  });
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  await expect(page.getByRole("button", { name: "녹음 저장 다시 시도" })).toBeVisible();
  await expect(page.getByRole("button", { name: "면접 마치고 회고 보기" })).toBeDisabled();
  await page.getByRole("button", { name: "녹음 저장 다시 시도" }).click();
  await expect(page.getByRole("button", { name: "녹음 저장 다시 시도" })).toHaveCount(0);
  await page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요").fill("직접 입력한 녹음 답변입니다.");
  await page.getByRole("button", { name: "면접 마치고 회고 보기" }).click();
  await expect(page.locator("audio")).toHaveCount(1);
  await expect(page.getByLabel("전사문 (직접 고칠 수 있어요)")).toHaveValue("직접 입력한 녹음 답변입니다.");
});

test("mock timer saves the current text once at the deadline", async ({ page, request }) => {
  const { session } = await seed(request, "mock");
  await page.clock.install();
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("radio", { name: "글로 답변" }).check();
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await page.getByLabel("내 답변", { exact: true }).fill("제가 직접 측정한 결과입니다.");
  await page.clock.fastForward(10100);
  await expect(page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요")).toHaveValue("제가 직접 측정한 결과입니다.");
  const saved = await (await request.get(`${API}/practice/sessions/${session.id}`)).json();
  expect(saved.answers).toHaveLength(1);
  expect(saved.answers[0].transcript).toBe("제가 직접 측정한 결과입니다.");
});

test("permanent audio error can recover to text and unfinished last answer can resume", async ({ page, request }) => {
  const { session } = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  // 첫 녹음 전에는 녹음 동의가 필요하다(글 답변에는 묻지 않는다). 동의하면 바로 답변을 시작한다
  await page.getByRole("button", { name: "동의하고 시작" }).click();
  await expect(page.getByText("녹음 중 · 경과 시간")).toBeVisible();
  await page.waitForTimeout(750);
  await page.route("**/practice/answers/*/audio", (route) => route.fulfill({ status: 413, contentType: "application/json", body: '{"detail":"녹음 파일이 너무 큽니다"}' }));
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  await page.getByRole("button", { name: "녹음 대신 글로 답변" }).click();
  await page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요").fill("제가 직접 작성한 대체 답변입니다.");
  // Save this last answer without finishing, then return through the review UI.
  await page.getByRole("button", { name: "답변만 저장" }).click();
  await page.getByRole("link", { name: "지금까지 저장한 답변 보기" }).click();
  await page.getByRole("link", { name: "면접 이어서 마치기" }).click();
  await expect(page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요")).toHaveValue("제가 직접 작성한 대체 답변입니다.");
  await page.getByRole("button", { name: "면접 마치고 회고 보기" }).click();
  await expect(page).toHaveURL(new RegExp(`/practice/sessions/${session.id}$`));
  const saved = await (await request.get(`${API}/practice/sessions/${session.id}`)).json();
  expect(saved.finished_at).toBeTruthy();
});

test("recorded answer can retry transcription and display returned Korean text", async ({ page, request }) => {
  const { session } = await seed(request);
  const aid = session.answers[0].id;
  await page.goto(`/practice/sessions/${session.id}/run`);
  // 첫 녹음 전에는 녹음 동의가 필요하다(글 답변에는 묻지 않는다). 동의하면 바로 답변을 시작한다
  await page.getByRole("button", { name: "동의하고 시작" }).click();
  await expect(page.getByText("녹음 중 · 경과 시간")).toBeVisible();
  await page.waitForTimeout(750);
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  const text = "저는 캐시를 직접 설계하고 응답 시간을 측정했습니다.";
  // The provider result is simulated: this checks the UI contract, not recognition accuracy.
  await page.route(`**/practice/answers/${aid}/transcribe`, async (route) => {
    const updated = await request.patch(`${API}/practice/answers/${aid}`, { data: { transcript: text } });
    await route.fulfill({ json: { ...await updated.json(), stt_status: "done" } });
  });
  await page.getByRole("button", { name: "음성 인식 다시 시도" }).click();
  await expect(page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요")).toHaveValue(text);
  await expect(page.getByRole("button", { name: "꼬리질문 받기" })).toBeEnabled();
});
