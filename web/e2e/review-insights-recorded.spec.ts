import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

// 회고 한눈에 보기(R1) — 녹음 답변이 있는 모의시험 세션. 카메라·마이크 없이 API로 고정된 데이터를 만든다:
// 녹음 파일은 의미 없는 바이트로 올리고(e2e는 STT_PROVIDER=off라 전사하지 않음) 녹음 길이는 업로드 값으로 정한다.
// 전사문은 직접 넣고, 코칭은 키가 없는 기본 점검(자소서에 수치가 있고 답변에 없으면 구체성 '보완')이다.
// 아래 기대값(음절 수·분당 음절·막대 비율)은 구현과 따로 손으로 계산한 값이다.
const API = "http://127.0.0.1:8011";

const ANSWERS = [
  { // Q1: 134음절 / 59.6초 → 분당 135, 제한 60초를 다 씀
    sec: 59.6, rating: 3,
    text: "제가 맡은 일은 주문 서버의 응답이 느려지는 원인을 찾는 것이었습니다 로그를 하나씩 따라가며 병목이 생기는 구간을 직접 확인했고 캐시를 넣어 문제를 풀었습니다 제가 맡은 일은 주문 서버의 응답이 느려지는 원인을 찾는 것이었습니다 로그를 하나씩 따라가며 병목이 생기는 구간을 직접 확인했고 캐시를 넣어 문제를 풀었습니다",
  },
  { // Q2: 37음절 / 18초 → 분당 123, 제한의 30%(짧음), 자기 평가 2점
    sec: 18, rating: 2,
    text: "제가 먼저 대화를 요청해서 서로가 중요하게 여기는 기준을 맞추고 일정을 다시 나눴습니다",
  },
  { // Q3: 55음절 / 45초 → 분당 73(평균보다 느림), 역할 표현 없음
    sec: 45, rating: 4,
    text: "우리 팀은 서비스 응답 속도를 개선하기 위해 캐시 구조를 바꾸고 배포 과정을 다시 설계해서 결과적으로 사용자 불만을 크게 줄였습니다",
  },
  { // Q4: 94음절 / 30초 → 분당 188(평균보다 빠름)
    sec: 30, rating: 5,
    text: "제가 처음 맡은 배포에서 설정을 빠뜨리는 실수를 했고 그 뒤로 점검표를 만들어 매번 확인했습니다 그 덕분에 같은 문제가 다시 생기지 않았고 팀 전체가 점검표를 쓰게 되었습니다 저는 작은 습관이 큰 사고를 막는다는 것을 배웠습니다",
  },
  { // Q5: 글로 답함(녹음 없음), 수치가 있어 기본 점검은 판단유보
    sec: null, rating: null,
    text: "제가 3년 안에 결제 시스템을 맡을 수 있도록 성장하겠습니다",
  },
] as const;
// 세션 평균 = (135 + 123 + 73 + 188) / 4 = 129.75 → 화면에는 130

async function seed(request: APIRequestContext) {
  await request.put(`${API}/practice/settings`, { data: { consent: true } });
  const app = await (await request.post(`${API}/track/applications`, { data: { company: "녹음 회고 검증", position: "백엔드 개발자", job_category: "개발" } })).json();
  const item = await (await request.post(`${API}/track/applications/${app.id}/essays`, { data: {
    question_text: "성과 경험", content: "캐시를 도입하여 응답 시간을 40% 개선했습니다.",
  } })).json();
  await request.post(`${API}/track/essays/${item.id}/versions`, { data: { content: item.versions[0].content, is_submitted: true } });
  const ids: string[] = [];
  for (let i = 0; i < ANSWERS.length; i++)
    ids.push((await (await request.post(`${API}/practice/questions`, { data: { category: "인성", text: `녹음 회고 질문 ${i + 1} ${Date.now()}-${Math.random()}` } })).json()).id);
  const s = await (await request.post(`${API}/practice/sessions`, { data: {
    mode: "mock", application_id: app.id, question_ids: ids, prep_sec: 0, answer_sec: 60,
  } })).json();
  const answers: { id: string; order_no: number }[] = [...s.answers].sort((a, b) => a.order_no - b.order_no);
  for (let i = 0; i < ANSWERS.length; i++) {
    const a = ANSWERS[i];
    const id = answers[i].id;
    if (a.sec != null) {
      const up = await request.post(`${API}/practice/answers/${id}/audio`, {
        multipart: { file: { name: "rec.webm", mimeType: "audio/webm", buffer: Buffer.from("not-real-audio") }, duration_sec: String(a.sec) },
      });
      expect(up.ok()).toBe(true);
    }
    expect((await request.patch(`${API}/practice/answers/${id}`, { data: { transcript: a.text, self_rating: a.rating } })).ok()).toBe(true);
    expect((await request.post(`${API}/practice/answers/${id}/coach`)).ok()).toBe(true);
  }
  return { sessionId: s.id as string, answerIds: answers.map((a) => a.id) };
}

