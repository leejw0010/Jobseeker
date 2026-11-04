import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API, BROWSER_API } from "./env";

// 카메라 자세 분석(선택 기능). 검출기는 playwright.config.ts의 VITE_E2E_FAKE_FACE로 가짜를 쓰고, 카메라는 Chromium의 가짜 장치를 쓴다
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
  page.on("request", (r) => { if (r.url().startsWith(BROWSER_API)) sent.push(r.postData() ?? ""); });
  await watchCamera(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  const panel = page.locator(".camera-panel");
  await expect(panel).toContainText("시선 추적이 아니에요");
  await expect(panel).toContainText("얼굴을 찾지 못한 시간");
  await expect(panel).not.toContainText("화면을 벗어난");

  await panel.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.getByLabel("내 카메라 미리보기")).toBeVisible();
  await expect(panel.getByRole("status")).toContainText("얼굴");
  // 끄면 카메라를 바로 놓고, 다시 켤 수 있다
  await panel.getByRole("button", { name: "카메라 끄기" }).click();
  await expect.poll(() => liveCameraTracks(page)).toBe(0);
  await panel.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(page.getByLabel("내 카메라 미리보기")).toBeVisible();

  await page.getByRole("checkbox", {name:"실시간 자세 힌트"}).uncheck();
  await expect(panel.getByRole("status")).toHaveCount(0);
  await page.getByRole("checkbox", {name:"실시간 자세 힌트"}).check();
  const consent=page.getByRole("button",{name:"동의하고 시작"});
  if(await consent.count()) await consent.click();
  else await page.getByRole("button",{name:"답변 시작",exact:true}).click();
  await page.waitForTimeout(4000);
  await page.getByRole("button",{name:"답변 끝내기"}).click();
  await page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요").fill("팀 프로젝트에서 일정 관리를 맡았습니다.");
  await page.getByRole("button",{name:"면접 마치고 회고 보기"}).click();
  await expect(page.getByRole("heading",{name:"다음 연습으로 연결하기"})).toBeVisible();
  // 회고로 넘어가면(면접 화면을 떠나면) 카메라를 놓는다
  expect(await liveCameraTracks(page)).toBe(0);
  const card = page.locator(".video-report");
  await expect(cameraHeading(page)).toBeVisible();
  await expect(card).toContainText("얼굴 검출 비율");
  await expect(card).toContainText("얼굴을 찾지 못한 시간");
  await expect(card).toContainText("분석한 시간");
  await expect(card).not.toContainText("화면을 벗어난");
  await expect(card.locator("tbody tr")).toHaveCount(1);
  // 열: 질문 | 답변 시간 | 분석한 시간 | 얼굴 검출 | 찾지 못한 시간 | 일부 프레임 밖 | 좌우 회전 | 숙임
  await expect(card.locator("tbody tr td").nth(3)).toHaveText(/^\d+%$/);
  await expect(card.locator("tbody tr td").nth(6)).toHaveText(/^\d+%$/); // 고개 방향 기준을 잡았다
  await expect(card).not.toContainText(/자신감이|긴장한|합격 가능성이 (높|낮)/);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({colorScheme});
    const minimum = await card.evaluate(root => {
      const luminance=(value:string)=>{const rgb=(value.match(/[\d.]+/g)??[]).slice(0,3).map(Number).map(n=>n/255).map(n=>n<=0.03928?n/12.92:((n+0.055)/1.055)**2.4);return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];};
      const background=luminance(getComputedStyle(root).backgroundColor);
      return Math.min(...[...root.querySelectorAll('.muted,th')].map(el=>{const foreground=luminance(getComputedStyle(el).color);return (Math.max(foreground,background)+0.05)/(Math.min(foreground,background)+0.05);}));
    });
    expect(minimum).toBeGreaterThanOrEqual(4.5);
  }
  // 수치는 서버로 보내지 않는다. 먼저 API 요청을 실제로 모았는지(글 답변 저장) 확인한다: 비어 있으면 아래 검사는 의미가 없다
  expect(sent.some((b) => b.includes("일정 관리를 맡았습니다"))).toBe(true);
  expect(sent.filter((b) => /detectedMs|noneMs|edgeMs|turnedMs|yaw|pitch|overshoot/.test(b))).toEqual([]);
  await expect(page.locator('.integrated-coaching')).toContainText('브라우저 카메라 표본');
  await card.getByRole('button',{name:'이 결과 지우기'}).click();
  await expect(page.locator('.integrated-coaching')).not.toContainText('브라우저 카메라 표본');
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

