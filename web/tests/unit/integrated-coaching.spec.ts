import { expect, test } from '@playwright/test';
import { competencyCoverage, groundedOutline, integratedCoaching, answerComments, answerCoaching } from '../../src/review/coaching';
import type { PracticeAnswer, PracticeSession } from '../../src/types';
const answer = (over: Partial<PracticeAnswer> = {}) => ({ id:'a', order_no:1, transcript:'제가 일정 관리를 맡고 매일 진행 상황을 확인했습니다.', recorded_at:null, question:{text:'협업 경험',category:'인성',competency_keys:['teamwork']}, coaching_report:null, question_classification:null, ...over } as PracticeAnswer);
const session = (answers: PracticeAnswer[]) => ({ id:'s',answers,mode:'free',answer_sec:90,debrief:null,redrill:[] } as unknown as PracticeSession);
const snapshot = {schema_version:1 as const,taxonomy_version:'v1',question_type:'experience',question_type_label:'경험',question_type_definition:'실제 경험',competencies:[{key:'teamwork',label:'협업',definition:'함께 일하기'}],tagging_source:'manual',question_role:'primary' as const,captured_at:'now'};
test('historical debrief without a verified input identity is preserved separately, not narrated as a current finding', () => {
 const s={...session([answer()]),debrief_status:'done',debrief:{lesson:'과거 전용 교훈입니다',input_status:'legacy_unverified'}} as PracticeSession;
 expect(integratedCoaching(s).script).not.toContain('과거 전용 교훈입니다');
});
test('coverage counts frozen question scope separately from quoted observations and preserves legacy null', () => {
 const a=answer({question_classification:snapshot});
 expect(competencyCoverage([a,answer()])).toMatchObject({missing:1,untagged:0,extraObservations:[],rows:[{key:'teamwork',label:'협업',questionCount:1,answeredCount:1,transcribedCount:1,analyzedCount:0,primaryCount:1,followupCount:0,observedCount:0}]});
 expect(competencyCoverage([answer()]).rows).toEqual([]);
});
test('only actual transcript quotes count as observed evidence; changed transcripts reject old quotes', () => {
 const evidence={status:'analyzed',method:'ai',observations:[{competency_key:'teamwork',basis:'past_action',quote:'매일 진행 상황을 확인했습니다',reason:'진행 공유'}]};
 const a=answer({question_classification:snapshot,coaching_report:{competency_evidence:evidence,criteria:[]} as never});
 expect(competencyCoverage([a]).rows[0].observedCount).toBe(1);
 expect(competencyCoverage([{...a,transcript:'새 답변'}]).rows[0].observedCount).toBe(0);
});
test('coaching has no invented praise or measurements with absent evidence; outline uses verbatim words and placeholders', () => {
 const a=answer(); const result=integratedCoaching(session([a]));
 expect(result.script).toContain('전사문 1개');
 expect(result.script).not.toMatch(/뛰어나|자신감|분당|시선|성공적/);
 expect(result.actions.length).toBeLessThanOrEqual(3);
 expect(groundedOutline(a).join(' ')).toContain(a.transcript!);
 expect(groundedOutline(a).join(' ')).toContain('[실제로'); expect(answerComments(a).length).toBe(0);
});
test('prioritises grounded core coaching over generic preparation and refers to answer source', () => {
 const a=answer({coaching_report:{criteria:[{key:'specificity',label:'구체성',status:'보완',reason:'결과 설명이 필요해요',answer_quote:'제가 일정 관리를 맡고',source_quote:'',source_version_id:null}],next_action:'실제 결과를 한 문장으로 덧붙이세요'} as never});
 const r=integratedCoaching(session([a])); expect(r.script).toContain('Q1'); expect(r.script).toContain('제가 일정 관리를 맡고');
 expect(r.actions[0].text).toContain('실제 결과'); expect(answerComments(a)[0].source).toBe('답변 코칭 · 구체성');
});
test('coaching groups a shared content pattern rather than concatenating each criterion', () => {
 const core={criteria:[{key:'specificity',label:'구체성',status:'보완',reason:'결과가 빠졌어요',answer_quote:'제가 일정 관리를 맡고'}],next_action:'실제로 확인한 결과를 추가하기'};
 const a=answer({coaching_report:core as never});
 const b={...a,id:'b',order_no:2};
 const script=integratedCoaching(session([a,b])).script;
 expect(script).toContain('구체성 보완이 2개 답변');
 expect(script.match(/결과가 빠졌어요/g)?.length).toBe(1);
});

