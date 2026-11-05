import {test,expect,type APIRequestContext,type Page} from '@playwright/test';
import {API} from './env';

async function reviewedSession(request:APIRequestContext) {
 const questions=[];
 for(let i=0;i<2;i++) questions.push(await (await request.post(`${API}/practice/questions`,{data:{category:'직무',text:`캐시 검토 질문 ${i} ${Date.now()}-${Math.random()}`}})).json());
 const s=await (await request.post(`${API}/practice/sessions`,{data:{mode:'free',question_ids:questions.map(q=>q.id)}})).json();
 for(const a of s.answers) {
  await request.patch(`${API}/practice/answers/${a.id}`,{data:{transcript:`합성 답변 ${a.order_no}에서 로그를 분류했습니다.`,self_rating:1}});
  await request.post(`${API}/practice/answers/${a.id}/coach`);
 }
 const saved=await (await request.get(`${API}/practice/sessions/${s.id}`)).json();
 return {...saved,debrief_status:'done',debrief:{lesson:'변경 전 세션의 오래된 해석',next_action:'변경 전 다음 행동',moments:[]}};
}

async function routeSession(page:Page,s:Awaited<ReturnType<typeof reviewedSession>>,options:{fail?:boolean}={}) {
 await page.route(`**/practice/sessions/${s.id}`,async route=>{
  if(route.request().resourceType()==='document') return route.continue();
  if(options.fail) return route.fulfill({status:503,json:{detail:'합성 세션 새로고침 실패'}});
  return route.fulfill({json:s});
 });
}

test('Track source omits hidden direct inputs from question generation requests',async({page,request})=>{
 const app=await (await request.post(`${API}/track/applications`,{data:{company:'선택한 Track 회사',position:'선택한 직무'}})).json();
 await page.goto('/practice');
 await page.getByLabel('회사',{exact:true}).fill('숨겨질 직접 회사');
 await page.getByLabel('직무',{exact:true}).last().fill('숨겨질 직접 직무');
 await page.getByLabel('자기소개서 내용',{exact:true}).fill('숨겨질 직접 자소서');
 await page.getByLabel('이번 연습에 연결할 지원 건').selectOption(app.id);
 const outgoing=page.waitForRequest(r=>r.method()==='POST'&&r.url().endsWith('/practice/questions/generate'));
 await page.getByRole('button',{name:'질문 생성',exact:true}).click();
 const body=(await outgoing).postDataJSON();
 expect(body.application_id).toBe(app.id);
 expect(body).not.toHaveProperty('company');
 expect(body).not.toHaveProperty('position');
 expect(body).not.toHaveProperty('essay_text');
});

test('draft pauses the entire integrated narrative and actions, and revert restores them',async({page,request})=>{
 const s=await reviewedSession(request); await routeSession(page,s);
 await page.goto(`/practice/sessions/${s.id}`);
 const integrated=page.locator('.integrated-coaching');
 await expect(integrated).toContainText('이번 연습은 답변 2개');
 const last=page.locator(`#answer-${s.answers[1].id}`);
 await last.getByLabel('전사문 (직접 고칠 수 있어요)').fill('저장하지 않은 두 번째 설명');
 await expect(integrated).not.toContainText('이번 연습은 답변 2개');
 await expect(integrated.getByRole('heading',{name:'다음 연습에서 해볼 일'})).toHaveCount(0);
 await expect(page.getByTestId('integrated-content-paused')).toBeVisible();
 await last.getByLabel('전사문 (직접 고칠 수 있어요)').fill(s.answers[1].transcript);
 await expect(integrated).toContainText('이번 연습은 답변 2개');
 await expect(page.getByTestId('integrated-content-paused')).toHaveCount(0);
});

