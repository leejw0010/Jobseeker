import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// 카메라 자세 분석(선택 기능). 검출기는 playwright.config.ts의 VITE_E2E_FAKE_FACE로 가짜를 쓰고, 카메라는 Chromium의 가짜 장치를 쓴다
const API = "http://127.0.0.1:8011";
async function seed(request: APIRequestContext) {
  const q = await (await request.post(`${API}/practice/questions`, { data: { category: "인성", text: `카메라 분석 질문 ${Date.now()}-${Math.random()}` } })).json();
  return (await request.post(`${API}/practice/sessions`, { data: { mode: "free", question_ids: [q.id], prep_sec: 0, answer_sec: 10 } })).json();
}

/** getUserMedia가 돌려준 카메라 스트림을 모아 둔다(정리됐는지 확인용). deny면 카메라만 거부한다 */
async function watchCamera(page: Page, deny = false) {
  await page.addInitScript((denyVideo) => {
    const w = window as unknown as { __cameraStreams: MediaStream[] };
    w.__cameraStreams = [];
    const md = navigator.mediaDevices;
    const original = md.getUserMedia.bind(md);
    md.getUserMedia = async (c?: MediaStreamConstraints) => {
      if (c?.video && denyVideo) throw new DOMException("denied", "NotAllowedError");
      const s = await original(c);
      if (c?.video) w.__cameraStreams.push(s);
      return s;
    };
  }, deny);
}
const liveCameraTracks = (page: Page) => page.evaluate(() =>
  (window as unknown as { __cameraStreams: MediaStream[] }).__cameraStreams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length);

async function answerByTextAndFinish(page: Page, waitMs = 0) {
  await page.getByRole("radio", { name: "글로 답변" }).check();
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await page.getByLabel("내 답변", { exact: true }).fill("팀 프로젝트에서 일정 관리를 맡았습니다.");
  if (waitMs) await page.waitForTimeout(waitMs); // 고개 방향 기준을 잡을 만큼 표본을 모은다(초당 4회)
  await page.getByRole("button", { name: "답변 끝내기" }).click();
  await page.getByRole("button", { name: "면접 마치고 회고 보기" }).click();
  await expect(page.getByRole("heading", { name: "다음 연습으로 연결하기" })).toBeVisible();
}
const cameraHeading = (page: Page) => page.getByRole("heading", { name: "카메라 자세 분석" });

test("camera analysis measures during the answer, shows numbers in review, and keeps them only in memory", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const sent: string[] = [];
  page.on("request", (r) => { if (r.url().startsWith(API)) sent.push(r.postData() ?? ""); });
  await watchCamera(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  const panel = page.locator(".camera-panel");
  await expect(panel).toContainText("시선 추적이 아니에요");

  await panel.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.getByLabel("내 카메라 미리보기")).toBeVisible();
  await expect(panel.getByRole("status")).toContainText("얼굴");
  // 끄면 카메라를 바로 놓고, 다시 켤 수 있다
  await panel.getByRole("button", { name: "카메라 끄기" }).click();
  await expect.poll(() => liveCameraTracks(page)).toBe(0);
  await panel.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.getByLabel("내 카메라 미리보기")).toBeVisible();

  await answerByTextAndFinish(page, 4000);
  // 회고로 넘어가면(면접 화면을 떠나면) 카메라를 놓는다
  expect(await liveCameraTracks(page)).toBe(0);
  const card = page.locator(".video-report");
  await expect(cameraHeading(page)).toBeVisible();
  await expect(card).toContainText("얼굴 검출 비율");
  await expect(card).toContainText("화면을 벗어난 시간");
  await expect(card.locator("tbody tr")).toHaveCount(1);
  await expect(card.locator("tbody tr td").nth(2)).toHaveText(/^\d+%$/);
  await expect(card.locator("tbody tr td").nth(4)).toHaveText(/^\d+%$/); // 고개 방향 기준을 잡았다
  await expect(card).not.toContainText(/자신감이|긴장한|합격 가능성이 (높|낮)/);
  // 수치는 서버로 보내지 않는다
  expect(sent.filter((b) => /detectedMs|turnedMs|yaw|pitch/.test(b))).toEqual([]);
  // 메모리에만 있으므로 새로고침하면 사라진다
  await page.reload();
  await expect(page.getByRole("heading", { name: "다음 연습으로 연결하기" })).toBeVisible();
  await expect(cameraHeading(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("camera permission denied keeps the interview working", async ({ page, request }) => {
  await watchCamera(page, true);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.locator(".camera-panel").getByRole("alert")).toContainText("카메라를 사용할 수 없어요");
  await answerByTextAndFinish(page);
  await expect(cameraHeading(page)).toHaveCount(0);
});

test("analysis model load failure releases the camera and keeps the interview working", async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem("e2e-face-detector", "fail"));
  await watchCamera(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.locator(".camera-panel").getByRole("alert")).toContainText("영상 분석 모델을 불러오지 못해");
  await expect.poll(() => liveCameraTracks(page)).toBe(0);
  await expect(page.getByLabel("내 카메라 미리보기")).toHaveCount(0);
  await answerByTextAndFinish(page);
  await expect(cameraHeading(page)).toHaveCount(0);
});
