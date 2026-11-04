import { expect, test, type Page } from "@playwright/test";

// 개발 전용 시선 실험실(0단계). 가짜 검출기의 가상 사용자가 화면에 표시된 점·렌즈 안내를 따라 본다.
// 이 테스트는 배선·흐름·판정 표시를 확인한다. 실제 웹캠 정확도는 확인하지 못한다(docs/progress.md 수동 절차).
test.beforeEach(({}, testInfo) => test.skip(testInfo.project.name !== "desktop"));
test.setTimeout(180_000);

async function startLab(page: Page, mode: string, opts: { skipRate?: boolean } = {}) {
  await page.addInitScript((m) => {
    localStorage.setItem("e2e-face-detector", m);
    localStorage.setItem("e2e-gaze-scale", "0.2"); // e2e에서만 단계 시간을 줄인다
  }, mode);
  await page.goto("/dev/gaze-lab");
  await expect(page.getByRole("heading", { name: "시선 실험실(개발 전용)" })).toBeVisible();
  await page.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.getByText("얼굴이 화면 안에 있어요")).toBeVisible();
  if (opts.skipRate) await page.getByLabel("주기 시험 건너뛰기").check();
  await page.getByRole("button", { name: "시험 시작" }).click();
}

const verdictRow = (page: Page, name: string) => page.getByTestId("lab-verdicts").getByRole("row").filter({ hasText: name });

test("separable fake user: lens and screen pass, panel region performance and rates are reported, nothing is sent", async ({ page }) => {
  const sent: string[] = [];
  page.on("request", (r) => { const b = r.postData(); if (b) sent.push(b); });
  await startLab(page, "gaze");
  await expect(page.getByRole("heading", { name: "시험 결과" })).toBeVisible({ timeout: 150_000 });
  await expect(verdictRow(page, "H1 렌즈 대 화면 위쪽")).toContainText("통과");
  await expect(verdictRow(page, "H2 화면 좌표")).toContainText("통과");
  const panels = page.getByTestId("lab-panels");
  for (const h of ["32px", "120px", "240px"]) await expect(panels).toContainText(h);
  await expect(panels).toContainText("적중");
  await expect(panels).toContainText("question 오판");
  const rates = page.getByTestId("lab-rates");
  for (const hz of ["초당 4회", "초당 10회", "초당 15회"]) await expect(rates).toContainText(hz);
  await expect(page.getByText("통과해도 실제 사용에 충분한 정확도를 보장하지 않아요")).toBeVisible();
  expect(sent.filter((b) => /ex|ey|landmark|gaze|e50|valAuc/i.test(b))).toEqual([]);
});

test("lens at the top of the screen: G1 is reported as unable to tell lens from screen top", async ({ page }) => {
  await startLab(page, "gaze-inseparable", { skipRate: true });
  await expect(page.getByRole("heading", { name: "시험 결과" })).toBeVisible({ timeout: 150_000 });
  await expect(verdictRow(page, "H1 렌즈 대 화면 위쪽")).toContainText("실패");
  await expect(page.getByText("화면 위쪽과 렌즈를 구별할 수 없음")).toBeVisible();
  await expect(verdictRow(page, "H2 화면 좌표")).toContainText("통과"); // G1이 안 돼도 G2는 따로
});

test("noisy tracking fails G2; leaving the page clears the results", async ({ page }) => {
  await startLab(page, "gaze-noisy", { skipRate: true });
  await expect(page.getByRole("heading", { name: "시험 결과" })).toBeVisible({ timeout: 150_000 });
  await expect(verdictRow(page, "H2 화면 좌표")).toContainText("실패");
  await page.goto("/practice");
  await page.goto("/dev/gaze-lab");
  await expect(page.getByRole("heading", { name: "시선 실험실(개발 전용)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "시험 결과" })).toHaveCount(0);
});

test("changing the window size during the test invalidates the run", async ({ page }) => {
  await startLab(page, "gaze", { skipRate: true });
  await expect(page.getByTestId("lab-prompt")).toBeVisible();
  await page.setViewportSize({ width: 1000, height: 650 });
  await expect(page.getByText("창 크기·위치·배율이 바뀌어 이번 시험은 무효예요")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "처음부터 다시" })).toBeVisible();
});

test("dots are drawn exactly where they are scored, and diagnostics are shown", async ({ page }) => {
  await startLab(page, "gaze", { skipRate: true });
  const dot = page.locator("[data-gaze-target]").first();
  await expect(dot).toBeVisible();
  const m = await dot.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { cx: r.left + r.width / 2, cy: r.top + r.height / 2, tx: Number(el.dataset.targetX), ty: Number(el.dataset.targetY) };
  });
  // 채점 좌표(스크롤바를 뺀 화면 기준)와 실제로 그린 점의 가운데가 같아야 한다
  expect(Math.abs(m.cx - m.tx)).toBeLessThan(1);
  expect(Math.abs(m.cy - m.ty)).toBeLessThan(1);
  await expect(page.getByRole("heading", { name: "시험 결과" })).toBeVisible({ timeout: 150_000 });
  const diag = page.getByTestId("lab-diag");
  await expect(diag).toContainText("val-lens-forward");
  await expect(diag).toContainText("시험 앞→끝 변화");
  await expect(diag).toContainText("val-25-25");
});
