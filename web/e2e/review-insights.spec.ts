import { expect, test, type APIRequestContext } from "@playwright/test";
import { API } from "./env";

// 회고 한눈에 보기(R1): 세션 상세 값만으로 그린 그래프와 규칙 보완점. 외부 서비스를 부르지 않는다
const LONG_Q = "지금까지 경험한 프로젝트 가운데 가장 어려웠던 순간을 하나 고르고, 그때 팀과 본인이 각각 어떤 판단을 했으며 결과가 어땠는지 아주 자세하게 설명해 주세요".repeat(2);
const TEAM = "우리 팀은 서비스 응답 속도를 개선하기 위해 캐시 구조를 바꾸고 배포 과정을 다시 설계해서 결과적으로 사용자 불만을 크게 줄였습니다";

async function session(request: APIRequestContext, texts: string[]) {
  const ids = [];
  for (const text of texts)
    ids.push((await (await request.post(`${API}/practice/questions`, { data: { category: "인성", text: `${text} ${Date.now()}-${Math.random()}` } })).json()).id);
  const s = await (await request.post(`${API}/practice/sessions`, { data: { mode: "free", question_ids: ids, prep_sec: 0, answer_sec: 60 } })).json();
  return s as { id: string; answers: { id: string; order_no: number }[] };
}

test("typed answers: status grid, rule-based points with answer links, and reasons instead of empty charts", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const s = await session(request, [LONG_Q, "본인의 강점은 무엇인가요?"]);
  const [a1, a2] = [...s.answers].sort((x, y) => x.order_no - y.order_no);
  await request.patch(`${API}/practice/answers/${a1.id}`, { data: { transcript: TEAM, self_rating: 2 } });
  await request.patch(`${API}/practice/answers/${a2.id}`, { data: { transcript: "제가 맡은 일을 끝까지 책임지는 편입니다.", self_rating: 4 } });
  await request.post(`${API}/practice/answers/${a1.id}/coach`); // 키가 없으니 기본 점검(모두 판단유보)

  await page.goto(`/practice/sessions/${s.id}`);
  const card = page.locator("section.insights");
  await expect(card.getByRole("heading", { name: "한눈에 보기" })).toBeVisible();

  const grid = card.getByRole("table", { name: "답변별 코칭 점검 상태" });
  await expect(grid.getByRole("row").filter({ hasText: "Q1" })).toContainText("–판단유보");
  await expect(grid.getByRole("row").filter({ hasText: "Q2" })).toContainText("·점검 전");

  const points = card.getByTestId("insight-points");
  const role = points.getByRole("listitem").filter({ hasText: "내가 한 일이 잘 드러나지 않아요" });
  await expect(role).toHaveCount(0); // 대명사 유무로 본인 역할을 판정하지 않는다
  await expect(points.getByRole("listitem").filter({hasText:"스스로 아쉬웠다고 평가했어요"}).getByRole("link", {name:"Q1"})).toHaveAttribute("href", `#answer-${a1.id}`);
  await expect(points.getByRole("listitem").filter({ hasText: "스스로 아쉬웠다고 평가했어요" })).toContainText("Q1 2점");
  await expect(points).not.toContainText("Q2 4점");

  await expect(card.getByText("녹음 답변이 없어 말 빠르기를 계산하지 못했어요")).toBeVisible();
  await expect(card.getByText("녹음 답변이 없어 답변 시간을 표시하지 못했어요")).toBeVisible();

  const rating = card.getByRole("figure", { name: "자기 평가" });
  await rating.getByText("표로 보기").click();
  await expect(rating.getByRole("table")).toContainText("2점");
  await expect(rating.getByRole("table")).toContainText("4점");

  // 아주 긴 질문이 있어도 화면이 옆으로 넘치지 않는다
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});

test("a session with no answers yet shows a short note instead of charts", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const s = await session(request, ["지원 동기를 말씀해 주세요."]);
  await page.goto(`/practice/sessions/${s.id}`);
  const card = page.locator("section.insights");
  await expect(card.getByText("아직 답변이 없어요")).toBeVisible();
  await expect(card.getByRole("table")).toHaveCount(0);
  expect(errors).toEqual([]);
});
