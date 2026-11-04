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
