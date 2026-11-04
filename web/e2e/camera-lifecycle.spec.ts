import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API } from "./env";

// 권한 응답과 검출기 모듈 준비를 따로 늦춘다. 실제 Chromium 카메라 트랙이 준비 중에도 바로 정리되는지 검사한다.
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop", "화면 크기와 무관한 카메라 수명 검사"));

async function seed(request: APIRequestContext) {
  const q = await (await request.post(`${API}/practice/questions`, {
    data: { category: "인성", text: `카메라 정리 질문 ${Date.now()}-${Math.random()}` },
  })).json();
  return (await request.post(`${API}/practice/sessions`, {
    data: { mode: "free", question_ids: [q.id], prep_sec: 0, answer_sec: 30 },
  })).json();
}

async function watchCamera(page: Page, holdPermission = false) {
  await page.addInitScript((hold) => {
    const w = window as unknown as {
      __cameraLifecycle: { streams: MediaStream[]; grant?: () => void };
    };
    w.__cameraLifecycle = { streams: [] };
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints?: MediaStreamConstraints) => {
      if (!constraints?.video) return original(constraints);
      if (hold) await new Promise<void>((resolve) => { w.__cameraLifecycle.grant = resolve; });
      const stream = await original(constraints);
      w.__cameraLifecycle.streams.push(stream);
      return stream;
    };
  }, holdPermission);
}

const camera = (page: Page) => page.evaluate(() => {
  const { streams, grant } = (window as unknown as {
    __cameraLifecycle: { streams: MediaStream[]; grant?: () => void };
  }).__cameraLifecycle;
  return { acquired: streams.length, live: streams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length,
    permissionPending: !!grant };
});

const grantCamera = (page: Page) => page.evaluate(() => {
  (window as unknown as { __cameraLifecycle: { grant?: () => void } }).__cameraLifecycle.grant?.();
});

async function holdDetector(page: Page) {
  let requested = false;
  let release!: () => void;
  const ready = new Promise<void>((resolve) => { release = resolve; });
  await page.route(/\/src\/video\/fakeDetector\.ts(?:\?|$)/, async (route) => {
    requested = true;
    await ready;
    await route.continue();
  });
  return { requested: () => requested, release };
}

for (const latePermission of [false, true]) {
  test(`${latePermission ? "late permission" : "acquired camera"}: leaving while the detector loads releases the camera before the detector finishes`, async ({ page, request }) => {
    await watchCamera(page, latePermission);
    const detector = await holdDetector(page);
    const session = await seed(request);
    await page.goto(`/practice/sessions/${session.id}/run`);
    try {
      await page.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
      await expect.poll(detector.requested).toBe(true);
      if (latePermission) await expect.poll(async () => (await camera(page)).permissionPending).toBe(true);
      else await expect.poll(async () => (await camera(page)).live).toBe(1);
      await page.getByRole("link", { name: "지원 관리", exact: true }).click();
      await expect(page.getByRole("heading", { name: "지원 관리", exact: true })).toBeVisible();
      if (latePermission) await grantCamera(page);
      await expect.poll(async () => (await camera(page)).acquired).toBe(1);
      // 검출기 응답은 아직 붙잡고 있다. 이 시점에 트랙이 살아 있으면 화면을 떠나도 카메라가 켜져 있는 결함이다.
      await expect.poll(async () => (await camera(page)).live, { timeout: 3000 }).toBe(0);
    } finally {
      detector.release();
      await page.unrouteAll({ behavior: "wait" });
    }
  });
}

test("detector failure cancels pending camera setup and closes a later permission stream", async ({ page, request }) => {
  await watchCamera(page, true);
  await page.addInitScript(() => localStorage.setItem("e2e-face-detector", "fail"));
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  await page.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect.poll(async () => (await camera(page)).permissionPending).toBe(true);
  await expect(page.locator(".camera-panel").getByRole("alert")).toContainText("영상 분석 모델을 불러오지 못해", { timeout: 3000 });
  await grantCamera(page);
  await expect.poll(async () => (await camera(page)).acquired).toBe(1);
  await expect.poll(async () => (await camera(page)).live).toBe(0);
});
