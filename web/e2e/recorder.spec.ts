import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API } from "./env";

// 마이크 권한 응답이 늦게 오는 경우. 권한 창 대신 getUserMedia(audio)를 붙잡아 두었다가 원할 때 허용한다
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop", "흐름 검사: 화면 크기와 무관"));

async function seed(request: APIRequestContext) {
  await request.put(`${API}/practice/settings`, { data: { consent: true } });
  const q = await (await request.post(`${API}/practice/questions`, { data: { category: "인성", text: `마이크 질문 ${Date.now()}-${Math.random()}` } })).json();
  return (await request.post(`${API}/practice/sessions`, { data: { mode: "free", question_ids: [q.id], prep_sec: 0, answer_sec: 30 } })).json();
}

async function holdMicrophone(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __mic: { calls: number; streams: MediaStream[]; waiting: (() => void)[] } };
    w.__mic = { calls: 0, streams: [], waiting: [] };
    const md = navigator.mediaDevices;
    const original = md.getUserMedia.bind(md);
    md.getUserMedia = async (c?: MediaStreamConstraints) => {
      if (!c?.audio) return original(c);
      w.__mic.calls++;
      await new Promise<void>((r) => w.__mic.waiting.push(r));
      const s = await original(c);
      w.__mic.streams.push(s);
      return s;
    };
  });
}
const mic = (page: Page) => page.evaluate(() => {
  const m = (window as unknown as { __mic: { calls: number; streams: MediaStream[] } }).__mic;
  return { calls: m.calls, streams: m.streams.length,
    live: m.streams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length };
});
const grant = (page: Page) => page.evaluate(() =>
  (window as unknown as { __mic: { waiting: (() => void)[] } }).__mic.waiting.splice(0).forEach((r) => r()));

test("permission granted after leaving the interview releases the microphone at once", async ({ page, request }) => {
  await holdMicrophone(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await expect.poll(async () => (await mic(page)).calls).toBe(1);
  await page.getByRole("link", { name: "지원 관리" }).click(); // 권한 응답 전에 면접 화면을 떠난다
  await expect(page.getByRole("heading", { name: "지원 관리" })).toBeVisible();
  await grant(page);
  await expect.poll(async () => (await mic(page)).streams).toBe(1);
  await expect.poll(async () => (await mic(page)).live).toBe(0);
});

test("clicking start twice while asking asks once and records once", async ({ page, request }) => {
  await holdMicrophone(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  const start = page.getByRole("button", { name: "답변 시작", exact: true });
  await start.click();
  await expect(start).toBeDisabled(); // 권한을 묻는 동안은 다시 누를 수 없다
  await start.dispatchEvent("click"); // 그래도 이벤트가 들어오면 무시한다
  await page.waitForTimeout(300);
  await grant(page);
  await expect(page.getByText("녹음 중 · 경과 시간")).toBeVisible();
  const m = await mic(page);
  expect(m.calls).toBe(1);
  expect(m.live).toBe(1);
});

test("optional audio analysis failure does not prevent recording or saving an answer", async ({ page, request }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: class { constructor() { throw new Error("test: audio analysis unavailable"); } },
    });
  });
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("button", { name: "답변 시작", exact: true }).click();
  await expect(page.getByText("녹음 중 · 경과 시간")).toBeVisible();
  // Free mode briefly starts with the configured answer limit before its elapsed
  // timer ticks. That limit is not proof that audio has actually been captured.
  await expect.poll(async () => {
    const [minutes, seconds] = (await page.locator(".timer").innerText()).split(":").map(Number);
    const elapsed = minutes * 60 + seconds;
    return elapsed >= 2 && elapsed < session.answer_sec;
  }).toBe(true);
  const saved = page.waitForResponse((r) => r.url().endsWith(`/practice/answers/${session.answers[0].id}/audio`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "답변 끝내기", exact: true }).click();
  const response = await saved;
  expect(response.status()).toBe(200);
  expect((await response.json()).recorded_at).toBeTruthy();
});

test("a star rating cannot be sent again while the first one is saving", async ({ page, request }) => {
  const q = await (await request.post(`${API}/practice/questions`, { data: { category: "인성", text: `별점 ${Date.now()}` } })).json();
  const session = await (await request.post(`${API}/practice/sessions`, { data: { mode: "free", question_ids: [q.id] } })).json();
  await request.patch(`${API}/practice/answers/${session.answers[0].id}`, { data: { transcript: "제가 맡은 일을 끝냈습니다." } });
  let patches = 0;
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await page.route("**/practice/answers/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patches++;
    await gate;
    await route.continue();
  });
  await page.goto(`/practice/sessions/${session.id}`);
  const four = page.getByRole("radio", { name: "4점", exact: true });
  const two = page.getByRole("radio", { name: "2점", exact: true });
  await four.click();
  try {
    await expect(four).toBeDisabled();
    await expect(two).toBeDisabled();
    await two.evaluate(element => (element as HTMLButtonElement).click());
    expect(patches).toBe(1);
  } finally {
    release();
  }
  await expect(four).toBeChecked();
  await expect(four).toBeEnabled();
  await expect(two).not.toBeChecked();
  expect(patches).toBe(1);
  const saved = await (await request.get(`${API}/practice/sessions/${session.id}`)).json();
  expect(saved.answers[0].self_rating).toBe(4);
});
