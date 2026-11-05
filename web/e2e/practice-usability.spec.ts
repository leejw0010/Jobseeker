import { test, expect } from '@playwright/test';
import { API } from './env';

test('one shared application source previews the context for both modes and names question selection', async ({page,request})=>{
 const app=await (await request.post(`${API}/track/applications`,{data:{company:'공통 기준 회사',position:'제품 개발'}})).json();
 const q=await (await request.post(`${API}/practice/questions`,{data:{category:'직무',text:`기준 확인 질문 ${Date.now()}`}})).json();
 await page.goto('/practice');
 await page.getByLabel('이번 연습에 연결할 지원 건').selectOption(app.id);
 await expect(page.getByTestId('practice-context-preview')).toContainText('공통 기준 회사');
 await expect(page.getByTestId('practice-context-preview')).toContainText('제품 개발');
 await page.getByRole('checkbox',{name:`질문 선택: ${q.text}`,exact:true}).check();
 await page.getByRole('button',{name:'선택한 질문으로 자유 연습'}).click();
 await expect(page.getByRole('heading',{name:'이번 면접의 기준 자료'})).toBeVisible();
 const sid=page.url().split('/').at(-2);
 const session=await (await request.get(`${API}/practice/sessions/${sid}`)).json();
 expect(session.application_id).toBe(app.id);
 expect(session.context_snapshot.company).toBe('공통 기준 회사');
});

test('unsaved transcript pauses dependent coaching while notes preserve it and rating exposes checked state', async ({page,request})=>{
 const q=await (await request.post(`${API}/practice/questions`,{data:{category:'직무',text:`초안 확인 질문 ${Date.now()}`}})).json();
 const s=await (await request.post(`${API}/practice/sessions`,{data:{mode:'free',question_ids:[q.id]}})).json();
 const a=s.answers[0];
 await request.patch(`${API}/practice/answers/${a.id}`,{data:{transcript:'실제 장애 로그를 분류하고 배포 점검표를 작성했습니다.'}});
 await request.post(`${API}/practice/answers/${a.id}/coach`);
 await page.goto(`/practice/sessions/${s.id}`);
 const card=page.locator(`#answer-${a.id}`);
 await expect(card.locator('.coaching-panel')).toBeVisible();
 await card.getByLabel('회고 메모').fill('다음에 다시 확인');
 await expect(card.locator('.coaching-panel')).toBeVisible();
 await expect(page.getByTestId('unsaved-transcript')).toHaveCount(0);
 await card.getByLabel('전사문 (직접 고칠 수 있어요)').fill('아직 저장하지 않은 새 답변');
 await expect(page.getByTestId('unsaved-transcript')).toBeVisible();
 await expect(card.locator('.coaching-panel')).toHaveCount(0);
 await expect(card.getByText('내 답변으로 개선 틀 만들기',{exact:true})).toHaveCount(0);
 await card.getByRole('button',{name:'저장',exact:true}).click();
 await card.getByRole('radio',{name:'4점',exact:true}).click();
 await expect(card.getByRole('radio',{name:'4점',exact:true})).toBeChecked();
 await expect(card.getByRole('radio',{name:'3점',exact:true})).not.toBeChecked();
 await card.getByRole('radio',{name:'4점',exact:true}).focus();
 await page.keyboard.press('ArrowRight');
 await expect(card.getByRole('radio',{name:'5점',exact:true})).toBeChecked();
 await expect(card.getByRole('radio',{name:'5점',exact:true})).toBeFocused();
});


test('frozen submitted source distinguishes confirmed, legacy, and missing confirmation records',async({page,request})=>{
 const q=await (await request.post(`${API}/practice/questions`,{data:{category:'인성',text:`자료 확인 ${Date.now()}`}})).json();
 const s=await (await request.post(`${API}/practice/sessions`,{data:{mode:'free',question_ids:[q.id]}})).json();
 const essay={item_id:'i',version_id:'v',question_text:'자료 상태',version_no:1,content:'합성 자소서',selection:'submitted',is_submitted:true};
 for(const [status,label] of [['confirmed','제출본 · 확인됨'],['legacy_unverified','이전 제출 표시 · 확인 전'],[undefined,'제출본 · 확인 기록 없음']] as const) {
  await page.route(`**/practice/sessions/${s.id}`,route=>route.request().resourceType()==='document' ? route.continue() : route.fulfill({json:{...s,context_snapshot:{company:'합성 회사',position:'합성 직무',essay_basis:'submitted',job_description:'',essays:[{...essay,submission_confirmation:status}]}}}));
  await page.goto(`/practice/sessions/${s.id}`);
  await expect(page.locator('.source-detail summary').filter({hasText:'자료 상태'})).toContainText(label);
  await page.unroute(`**/practice/sessions/${s.id}`);
 }
});

test('a later draft cannot request coaching until the earlier draft is saved',async({page,request})=>{
 const questions=[];
 for(let i=0;i<2;i++) questions.push(await (await request.post(`${API}/practice/questions`,{data:{category:'직무',text:`앞선 초안 확인 ${i} ${Date.now()}`}})).json());
 const s=await (await request.post(`${API}/practice/sessions`,{data:{mode:'free',question_ids:questions.map(q=>q.id)}})).json();
 for(const a of s.answers) await request.patch(`${API}/practice/answers/${a.id}`,{data:{transcript:'합성 예시에서 로그를 분류했습니다.'}});
 await page.goto(`/practice/sessions/${s.id}`);
 const first=page.locator(`#answer-${s.answers[0].id}`); const later=page.locator(`#answer-${s.answers[1].id}`);
 await first.getByLabel('전사문 (직접 고칠 수 있어요)').fill('아직 저장하지 않은 앞선 설명');
 await later.getByLabel('전사문 (직접 고칠 수 있어요)').fill('아직 저장하지 않은 나중 설명');
 await expect(later.getByRole('button',{name:'답변 점검',exact:true})).toBeDisabled();
 await first.getByRole('button',{name:'저장',exact:true}).click();
 await expect(later.getByRole('button',{name:'답변 점검',exact:true})).toBeEnabled();
});
