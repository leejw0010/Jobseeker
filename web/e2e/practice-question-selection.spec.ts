import { expect, test } from '@playwright/test';
import { API } from './env';

test('linked practice offers compatible questions and resets selection when the application changes', async ({ page, request }) => {
  const suffix = `${test.info().project.name}-${Date.now()}`;
  const applications = [];
  const linkedQuestions = [];
  for (const name of ['기준 A', '기준 B']) {
    const response = await request.post(`${API}/track/applications`, { data: { company: `${name} ${suffix}`, position: '제품 개발자' } });
    expect(response.status()).toBe(201);
    const application = await response.json();
    applications.push(application);
    const generated = await request.post(`${API}/practice/questions/generate`, { data: { application_id: application.id, count: 1 } });
    expect(generated.status()).toBe(201);
    const questions = await generated.json();
    expect(questions).toHaveLength(1);
    linkedQuestions.push(questions[0]);
  }
  const unlinked = await (await request.post(`${API}/practice/questions`, { data: { category: '직무', text: `공통 선택 ${suffix}` } })).json();
  const choice = (text: string) => page.getByRole('checkbox', { name: `질문 선택: ${text}`, exact: true });
  const start = page.getByRole('button', { name: '선택한 질문으로 자유 연습', exact: true });

  await page.goto(`/practice?application=${applications[0].id}`);
  await expect(choice(linkedQuestions[0].text)).toBeVisible();
  await expect(choice(unlinked.text)).toBeVisible();
  await expect(choice(linkedQuestions[1].text)).toHaveCount(0);
  await choice(linkedQuestions[0].text).check();
  await expect(start).toBeEnabled();

  await page.getByLabel('이번 연습에 연결할 지원 건').selectOption(applications[1].id);
  await expect(choice(linkedQuestions[0].text)).toHaveCount(0);
  await expect(choice(linkedQuestions[1].text)).toBeVisible();
  await expect(start).toBeDisabled();
  await choice(linkedQuestions[1].text).check();
  await expect(start).toBeEnabled();

  await page.getByLabel('이번 연습에 연결할 지원 건').selectOption('');
  await expect(choice(linkedQuestions[0].text)).toBeVisible();
  await expect(choice(linkedQuestions[1].text)).toBeVisible();
  await expect(start).toBeDisabled();
  await page.getByLabel('이번 연습에 연결할 지원 건').selectOption(applications[1].id);
  await choice(linkedQuestions[1].text).check();
  const created = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/practice/sessions'));
  await start.click();
  const response = await created;
  expect(response.status()).toBe(201);
  const session = await response.json();
  await expect(page).toHaveURL(new RegExp(`/practice/sessions/${session.id}/run$`));
  expect(session.application_id).toBe(applications[1].id);
  expect(session.answers.map((answer: { question: { id: string } }) => answer.question.id)).toEqual([linkedQuestions[1].id]);
});

test('the shared application source cannot change while question generation is saving', async ({ page, request }) => {
  const response = await request.post(`${API}/track/applications`, { data: { company: `대기 기준 ${test.info().project.name} ${Date.now()}`, position: '제품 개발자' } });
  const application = await response.json();
  const question = await (await request.post(`${API}/practice/questions`, { data: { category: '직무', text: `동시 삭제 확인 ${test.info().project.name} ${Date.now()}` } })).json();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let entered!: () => void;
  const pending = new Promise<void>(resolve => { entered = resolve; });
  await page.route('**/practice/questions/generate', async route => {
    entered();
    await gate;
    await route.continue();
  });
  await page.goto(`/practice?application=${application.id}`);
  const source = page.getByLabel('이번 연습에 연결할 지원 건');
  const row = page.locator('.qlist li').filter({ has: page.getByRole('checkbox', { name: `질문 선택: ${question.text}`, exact: true }) });
  const remove = row.getByRole('button', { name: '삭제', exact: true });
  await expect(source).toHaveValue(application.id);
  await page.getByRole('button', { name: '질문 생성', exact: true }).click();
  await pending;
  try {
    await expect(source).toBeDisabled();
    const deletion = page.waitForResponse(result => result.request().method() === 'DELETE' && result.url().endsWith(`/practice/questions/${question.id}`), { timeout: 750 }).catch(() => null);
    // Native click must not start a second writer while generation owns the source.
    await remove.evaluate(element => (element as HTMLButtonElement).click());
    expect(await deletion).toBeNull();
    await expect(remove).toBeDisabled();
    await expect(source).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByRole('button', { name: '질문 생성', exact: true })).toBeEnabled();
  await expect(source).toBeEnabled();
  await expect(source).toHaveValue(application.id);
  const questions = await (await request.get(`${API}/practice/questions`)).json();
  expect(questions.some((item: { id: string }) => item.id === question.id)).toBe(true);
  await expect(page.getByRole('button', { name: '선택한 질문으로 자유 연습', exact: true })).toBeEnabled();
});