test("edge-top: face partly outside is shown as detected, not as not-found", async ({ page, request }) => {
  // 이마 위만 프레임 밖이고 눈·코·입은 안에 있는 얼굴(가까이 앉은 경우)
  await page.addInitScript(() => localStorage.setItem("e2e-face-detector", "edge-top"));
  await watchCamera(page);
  const session = await seed(request);
  await page.goto(`/practice/sessions/${session.id}/run`);
  const panel = page.locator(".camera-panel");
  await panel.getByRole("button", { name: "동의하고 카메라 켜기" }).click();
  await expect(panel.getByRole("status")).toHaveText("얼굴 위쪽이 화면 밖에 있어요");
  // 미리보기는 분석 프레임 전체를 보여 주고(contain), 좌우 반전은 그대로다
  const preview = page.getByLabel("내 카메라 미리보기");
  expect(await preview.evaluate((el) => getComputedStyle(el).objectFit)).toBe("contain");
  expect(await preview.evaluate((el) => getComputedStyle(el).transform)).toMatch(/^matrix\(-1,/);

  const consent=page.getByRole("button",{name:"동의하고 시작"});
  if(await consent.count()) await consent.click();
  else await page.getByRole("button",{name:"답변 시작",exact:true}).click();
  await page.waitForTimeout(1500);
  await page.getByRole("button",{name:"답변 끝내기"}).click();
  await page.getByLabel("답변 확인 · 전사문을 고칠 수 있어요").fill("팀 프로젝트에서 일정 관리를 맡았습니다.");
  await page.getByRole("button",{name:"면접 마치고 회고 보기"}).click();
  const row = page.locator(".video-report tbody tr td");
  await expect(row.nth(3)).toHaveText("100%"); // 얼굴 검출
  await expect(row.nth(4)).toHaveText("0초"); // 찾지 못한 시간
  await expect(row.nth(5)).not.toHaveText("0초"); // 일부 프레임 밖
  await expect(page.locator(".video-report")).not.toContainText("화면을 벗어난");
});

test("typed answers never receive camera or voice reports", async ({page,request}) => {
 const session=await seed(request); await page.goto(`/practice/sessions/${session.id}/run`);
 await page.getByRole("button",{name:"동의하고 카메라 켜기"}).click();
 await answerByTextAndFinish(page,1500);
 await expect(page.locator(".video-report")).toHaveCount(0);
 await expect(page.getByRole("heading",{name:"음성 전달 관찰"})).toHaveCount(0);
});

test("failed recording uploads never publish camera or voice reports", async ({page,request})=>{
 const session=await seed(request);
 await page.goto(`/practice/sessions/${session.id}/run`);
 await page.getByRole("button",{name:"동의하고 카메라 켜기"}).click();
 const consent=page.getByRole("button",{name:"동의하고 시작"});
 if(await consent.count()) await consent.click(); else await page.getByRole("button",{name:"답변 시작",exact:true}).click();
 await page.waitForTimeout(1200);
 await page.route("**/practice/answers/*/audio",route=>route.fulfill({status:503,json:{detail:"테스트 저장 실패"}}));
 await page.getByRole("button",{name:"답변 끝내기"}).click();
 await expect(page.getByRole("alert")).toContainText("테스트 저장 실패");
 await page.getByRole("link",{name:"지금까지 저장한 답변 보기"}).click();
 await expect(page.getByRole("heading",{name:"통합 코칭"})).toBeVisible();
 await expect(page.locator(".video-report")).toHaveCount(0);
 await expect(page.getByRole("heading",{name:"음성 전달 관찰"})).toHaveCount(0);
});
