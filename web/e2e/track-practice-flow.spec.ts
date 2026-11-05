import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API } from "./env";
import type { ApplicationDetail, InterviewContext, Stats } from "../src/types";

// All application, essay, version, confirmation and event writes below use the real UI.
// API requests are read-only checks against the actual IDs created by that UI.
async function readStats(request: APIRequestContext): Promise<Stats> {
  const response = await request.get(`${API}/track/stats`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function state(page: Page, stage: string, status: string) {
  await expect(page.getByRole("combobox", { name: "현재 단계", exact: true })).toHaveValue(stage);
  await expect(page.getByRole("combobox", { name: "상태", exact: true })).toHaveValue(status);
  await expect(page.locator("h1 + .chip")).toHaveText(status);
}

test("UI-created Track history and confirmed essays remain frozen in linked Practice", async ({ page, request }, testInfo) => {
  const baseline = await readStats(request);
  const company = `연습회사 ${testInfo.project.name} ${Date.now()}`;
  const position = "제품 개발자";
  const applied = "2026-11-01";
  const jobUrl = `https://example.com/jobs/practice-only-${testInfo.project.name}-${Date.now()}`;
  const essays = [
    { question: "지원 동기", answer: "작은 도구를 만들어 반복 작업을 줄였습니다." },
    { question: "협업 경험", answer: "역할을 나누고 매주 진행 상황을 공유했습니다." },
    { question: "문제 해결", answer: "오류를 재현한 뒤 원인을 기록하고 수정했습니다." },
  ];
  const first = page.getByRole("region", { name: essays[0].question, exact: true });
  const version = (n: number) => first.locator(".version-list").getByRole("button", { name: new RegExp(`^v${n}\\s`) });

  await test.step("A: create a complete application and refresh persisted fields", async () => {
    await page.goto("/track");
    await page.getByRole("button", { name: "+ 지원 건 추가", exact: true }).click();
    await page.getByLabel("회사", { exact: true }).fill(company);
    await page.getByLabel("직무(포지션)", { exact: true }).fill(position);
    await page.getByLabel("지원일", { exact: true }).fill(applied);
    await page.getByLabel("채용 공고 URL", { exact: true }).fill(jobUrl);
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await expect(page).toHaveURL(/\/track\/[\w-]+$/);
    await page.reload();
    await expect(page.getByRole("heading", { name: `${company} · ${position}`, exact: true })).toBeVisible();
    await expect(page.getByLabel("회사", { exact: true })).toHaveValue(company);
    await expect(page.getByLabel("직무", { exact: true })).toHaveValue(position);
    await expect(page.getByLabel("지원일", { exact: true })).toHaveValue(applied);
    await expect(page.getByLabel("공고 URL", { exact: true })).toHaveValue(jobUrl);
    await expect(page.getByRole("link", { name: "공고 열기 ↗" })).toHaveAttribute("href", jobUrl);
  });
  const applicationId = new URL(page.url()).pathname.split("/").pop()!;
  const applicationPath = `/track/${applicationId}`;

  await test.step("B: add three questions and save each answer through the UI", async () => {
    for (const essay of essays) {
      await page.getByRole("textbox", { name: "새 자소서 문항", exact: true }).fill(essay.question);
      await page.getByRole("button", { name: "문항 추가", exact: true }).click();
      const card = page.getByRole("region", { name: essay.question, exact: true });
      await card.getByRole("textbox", { name: `${essay.question} 답변`, exact: true }).fill(essay.answer);
      await card.getByRole("button", { name: "새 버전 저장", exact: true }).click();
      await expect(card.locator(".version-list button")).toHaveCount(1);
    }
    await page.reload();
    for (const essay of essays) await expect(page.getByLabel(`${essay.question} 답변`, { exact: true })).toHaveValue(essay.answer);
  });

  await test.step("C: diff, append-only restoration, old-version confirmation and a newer draft", async () => {
    await first.getByRole("textbox").fill("작은 도구를 만들어 반복 작업을 크게 개선했습니다.");
    await first.getByRole("button", { name: "새 버전 저장", exact: true }).click();
    await expect(first.locator(".version-list button")).toHaveCount(2);
    await first.getByText("직전 버전(v1)과 비교", { exact: true }).click();
    await expect(first.locator("del")).toContainText("줄였습니다.");
    await expect(first.locator("ins")).toContainText("크게 개선했습니다.");
    await version(1).click();
    await first.getByRole("button", { name: "이 버전으로 되돌리기", exact: true }).click();
    await expect(first.locator(".version-list button")).toHaveCount(3);
    await expect(first.getByRole("textbox")).toHaveValue(essays[0].answer);
    await version(2).click();
    await expect(first.locator(".diff")).toHaveText("작은 도구를 만들어 반복 작업을 크게 개선했습니다.");
    await version(1).click();
    await first.getByRole("button", { name: "이 버전을 제출본으로 확인", exact: true }).click();
    await expect(first.getByText("최근 확인한 제출본: v1", { exact: true })).toBeVisible();
    await version(3).click();
    await first.getByRole("textbox").fill("새 초안에서는 검토 방법을 덧붙였습니다.");
    await first.getByRole("button", { name: "새 버전 저장", exact: true }).click();
    await expect(first.locator(".version-list button")).toHaveCount(4);
    await expect(first.getByText("최근 확인한 제출본: v1", { exact: true })).toBeVisible();
    await page.reload();
    await expect(first.getByRole("textbox")).toHaveValue("새 초안에서는 검토 방법을 덧붙였습니다.");
    await expect(first.getByText("최근 확인한 제출본: v1", { exact: true })).toBeVisible();
  });

  async function addEvent(stage: string, result: string, date: string, memo: string) {
    await page.getByRole("combobox", { name: "기록 단계", exact: true }).selectOption(stage);
    await page.getByRole("combobox", { name: "기록 결과", exact: true }).selectOption(result);
    await page.getByLabel("기록 날짜", { exact: true }).fill(date);
    await page.getByPlaceholder("메모 (예: 면접 질문, 분위기)").fill(memo);
    await page.getByRole("button", { name: "기록", exact: true }).click();
    await expect(page.getByRole("cell", { name: memo, exact: true })).toBeVisible();
  }

  async function statsMatch(status: "진행중" | "불합격" | "보류", stage: string) {
    const stats = await readStats(request);
    expect(stats.total).toBe(baseline.total + 1);
    for (const value of ["진행중", "합격", "불합격", "보류"] as const) {
      expect(stats.status[value]).toBe(baseline.status[value] + (value === status ? 1 : 0));
    }
    const row = stats.funnel.find((r) => r.stage === stage)!;
    const previous = baseline.funnel.find((r) => r.stage === stage)!;
    expect(row.reached).toBe(previous.reached + 1);
    expect(row.failed).toBe(previous.failed + (status === "불합격" ? 1 : 0));
    expect(row.hold).toBe((previous.hold ?? 0) + (status === "보류" ? 1 : 0));
    await page.getByRole("link", { name: "통계", exact: true }).click();
    await expect(page.locator(".tile").filter({ hasText: "전체 지원" }).locator(".v")).toHaveText(String(stats.total));
    await expect(page.locator(".tile").filter({ hasText: "✕ 불합격" }).locator(".v")).toHaveText(String(stats.status["불합격"]));
    await page.getByRole("button", { name: "표로 보기", exact: true }).click();
    const tableRow = page.getByRole("row").filter({ has: page.getByRole("cell", { name: stage, exact: true }) });
    await expect(tableRow.getByRole("cell")).toHaveText([
      stage, String(row.reached), String(row.passed), String(row.failed), String(row.pending - (row.hold ?? 0)), String(row.hold ?? 0),
      row.pass_rate == null ? "–" : `${Math.round(row.pass_rate * 100)}%`,
    ]);
    await page.goto(applicationPath);
    await state(page, stage, status);
  }

  await test.step("D: event history, correction, deletion and explicit manual override keep stats coherent", async () => {
    await addEvent("서류", "합격", "2026-11-02", "서류 확인");
    await state(page, "인적성", "진행중");
    await addEvent("인적성", "합격", "2026-11-03", "인적성 확인");
    await state(page, "1차면접", "진행중");
    await addEvent("1차면접", "불합격", "2026-11-04", "면접 확인");
    await state(page, "1차면접", "불합격");
    await statsMatch("불합격", "1차면접");
    await page.getByRole("row").filter({ hasText: "면접 확인" }).getByRole("button", { name: "수정", exact: true }).click();
    await expect(page.getByRole("heading", { name: "기록 수정", exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "수정 결과", exact: true }).selectOption("대기");
    await page.getByLabel("수정 메모", { exact: true }).fill("면접 결과 정정");
    await page.getByRole("button", { name: "기록 수정 저장", exact: true }).click();
    await state(page, "1차면접", "진행중");
    await expect(page.getByRole("cell", { name: "면접 결과 정정", exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "현재 단계", exact: true }).selectOption("2차면접");
    await page.getByRole("combobox", { name: "상태", exact: true }).selectOption("보류");
    await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
    await state(page, "2차면접", "보류");
    await expect(page.getByText("수동으로 정한 단계와 상태를 유지합니다.", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "1차면접 2026-11-04 기록 삭제", exact: true }).click();
    await expect(page.getByRole("cell", { name: "면접 결과 정정", exact: true })).toHaveCount(0);
    await state(page, "2차면접", "보류");
    await statsMatch("보류", "2차면접");
    await page.getByRole("button", { name: "기록으로 현재 상태 계산", exact: true }).click();
    await state(page, "1차면접", "진행중");
    await expect(page.getByText("기록 날짜 순서로 현재 단계와 상태를 계산합니다.", { exact: false })).toBeVisible();
    await statsMatch("진행중", "1차면접");
  });

  let sessionId = "";
  let snapshot: InterviewContext;
  await test.step("E: link from Track, choose confirmed basis and start free practice", async () => {
    await page.getByRole("button", { name: "이 지원 건으로 면접 질문 만들기", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "이번 연습에 연결할 지원 건", exact: true })).toHaveValue(applicationId);
    await page.getByRole("combobox", { name: "자소서 기준", exact: true }).selectOption("submitted");
    await expect(page.getByTestId("practice-context-preview")).toContainText("지원 동기 · v1 · 제출본 · 확인됨");
    await page.getByRole("checkbox", { name: /^질문 선택:/ }).first().check();
    await page.getByRole("button", { name: "선택한 질문으로 자유 연습", exact: true }).click();
    await expect(page).toHaveURL(/\/practice\/sessions\/[\w-]+\/run$/);
    sessionId = new URL(page.url()).pathname.split("/")[3];
    await expect(page.getByRole("heading", { name: "이번 면접의 기준 자료", exact: true })).toBeVisible();
    const response = await request.get(`${API}/practice/sessions/${sessionId}`);
    expect(response.ok()).toBeTruthy();
    snapshot = (await response.json()).context_snapshot;
    expect(snapshot.essay_basis).toBe("submitted");
    expect(snapshot.essays).toHaveLength(3);
    expect(snapshot.essays?.find((e) => e.question_text === essays[0].question)).toMatchObject({
      version_no: 1, content: essays[0].answer, selection: "submitted", submission_confirmation: "confirmed",
    });
  });

  await test.step("F: later Track edits and confirmation leave the existing session unchanged", async () => {
    await page.goto(applicationPath);
    await first.getByRole("textbox").fill("연습 시작 뒤 수정한 별도의 내용입니다.");
    await first.getByRole("button", { name: "제출본으로 저장", exact: true }).click();
    await expect(first.locator(".version-list button")).toHaveCount(5);
    await expect(first.getByText("최근 확인한 제출본: v5", { exact: true })).toBeVisible();
    await page.getByLabel("회사", { exact: true }).fill(`${company} 수정`);
    await page.getByRole("button", { name: "기본 정보 저장", exact: true }).click();
    await expect(page.getByRole("heading", { name: `${company} 수정 · ${position}`, exact: true })).toBeVisible();
    const applicationResponse = await request.get(`${API}/track/applications/${applicationId}`);
    expect(applicationResponse.ok()).toBeTruthy();
    const detail: ApplicationDetail = await applicationResponse.json();
    const item = detail.essay_items.find((e) => e.question_text === essays[0].question)!;
    expect(item.versions).toHaveLength(5);
    expect(item.versions[0].content).toBe(essays[0].answer);
    expect(item.versions[2].content).toBe(essays[0].answer);
    expect(item.versions[2].id).not.toBe(item.versions[0].id);
    expect(item.submitted_version_id).toBe(item.versions[4].id);
    const after = await (await request.get(`${API}/practice/sessions/${sessionId}`)).json();
    expect(after.context_snapshot).toEqual(snapshot!);
    await page.goto(`/practice/sessions/${sessionId}/run`);
    const sources = page.locator(".source-context");
    await expect(sources).toContainText(`${company} · ${position}`);
    await sources.locator("summary").filter({ hasText: essays[0].question }).click();
    await expect(sources.getByText(essays[0].answer, { exact: true })).toBeVisible();
    await expect(sources).not.toContainText("연습 시작 뒤 수정한 별도의 내용입니다.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await testInfo.attach("track-practice-ui-flow.json", { contentType: "application/json", body: JSON.stringify({
      applicationId, sessionId, snapshot: snapshot!, finalSubmittedVersionId: item.submitted_version_id,
      externalServices: "disabled", viewport: testInfo.project.name,
    }, null, 2) });
  });
});