test('successful transcript PATCH cannot restore old dependent guidance when session refresh fails',async({page,request})=>{
 const s=await reviewedSession(request); const options={fail:false}; await routeSession(page,s,options);
 await page.goto(`/practice/sessions/${s.id}`);
 const first=page.locator(`#answer-${s.answers[0].id}`); const later=page.locator(`#answer-${s.answers[1].id}`);
 await expect(later.locator('.coaching-panel')).toBeVisible();
 await first.getByLabel('전사문 (직접 고칠 수 있어요)').fill('저장한 새로운 첫 번째 설명');
 options.fail=true;
 await first.getByRole('button',{name:'저장',exact:true}).click();
 await expect(first.getByRole('button',{name:'저장',exact:true})).toBeDisabled();
 await expect(later.locator('.coaching-panel')).toHaveCount(0);
 await expect(page.locator('.integrated-coaching')).not.toContainText('변경 전 세션의 오래된 해석');
 await expect(page.locator('.weak-list')).toHaveCount(0);
 await expect(page.getByTestId('review-refresh-error')).toContainText('합성 세션 새로고침 실패');
 await expect(page.getByTestId('integrated-content-paused')).toBeVisible();
 // An explicit successful authoritative retry releases the pause; no model request.
 const fresh=await (await request.get(`${API}/practice/sessions/${s.id}`)).json();
 Object.assign(s,fresh); options.fail=false;
 await page.getByRole('button',{name:'회고 다시 불러오기',exact:true}).click();
 await expect(page.getByTestId('review-refresh-error')).toHaveCount(0);
 await expect(page.getByTestId('integrated-content-paused')).toHaveCount(0);
 await expect(later.locator('.coaching-panel')).toHaveCount(0);
});

test('notes-only save with failed refresh retains answer coaching and pauses the invalidated session summary',async({page,request})=>{
 const s=await reviewedSession(request); const options={fail:false}; await routeSession(page,s,options);
 await page.goto(`/practice/sessions/${s.id}`);
 const first=page.locator(`#answer-${s.answers[0].id}`);
 await first.getByLabel('회고 메모',{exact:true}).fill('저장한 새 회고 메모');
 options.fail=true;
 await first.getByRole('button',{name:'저장',exact:true}).click();
 await expect(page.getByTestId('review-refresh-error')).toBeVisible();
 await expect(first.locator('.coaching-panel')).toBeVisible();
 await expect(page.locator('.integrated-coaching')).not.toContainText('변경 전 세션의 오래된 해석');
 await expect(page.getByTestId('integrated-content-paused')).toBeVisible();
});

test('legacy criterion reason is retained in history but absent from current status grid tooltips',async({page,request})=>{
 const s=await reviewedSession(request);
 s.answers[0].coaching_report={...s.answers[0].coaching_report,input_status:'legacy_unverified',criteria:s.answers[0].coaching_report.criteria.map((c:Record<string,unknown>)=>({...c,reason:'이전 코칭 전용 이유'}))};
 await routeSession(page,s); await page.goto(`/practice/sessions/${s.id}`);
 const grid=page.getByRole('table',{name:'답변별 코칭 점검 상태'});
 const first=grid.getByRole('row').filter({hasText:'Q1'});
 await expect(first).toContainText('점검 전');
 expect(await first.locator('[title]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('title')))).not.toContain('이전 코칭 전용 이유');
 await expect(page.locator(`#answer-${s.answers[0].id} .coaching-panel`)).toContainText('이전 코칭 전용 이유');
});

test('a delayed authoritative GET keeps dependent coaching paused immediately after PATCH succeeds',async({page,request})=>{
 const s=await reviewedSession(request); let hold=false;
 let release=()=>{}; const barrier=new Promise<void>(resolve=>{release=resolve;});
 let markEntered=()=>{}; const entered=new Promise<void>(resolve=>{markEntered=resolve;});
 await page.route(`**/practice/sessions/${s.id}`,async route=>{
  if(route.request().resourceType()==='document') return route.continue();
  if(hold) {markEntered(); await barrier; return route.fulfill({json:await (await request.get(`${API}/practice/sessions/${s.id}`)).json()});}
  return route.fulfill({json:s});
 });
 await page.goto(`/practice/sessions/${s.id}`);
 const first=page.locator(`#answer-${s.answers[0].id}`); const later=page.locator(`#answer-${s.answers[1].id}`);
 await first.getByLabel('전사문 (직접 고칠 수 있어요)').fill('저장된 새로운 설명'); hold=true;
 try {
  await first.getByRole('button',{name:'저장',exact:true}).click(); await entered;
  await expect(later.locator('.coaching-panel')).toHaveCount(0);
  await expect(page.getByTestId('integrated-content-paused')).toBeVisible();
 } finally {release();}
 await expect(page.getByTestId('integrated-content-paused')).toHaveCount(0);
});
