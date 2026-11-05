import { expect, test } from '@playwright/test';
import { API } from './env';
test('classification controls, frozen review and accessible competency history', async ({page,request}) => {
 const observed:{method:string;path:string}[]=[];
 page.on('request',r=>{const u=new URL(r.url());if(u.pathname.startsWith('/practice/'))observed.push({method:r.method(),path:u.pathname});});
 const taxonomy=await (await request.get(`${API}/practice/taxonomy`)).json();
 test.skip(!taxonomy.enabled,'taxonomy schema is disabled');
 const q=await (await request.post(`${API}/practice/questions`,{data:{category:'인성',text:`분류 접근성 질문 ${Date.now()}`}})).json();
 await page.goto('/practice');
 const row=page.locator('.qlist li').filter({hasText:q.text});
 await row.getByRole('button',{name:'분류 편집'}).click();
 await row.getByLabel('질문 유형').selectOption(taxonomy.question_types[0].key);
 await row.getByLabel(taxonomy.competencies[0].label,{exact:true}).check();
 await row.getByRole('button',{name:'분류 저장'}).click();
 await expect(row).toContainText(taxonomy.question_types[0].label);
 await row.getByRole('checkbox',{name:`질문 선택: ${q.text}`,exact:true}).check();
 await page.getByRole('button',{name:'선택한 질문으로 자유 연습'}).click();
 await expect(page.getByText('시작 시점 분류',{exact:true})).toBeVisible();
 await page.getByRole('radio',{name:'글로 답변',exact:true}).check();
 await page.getByRole('button',{name:'답변 시작',exact:true}).click();
 await page.getByLabel('내 답변',{exact:true}).fill('제가 역할을 나누고 매일 진행 상황을 공유했습니다.');
 await page.getByRole('button',{name:'답변 끝내기'}).click();
 await page.getByRole('button',{name:'면접 마치고 회고 보기'}).click();
 await expect(page.getByRole('heading',{name:'통합 코칭'})).toBeVisible();
 const reviewStart=observed.length;
 await expect(page.getByRole('heading',{name:'연습 역량과 관찰 근거'})).toBeVisible();
 await expect(page.getByText('질문 1개 · 인용 근거 0개')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
 const reviewLink=page.getByRole('link',{name:'Q1',exact:true}).first();
 await reviewLink.focus(); await expect(reviewLink).toBeFocused();
 const contrast = () => page.locator('.debrief-card, .competency-review, .voice-report, .video-report').evaluateAll(cards => {
   const luminance=(value:string)=>{const rgb=(value.match(/[\d.]+/g)??[]).slice(0,3).map(Number).map(n=>n/255).map(n=>n<=0.03928?n/12.92:((n+0.055)/1.055)**2.4);return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];};
   return Math.min(...cards.flatMap(card=>{const background=luminance(getComputedStyle(card).backgroundColor);return [...card.querySelectorAll('.muted,th')].map(el=>{const foreground=luminance(getComputedStyle(el).color);return (Math.max(foreground,background)+0.05)/(Math.min(foreground,background)+0.05);});}));
 });
 expect(await contrast()).toBeGreaterThanOrEqual(4.5);
 await page.screenshot({path:test.info().outputPath('integrated-review-light.png'),fullPage:true});
 await page.emulateMedia({colorScheme:'dark'});
 expect(await contrast()).toBeGreaterThanOrEqual(4.5);
 await page.screenshot({path:test.info().outputPath('integrated-review-dark.png'),fullPage:true});
 await page.getByText('내 답변으로 개선 틀 만들기' ,{exact:true}).click();
 await expect(page.getByText('내 답변에서 가져온 재료:',{exact:false})).toContainText('제가 역할을 나누고');
 const reviewRequests=observed.slice(reviewStart);
 expect(reviewRequests.filter(r=>r.method==='POST'&&/\/(coach|debrief)$/.test(r.path))).toEqual([]);
 const homeTaxonomy=observed.filter(r=>r.path==='/practice/taxonomy'&&r.method==='GET').length;
 const questionGets=observed.filter(r=>r.path==='/practice/questions'&&r.method==='GET').length;
 await page.goto('/practice/history');
 await expect(page.getByLabel('연습 역량 필터')).toBeVisible();
 await page.getByLabel('연습 역량 필터').selectOption(taxonomy.competencies[0].key);
 await expect(page.getByRole('link',{name:/자유 연습/}).first()).toBeVisible();
 const callCounts={homeTaxonomyGets:homeTaxonomy,homeQuestionGetsIncludingEditorRefresh:questionGets,historyTaxonomyGets:observed.filter(r=>r.path==='/practice/taxonomy'&&r.method==='GET').length-homeTaxonomy,reviewExtraCoachingPosts:reviewRequests.filter(r=>r.method==='POST'&&/\/(coach|debrief)$/.test(r.path)).length};
 console.log('Integrated review API counts',JSON.stringify(callCounts));
 await test.info().attach('api-call-counts.json',{body:JSON.stringify(callCounts,null,2),contentType:'application/json'});
});

test('disabled taxonomy hides editing and selection controls',async({page})=>{
 await page.route('**/practice/taxonomy',route=>route.fulfill({json:{enabled:false,taxonomy_version:'interview-v1',question_types:[],competencies:[],max_competencies:3}}));
 await page.goto('/practice');
 await expect(page.getByRole('heading',{name:'질문은행'})).toBeVisible();
 await expect(page.getByLabel('질문 유형 필터')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'분류 편집'})).toHaveCount(0);
 await expect(page.getByRole('group',{name:'직접 추가할 질문 분류'})).toHaveCount(0);
});

test('legacy debrief remains readable as history and is excluded from current integrated findings', async ({page,request}) => {
 const q=await (await request.post(`${API}/practice/questions`,{data:{category:'인성',text:`이전 회고 보존 ${Date.now()}`}})).json();
 const s=await (await request.post(`${API}/practice/sessions`,{data:{mode:'free',question_ids:[q.id]}})).json();
 await page.route(`**/practice/sessions/${s.id}`, async route => {
   if (route.request().isNavigationRequest()) return route.continue();
   const response=await route.fetch();
   const body=await response.json();
   await route.fulfill({response,json:{...body,debrief_status:'done',debrief:{lesson:'보관한 이전 버전의 교훈',next_action:'이전 행동',moments:[],input_status:'legacy_unverified'}}});
 });
 await page.goto(`/practice/sessions/${s.id}`);
 await expect(page.locator('.integrated-coaching')).not.toContainText('보관한 이전 버전의 교훈');
 await page.getByText('기존 AI 디브리프의 근거와 원문',{exact:true}).click();
 await expect(page.getByText('보관한 이전 버전의 교훈',{exact:true})).toBeVisible();
 await expect(page.getByText('현재 답변과의 일치를 확인할 수 없어',{exact:false})).toBeVisible();
});