test('coverage separates untagged snapshots and followups; narrative stays bounded', () => {
 const a=answer({question_classification:{...snapshot,question_role:'followup'}});
 const empty=answer({question_classification:{...snapshot,competencies:[]}});
 expect(competencyCoverage([a,empty])).toMatchObject({missing:0,untagged:1,rows:[{primaryCount:0,followupCount:1}]});
 const report={criteria:[{key:'specificity',label:'구체성',status:'보완',reason:'근거'.repeat(1000),answer_quote:'제가 일정 관리를 맡고'}],next_action:'행동'.repeat(1000)};
 expect(integratedCoaching(session([answer({coaching_report:report as never})])).script.length).toBeLessThanOrEqual(1001);
});

test('per-answer coaching joins one priority with measured delivery and no invented strength', () => {
 const result=answerCoaching(answer(),[{answerId:'a',order:1,source:'브라우저 카메라 표본',text:'분석 5초 중 프레임 밖 2초',action:'카메라 위치 점검'}]);
 expect(result.script).toContain('분석 5초 중 프레임 밖 2초');
 expect(result.priority).toBe('카메라 위치 점검');
 expect(result.script).not.toMatch(/훌륭|좋았|충분/);
});

test('answer action belongs once to the whole answer, not to every weak criterion', () => {
 const a=answer({coaching_report:{criteria:['specificity','relevance'].map((key)=>({key,label:key,status:'보완',reason:'추가 설명 필요',answer_quote:'제가 일정 관리를 맡고'})),next_action:'하나의 다음 행동'} as never});
 const result=answerCoaching(a);
 expect(result.comments.every(c=>!c.action)).toBe(true);
 expect(result.priority).toBe('하나의 다음 행동');
});

test('session themes use distinct affected answers then relevance before specificity ties', () => {
 const weak=(key:string)=>({key,label:key==='relevance'?'질문 적합성':'구체성',status:'보완',reason:'확인할 근거',answer_quote:'제가 일정 관리를 맡고'});
 const a=answer({coaching_report:{criteria:[weak('specificity'),weak('relevance')],next_action:'한 행동'} as never});
 const b=answer({id:'b',order_no:2,coaching_report:{criteria:[weak('relevance')],next_action:'다른 행동'} as never});
 const r=integratedCoaching(session([a,b]));
 expect(r.script).toContain('질문 적합성 보완이 2개 답변');
 expect(r.actions.length).toBeLessThanOrEqual(2);
 const tied=integratedCoaching(session([a]));
 expect(tied.script).toContain('질문 적합성 보완이 1개 답변');
});

test('unverified historical coaching is excluded from current comments, priorities, and observations', () => {
 const a=answer({question_classification:snapshot,coaching_report:{input_status:'legacy_unverified',criteria:[{key:'specificity',label:'구체성',status:'보완',reason:'과거 조언',answer_quote:'제가 일정 관리를 맡고'}],next_action:'과거 행동',competency_evidence:{status:'analyzed',observations:[{competency_key:'teamwork',basis:'past_action',quote:'매일 진행 상황을 확인했습니다',reason:'과거 해석'}]}} as never});
 expect(answerComments(a)).toEqual([]);
 expect(integratedCoaching(session([a])).script).not.toContain('과거 조언');
 expect(competencyCoverage([a]).rows[0].observedCount).toBe(0);
});

test('outlines follow each question type and keep unknown questions neutral', () => {
 const expected:Record<string,string>={behavioral:'상황',situational:'가정',knowledge:'개념',motivation:'지원',project_deep_dive:'선택',self_description:'소개'};
 for(const [type,word] of Object.entries(expected)) {
  const lines=groundedOutline(answer({question_classification:{...snapshot,question_type:type}}));
  expect(lines.join(' ')).toContain(word);
  expect(lines.join(' ')).toContain(answer().transcript!);
 }
 const unknown=groundedOutline(answer()).join(' ');
 expect(unknown).not.toContain('결과와 배운 점');
 expect(unknown).toContain('질문이 요구하는');
});

test('current report keeps its single next action even when every criterion defers without a quote', () => {
 const a=answer({coaching_report:{input_status:'current',criteria:[{key:'relevance',label:'질문 적합성',status:'판단유보',reason:'근거가 부족해요',answer_quote:''}],next_action:'질문이 요구하는 답을 한 문장으로 정리하기'} as never});
 expect(answerCoaching(a).priority).toBe('질문이 요구하는 답을 한 문장으로 정리하기');
 expect(answerCoaching(a).comments).toEqual([]);
});
