import { expect, test } from "@playwright/test";
import { API } from "./env";

test('Track links and essay editor fit the viewport and have keyboard labels', async ({ page, request }) => {
  const app = await (await request.post(`${API}/track/applications`, { data: { company: `키보드${Date.now()}`, position: '개발자' } })).json();
  await request.post(`${API}/track/applications/${app.id}/essays`, { data: { question_text: '지원 동기', content: '첫 답변' } });
  await page.goto('/track');
  await page.getByPlaceholder('회사·직무 검색').fill(app.company);
  const link = page.getByRole('link', { name: app.company, exact: true });
  await expect(link).toBeVisible();
  await link.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: `${app.company} · 개발자` })).toBeVisible();
  await expect(page.getByLabel('지원 동기 답변')).toHaveValue('첫 답변');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test('stats show applied dates and separate hold from waiting', async ({ page }) => {
  const row = { stage: '서류', reached: 3, passed: 0, failed: 0, pending: 3, hold: 1, pass_rate: null };
  await page.route((url) => url.port === '8011' && url.pathname === '/track/stats', (route) => route.fulfill({ json: {
    total: 3, status: { 진행중: 2, 보류: 1, 합격: 0, 불합격: 0 }, funnel: [row], by_job_category: [],
    monthly: [{ month: '2026-11', count: 3 }], applied_monthly: [{ month: '2026-10', count: 2 }], undated_count: 1,
  } }));
  await page.goto('/track/stats');
  await expect(page.getByText('지원일 미입력 1건')).toBeVisible();
  await expect(page.getByText('2026-10', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '표로 보기', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: '보류', exact: true })).toBeVisible();
  await expect(page.locator('tbody').first().locator('tr')).toContainText('2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test('creating an application prevents duplicate clicks and keeps failed form values', async ({ page }) => {
  let count = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/track/applications', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    count++;
    await gate;
    await route.fulfill({ status: 500, json: { detail: '생성 실패' } });
  });
  await page.goto('/track');
  await page.getByRole('button', { name: '+ 지원 건 추가' }).click();
  await page.getByLabel('회사', { exact: true }).fill('실패 후 보존');
  await page.getByLabel('직무(포지션)', { exact: true }).fill('개발');
  const save = page.getByRole('button', { name: '저장', exact: true });
  await save.click();
  await expect(save).toBeDisabled();
  expect(count).toBe(1);
  release();
  await expect(page.getByRole('alert')).toHaveText('생성 실패');
  await expect(page.getByLabel('회사', { exact: true })).toHaveValue('실패 후 보존');
  await expect(save).toBeEnabled();
});
