import type { PracticeAnswer, PracticeSession, TaxonomyEntry } from '../types';
import { sessionInsights } from './insights';

export type GroundedComment = { type:'content'; item:string; source: string; quote: string; text: string; action?: string };
const excerpt=(text:string,max=140)=>text.length>max?`${text.slice(0,max)}…`:text;
const textOf = (a: PracticeAnswer) => a.transcript?.trim() ?? '';
export function answerComments(a: PracticeAnswer): GroundedComment[] {
  const text = textOf(a);
  if (!text) return [];
  return (a.coaching_report?.criteria ?? []).filter(c => c.answer_quote?.trim() && text.includes(c.answer_quote.trim())).map(c => ({
    type:"content" as const,item:c.label,source: `답변 코칭 · ${c.label}`, quote:c.answer_quote.trim(), text:`${c.status}: ${c.reason}`,
    ...(c.status === '보완' ? {action:a.coaching_report?.next_action} : {}),
  })).sort((a,b) => Number(!!b.action) - Number(!!a.action));
}
export function competencyCoverage(answers: PracticeAnswer[]) {
  type Row = TaxonomyEntry & {questionCount:number;answeredCount:number;transcribedCount:number;analyzedCount:number;primaryCount:number;followupCount:number;observedCount:number;observations:{answerId:string;order:number;quote:string;reason:string;basis:string}[]};
  const rows = new Map<string,Row>(); let missing=0,untagged=0;
  const extraObservations:{key:string;answerId:string;order:number;quote:string;reason:string}[]=[];
  for (const a of answers) {
    const snapshot=a.question_classification;
    if (!snapshot) {missing++;continue;}
    if(!snapshot.competencies.length) untagged++;
    const evidence=a.coaching_report?.competency_evidence;
    if(evidence?.status==='analyzed') for(const o of evidence.observations) {
      if(!snapshot.competencies.some(c=>c.key===o.competency_key)&&o.quote.trim()&&textOf(a).includes(o.quote.trim())) extraObservations.push({key:o.competency_key,answerId:a.id,order:a.order_no,quote:o.quote,reason:o.reason});
    }
    for (const c of snapshot.competencies) {
      // Version and label are frozen per answer; never substitute live question tags.
      const id = `${snapshot.taxonomy_version}:${c.key}`;
      const row=rows.get(id) ?? {...c,questionCount:0,answeredCount:0,transcribedCount:0,analyzedCount:0,primaryCount:0,followupCount:0,observedCount:0,observations:[]}; row.questionCount++;
      if(a.recorded_at||textOf(a)) row.answeredCount++;
      if(textOf(a)) row.transcribedCount++;
      if(a.coaching_report?.competency_evidence?.status==='analyzed') row.analyzedCount++;
      if(snapshot.question_role==='followup') row.followupCount++; else row.primaryCount++;
      const evidence=a.coaching_report?.competency_evidence;
      const hit=evidence?.status==='analyzed' ? evidence.observations.find(o=>o.competency_key===c.key && o.quote.trim() && textOf(a).includes(o.quote.trim())) : undefined;
      if(hit) {row.observedCount++;row.observations.push({answerId:a.id,order:a.order_no,quote:hit.quote,reason:hit.reason,basis:hit.basis});}
      rows.set(id,row);
    }
  }
  return {missing,untagged,extraObservations,rows:[...rows.values()]};
}
export function groundedOutline(a: PracticeAnswer): string[] {
  const text=textOf(a); if(!text) return [];
  return ['질문에 대한 결론: [실제로 말하려는 핵심을 한 문장으로 작성]', `내 답변에서 가져온 재료: “${text}”`, '내 역할과 행동: [실제로 맡은 범위와 선택한 이유를 확인해 작성]', '결과와 배운 점: [실제로 확인한 결과만 작성 · 수치가 없으면 관찰한 변화]'];
}
export type DeliveryFact = {answerId:string;order:number;source:string;text:string;action?:string};
/** Local composition only: existing core coaching plus quoted facts, never a new AI request. */
export function integratedCoaching(s: PracticeSession, delivery: DeliveryFact[] = []) {
  const answered=s.answers.filter(a=>textOf(a));
  const comments=s.answers.flatMap(a=>answerComments(a).map(c=>({...c,a})));
  const points=sessionInsights(s).points;
  const actions:{answerId:string;order:number;text:string}[]=[];
  for(const p of points) {
    const ref=p.answers[0]; if(ref && !actions.some(x=>x.text===p.action)) actions.push({answerId:ref.id,order:ref.order,text:p.action});
    if(actions.length===2) break;
  }
  const parts=[`이번 연습은 답변 ${s.answers.length}개 중 전사문 ${answered.length}개를 바탕으로 돌아볼게요.`];
  if(s.debrief_status==='done' && s.debrief?.lesson) parts.push(`기존 세션 디브리프에서 짚은 핵심은 “${excerpt(s.debrief.lesson,160)}”예요.`);
  const primary=points.find(p=>p.source==='coaching');
  if(primary) parts.push(`내용에서는 ${primary.title}이 ${primary.answers.length}개 답변에서 보여 이번 연습의 우선 과제로 잡았어요.`);
  const positive=comments.find(c=>c.text.startsWith('충분:'));
  if(positive) parts.push(`다시 연습할 때 유지할 재료도 있어요. Q${positive.a.order_no}의 “${excerpt(positive.quote,90)}”는 ${positive.source.replace('답변 코칭 · ','')} 코칭에서 충분으로 확인한 대목이에요. ${excerpt(positive.text.replace('충분: ',''),120)}`);
  const improvement=primary ? comments.find(c=>c.a.id===primary.answers[0]?.id && c.action && c.source.endsWith(primary.title.replace(' 보완',''))) : comments.find(c=>c.action);
  if(improvement) parts.push(`이 과제를 구체적으로 보면, Q${improvement.a.order_no}에서 “${excerpt(improvement.quote,90)}”라고 말했어요. 답변 코칭은 여기서 ${excerpt(improvement.text.replace('보완: ',''),140)}라고 짚었어요. 이 문장을 출발점으로 삼아 빠진 내용을 실제 경험 안에서 채워 보세요.`);
  for(const fact of delivery.slice(0,2)) {
    parts.push(`같은 연습의 Q${fact.order}에서 ${fact.source}로 확인한 값은 ${fact.text} 이 수치는 답변 내용에 대한 평가와 구분해서 참고해 주세요.`);
    if(fact.action && actions.length<3 && !actions.some(x=>x.text===fact.action)) actions.push({answerId:fact.answerId,order:fact.order,text:fact.action});
  }
  if(!comments.length) parts.push(answered.length ? '아직 인용으로 확인할 수 있는 답변 코칭이 없어요. 아래 전사문을 확인하고 답변 점검으로 내용의 근거를 먼저 살펴보세요.' : '아직 답변 내용이 없어 해석을 만들지 않았어요. 답변을 저장한 뒤 다시 살펴보세요.');
  if(actions.length) parts.push(`다음 연습에서는 ${actions.map(x=>`Q${x.order}에서 ${excerpt(x.text,100)}`).join(' 그리고 ')}부터 해보세요.`);
  else if(answered.length) actions.push({answerId:answered[0].id,order:answered[0].order_no,text:'전사문을 확인하고 답변 점검에서 근거와 보완점을 확인하기'});
  return {script:excerpt(parts.join('\n\n'),1000),actions:actions.slice(0,3),comments};
}

export function answerCoaching(a:PracticeAnswer, delivery:DeliveryFact[]=[]) {
 const comments=answerComments(a);
 const improvement=comments.find(c=>c.action);
 const positive=comments.find(c=>c.text.startsWith('충분:'));
 const facts=delivery.filter(f=>f.answerId===a.id);
 const parts:string[]=[];
 if(positive) parts.push(`유지할 재료는 “${excerpt(positive.quote,100)}”예요. ${positive.source}에서 충분으로 확인했어요.`);
 if(improvement) parts.push(`가장 먼저 볼 부분은 ${improvement.item}이에요. “${excerpt(improvement.quote,100)}”라는 답변에 대해 ${excerpt(improvement.text.replace('보완: ',''),160)}`);
 if(facts.length) parts.push(`전달 방식은 ${facts.map(f=>`${f.source}: ${f.text}`).join(' ')}`);
 const priority=improvement?.action||facts.find(f=>f.action)?.action||null;
 return {script:parts.join(' '),priority,comments};
}