/** 막대 한 줄: 라벨·값·막대 너비(%) */
async function bars(fig: Locator) {
  return fig.locator(".bar-row").evaluateAll((rows) => rows.map((r) => ({
    label: r.querySelector(".bar-label")?.textContent,
    value: r.querySelector(".bar-value")?.textContent,
    width: Number.parseFloat((r.querySelector(".bar-fill") as HTMLElement).style.width),
  })));
}
const refLeft = (fig: Locator) => fig.locator(".bar-ref").first().evaluate((el) => Number.parseFloat((el as HTMLElement).style.left));
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

let seeded: { sessionId: string; answerIds: string[] };
test.beforeEach(async ({ request }) => {
  seeded = await seed(request);
});
test.afterEach(async ({ request }) => {
  // 이 테스트가 올린 녹음은 세션과 함께 지우고, 다른 테스트처럼 동의 없는 상태로 돌려 둔다
  await request.delete(`${API}/practice/sessions/${seeded.sessionId}`);
  await request.put(`${API}/practice/settings`, { data: { consent: false } });
});

test("recorded mock session: time, speech-rate and rating bars match hand-computed values", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/practice/sessions/${seeded.sessionId}`);
  const card = page.locator("section.insights");
  await expect(card.getByRole("heading", { name: "한눈에 보기" })).toBeVisible();

  const time = card.getByRole("figure", { name: "답변 시간" });
  await expect(time).toContainText("제한 60초");
  const t = await bars(time);
  expect(t.map((b) => [b.label, b.value])).toEqual([["Q1", "60초"], ["Q2", "18초"], ["Q3", "45초"], ["Q4", "30초"]]);
  expect(t[0].width).toBeCloseTo(99.333, 2); // 59.6 / 60
  expect(t[1].width).toBeCloseTo(30, 5); // 18 / 60
  expect(await refLeft(time)).toBeCloseTo(100, 5); // 제한 선은 축 끝(제한이 가장 큰 값)

  const speed = card.getByRole("figure", { name: "말 빠르기(분당 음절)" });
  await expect(speed).toContainText("이 세션 평균 130");
  await expect(speed).toContainText("앞뒤 침묵이 들어 있어요");
  const s = await bars(speed);
  expect(s.map((b) => [b.label, b.value])).toEqual([["Q1", "135"], ["Q2", "123"], ["Q3", "73"], ["Q4", "188"]]);
  expect(s[3].width).toBeCloseTo(100, 5);
  expect(s[2].width).toBeCloseTo((73 / 188) * 100, 2);
  expect(await refLeft(speed)).toBeCloseTo((129.75 / 188) * 100, 2);
  // 막대 위에 올리면 값이 보인다(SVG가 아닌 HTML title)
  await expect(speed.locator(".bar-row").nth(3)).toHaveAttribute("title", "Q4 · 분당 188음절 (평균 130)");

  const rating = card.getByRole("figure", { name: "자기 평가" });
  const r = await bars(rating);
  expect(r.map((b) => [b.label, b.value, b.width])).toEqual([["Q1", "3점", 60], ["Q2", "2점", 40], ["Q3", "4점", 80], ["Q4", "5점", 100]]);

  // 표로 보기: 그래프와 같은 값
  await speed.getByText("표로 보기").click();
  await expect(speed.getByRole("table").locator("tbody tr")).toHaveText(["Q1135", "Q2123", "Q373", "Q4188"]);

  const grid = card.getByRole("table", { name: "답변별 코칭 점검 상태" });
  for (const q of ["Q1", "Q2", "Q3", "Q4"]) await expect(grid.getByRole("row").filter({ hasText: q }).getByRole("cell").first()).toHaveText("!보완");
  await expect(grid.getByRole("row").filter({ hasText: "Q5" }).getByRole("cell").first()).toHaveText("–판단유보");

  expect(await noOverflow(page)).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});

test("recorded mock session: improvement points in rule order, folded after five, with evidence", async ({ page }) => {
  await page.goto(`/practice/sessions/${seeded.sessionId}`);
  const points = page.getByTestId("insight-points");
  const shown = points.locator(":scope > ol > li");
  await expect(shown.locator("strong")).toHaveText([
    "구체성 보완", "제한 시간을 다 썼어요", "제한 시간보다 많이 짧았어요", "평소보다 빠르게 말했어요", "평소보다 느리게 말했어요",
  ]);
  const coaching = shown.nth(0);
  await expect(coaching).toContainText("코칭 결과");
  await expect(coaching).toContainText("(외 3개 답변)");
  await expect(coaching.locator("blockquote")).toHaveCount(2); // 인용은 두 답변까지
  await expect(coaching).toContainText("개선 전후의 측정 지표와 비교 조건을 설명해 주세요."); // 보고서의 다음 행동
  await expect(shown.nth(1)).toContainText("Q1 60초 / 제한 60초");
  await expect(shown.nth(2)).toContainText("Q2 18초(30%) / 제한 60초");
  await expect(shown.nth(3)).toContainText("Q4 분당 188음절 · 이 세션 평균 130음절");
  await expect(shown.nth(4)).toContainText("Q3 분당 73음절");

  const more = points.locator("details");
  await expect(more.locator("summary")).toHaveText("보완점 1개 더 보기");
  await more.locator("summary").click();
  await expect(more.locator("li strong")).toHaveText(["스스로 아쉬웠다고 평가했어요"]);
  await expect(more.locator("li").nth(0)).toContainText("Q2 2점");
});

test("clicking an improvement point's answer link moves to that answer card", async ({ page }) => {
  await page.goto(`/practice/sessions/${seeded.sessionId}`);
  const role = page.getByTestId("insight-points").getByRole("listitem").filter({ hasText: "평소보다 느리게 말했어요" });
  await role.getByRole("link", { name: "Q3" }).click();
  const target = `answer-${seeded.answerIds[2]}`;
  await expect(page).toHaveURL(new RegExp(`#${target}$`));
  const cardEl = page.locator(`#${target}`);
  await expect(cardEl).toBeInViewport();
  await expect(cardEl.getByRole("heading", { level: 3 })).toContainText("Q3.");
  await expect(cardEl.getByLabel("전사문 (직접 고칠 수 있어요)")).toHaveValue(ANSWERS[2].text);
});

test("keyboard: grid links are in tab order, Enter follows a point link, and the table view opens with Enter", async ({ page }) => {
  await page.goto(`/practice/sessions/${seeded.sessionId}`);
  const grid = page.getByRole("table", { name: "답변별 코칭 점검 상태" });
  await grid.getByRole("link", { name: "Q1" }).focus();
  await page.keyboard.press("Tab");
  await expect(grid.getByRole("link", { name: "Q2" })).toBeFocused();

  const time = page.getByRole("figure", { name: "답변 시간" });
  const summary = time.locator("summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(time.getByRole("table")).toBeVisible();
  await expect(time.getByRole("table").locator("tbody tr")).toHaveText(["Q160초", "Q218초", "Q345초", "Q430초"]);

  const over = page.getByTestId("insight-points").getByRole("listitem").filter({ hasText: "제한 시간을 다 썼어요" });
  await over.getByRole("link", { name: "Q1" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`#answer-${seeded.answerIds[0]}$`));
  await expect(page.locator(`#answer-${seeded.answerIds[0]}`)).toBeInViewport();
});

test("card text meets 4.5:1 contrast against the card in light and dark", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/practice/sessions/${seeded.sessionId}`);
    const card = page.locator("section.insights");
    await expect(card.getByRole("heading", { name: "한눈에 보기" })).toBeVisible();
    // 근거·기준선 이름·안내 문장(.muted)과 막대 값·라벨까지, 카드 안의 글자 색 대비를 잰다(WCAG AA 일반 글자 4.5:1)
    const worst = await card.evaluate((root) => {
      const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
      const lum = (c: string) => {
        const [r, g, b] = rgb(c).map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const bg = lum(getComputedStyle(root).backgroundColor);
      const found: { text: string; ratio: number }[] = [];
      for (const el of root.querySelectorAll<HTMLElement>(".muted, .bar-label, .bar-value, .viz-key, .st")) {
        const fg = lum(getComputedStyle(el).color);
        const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
        found.push({ text: (el.textContent ?? "").slice(0, 20), ratio: Math.round(ratio * 100) / 100 });
      }
      return found.sort((a, b) => a.ratio - b.ratio)[0];
    });
    expect(worst.ratio, `${scheme}: "${worst.text}"`).toBeGreaterThanOrEqual(4.5);
  }
});
