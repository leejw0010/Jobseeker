import type { PracticeAnswer, PracticeSession, TaxonomyEntry } from '../types';
import { sessionInsights } from './insights';

export type GroundedComment = { type:'content'; item:string; source: string; quote: string; text: string; action?: string };
const excerpt=(text:string,max=140)=>text.length>max?`${text.slice(0,max)}…`:text;
const textOf = (a: PracticeAnswer) => a.transcript?.trim() ?? '';
const currentReport = (a: PracticeAnswer) => a.coaching_report?.input_status === 'legacy_unverified' ? null : a.coaching_report;
export function answerComments(a: PracticeAnswer): GroundedComment[] {
  const text = textOf(a);
  if (!text) return [];
  return (currentReport(a)?.criteria ?? []).filter(c => c.answer_quote?.trim() && text.includes(c.answer_quote.trim())).map(c => ({
    type:"content" as const,item:c.label,source: `답변 코칭 · ${c.label}`, quote:c.answer_quote.trim(), text:`${c.status}: ${c.reason}`,
  }));
}
export function competencyCoverage(answers: PracticeAnswer[]) {
  type Row = TaxonomyEntry & {questionCount:number;answeredCount:number;transcribedCount:number;analyzedCount:number;primaryCount:number;followupCount:number;observedCount:number;observations:{answerId:string;order:number;quote:string;reason:string;basis:string}[]};
  const rows = new Map<string,Row>(); let missing=0,untagged=0;
  const extraObservations:{key:string;answerId:string;order:number;quote:string;reason:string}[]=[];
  for (const a of answers) {
    const snapshot=a.question_classification;
    if (!snapshot) {missing++;continue;}
    if(!snapshot.competencies.length) untagged++;
    const evidence=currentReport(a)?.competency_evidence;
    if(evidence?.status==='analyzed') for(const o of evidence.observations) {
      if(!snapshot.competencies.some(c=>c.key===o.competency_key)&&o.quote.trim()&&textOf(a).includes(o.quote.trim())) extraObservations.push({key:o.competency_key,answerId:a.id,order:a.order_no,quote:o.quote,reason:o.reason});
    }
    for (const c of snapshot.competencies) {
      // Version and label are frozen per answer; never substitute live question tags.
      const id = `${snapshot.taxonomy_version}:${c.key}`;
      const row=rows.get(id) ?? {...c,questionCount:0,answeredCount:0,transcribedCount:0,analyzedCount:0,primaryCount:0,followupCount:0,observedCount:0,observations:[]}; row.questionCount++;
      if(a.recorded_at||textOf(a)) row.answeredCount++;
      if(textOf(a)) row.transcribedCount++;
      if(currentReport(a)?.competency_evidence?.status==='analyzed') row.analyzedCount++;
      if(snapshot.question_role==='followup') row.followupCount++; else row.primaryCount++;
      const evidence=currentReport(a)?.competency_evidence;
      const hit=evidence?.status==='analyzed' ? evidence.observations.find(o=>o.competency_key===c.key && o.quote.trim() && textOf(a).includes(o.quote.trim())) : undefined;
      if(hit) {row.observedCount++;row.observations.push({answerId:a.id,order:a.order_no,quote:hit.quote,reason:hit.reason,basis:hit.basis});}
      rows.set(id,row);
    }
  }
  return {missing,untagged,extraObservations,rows:[...rows.values()]};
}
export function groundedOutline(a: PracticeAnswer): string[] {
  const text=textOf(a); if(!text) return [];
  const prompts:Record<string,string[]> = {
    self_description:['자기소개 핵심: [실제로 설명하려는 강점이나 특성]', '근거 연결: [그 특성을 보여주는 실제 사례와 한계]', '질문 연결: [질문이 요구하는 자기이해와 연결]'],
    motivation:['지원 이유: [실제로 지원한 이유와 목표]', '선택 근거: [확인한 회사·직무 정보와 자신의 경험]', '연결점: [목표를 위해 준비한 것과 더 확인할 것]'],
    behavioral:['상황과 과제: [실제로 겪은 상황과 목표]', '행동과 판단: [팀 안에서 실제로 맡은 몫과 선택 이유]', '결과와 배운 점: [실제로 확인한 결과만 작성]'],
    situational:['가정과 조건: [질문에 주어진 조건과 더 확인할 정보]', '판단 기준: [선택할 대응과 대안의 장단점]', '대응 순서: [가정한 행동과 결과를 확인할 방법 · 실제 경험과 구분]'],
    project_deep_dive:['프로젝트 맥락: [실제 목표와 제약]', '선택과 역할: [맡은 범위·선택 이유·검토한 대안]', '확인과 한계: [실제 결과와 검증 방법·남은 한계]'],
    knowledge:['개념과 결론: [설명하려는 원리나 핵심 답]', '추론 과정: [답에 이르는 근거와 적용 조건]', '검증과 한계: [확인 가능한 예와 모르는 부분]'],
  };
  const outline=prompts[a.question_classification?.question_type ?? ''] ?? ['질문이 요구하는 답: [실제로 말하려는 핵심]', '근거와 설명: [확인 가능한 재료와 판단 이유]', '확인할 부분: [질문에 비추어 빠진 설명과 모르는 부분]'];
  return [outline[0], `내 답변에서 가져온 재료: “${text}”`, ...outline.slice(1)];
}
export type DeliveryFact = {answerId:string;order:number;source:string;text:string;action?:string};
/** Local composition only: existing core coaching plus quoted facts, never a new AI request. */
export function integratedCoaching(s: PracticeSession, delivery: DeliveryFact[] = []) {
  const answered=s.answers.filter(a=>textOf(a));
  const comments=s.answers.flatMap(a=>answerComments(a).map(c=>({...c,a})));
  const tieOrder:Record<string,number>={"coaching-relevance":0,"coaching-specificity":1,"coaching-consistency":2};
  const points=[...sessionInsights(s).points].sort((a,b)=> Number(b.source==='coaching')-Number(a.source==='coaching') || new Set(b.answers.map(x=>x.id)).size-new Set(a.answers.map(x=>x.id)).size || (tieOrder[a.key]??3)-(tieOrder[b.key]??3));
  const actions:{answerId:string;order:number;text:string}[]=[];
  for(const p of points) {
    const ref=p.answers[0]; if(ref && !actions.some(x=>x.text===p.action)) actions.push({answerId:ref.id,order:ref.order,text:p.action});
    if(actions.length===2) break;
  }
  const parts=[`이번 연습은 답변 ${s.answers.length}개 중 전사문 ${answered.length}개를 바탕으로 돌아볼게요.`];
  if(s.debrief_status==='done' && s.debrief?.lesson && s.debrief.input_status!=='legacy_unverified') parts.push(`기존 세션 디브리프에서 짚은 핵심은 “${excerpt(s.debrief.lesson,160)}”예요.`);
  const primary=points.find(p=>p.source==='coaching');
  if(primary) parts.push(`내용에서는 ${primary.title}이 ${primary.answers.length}개 답변에서 보여 이번 연습의 우선 과제로 잡았어요.`);
  const positive=comments.find(c=>c.text.startsWith('충분:'));
  if(positive) parts.push(`다시 연습할 때 유지할 재료도 있어요. Q${positive.a.order_no}의 “${excerpt(positive.quote,90)}”는 ${positive.source.replace('답변 코칭 · ','')} 코칭에서 충분으로 확인한 대목이에요. ${excerpt(positive.text.replace('충분: ',''),120)}`);
  const improvement=primary ? comments.find(c=>c.a.id===primary.answers[0]?.id && c.text.startsWith('보완:') && c.source.endsWith(primary.title.replace(' 보완',''))) : comments.find(c=>c.text.startsWith('보완:'));
  if(improvement) parts.push(`이 과제를 구체적으로 보면, Q${improvement.a.order_no}에서 “${excerpt(improvement.quote,90)}”라고 말했어요. 답변 코칭은 여기서 ${excerpt(improvement.text.replace('보완: ',''),140)}라고 짚었어요. 이 문장을 출발점으로 삼아 빠진 내용을 실제 경험 안에서 채워 보세요.`);
  for(const fact of delivery.slice(0,2)) {
    parts.push(`같은 연습의 Q${fact.order}에서 ${fact.source}로 확인한 값은 ${fact.text} 이 수치는 답변 내용에 대한 평가와 구분해서 참고해 주세요.`);
    if(fact.action && actions.length<2 && !actions.some(x=>x.text===fact.action)) actions.push({answerId:fact.answerId,order:fact.order,text:fact.action});
  }
  if(!comments.length) parts.push(answered.length ? '아직 인용으로 확인할 수 있는 답변 코칭이 없어요. 아래 전사문을 확인하고 답변 점검으로 내용의 근거를 먼저 살펴보세요.' : '아직 답변 내용이 없어 해석을 만들지 않았어요. 답변을 저장한 뒤 다시 살펴보세요.');
  if(actions.length) parts.push(`다음 연습에서는 ${actions.map(x=>`Q${x.order}에서 ${excerpt(x.text,100)}`).join(' 그리고 ')}부터 해보세요.`);
  else if(answered.length) actions.push({answerId:answered[0].id,order:answered[0].order_no,text:'전사문을 확인하고 답변 점검에서 근거와 보완점을 확인하기'});
  return {script:excerpt(parts.join('\n\n'),1000),actions:actions.slice(0,2),comments};
}

export function answerCoaching(a:PracticeAnswer, delivery:DeliveryFact[]=[]) {
 const comments=answerComments(a);
 const improvement=comments.find(c=>c.text.startsWith('보완:'));
 const positive=comments.find(c=>c.text.startsWith('충분:'));
 const facts=delivery.filter(f=>f.answerId===a.id);
 const parts:string[]=[];
 if(positive) parts.push(`유지할 재료는 “${excerpt(positive.quote,100)}”예요. ${positive.source}에서 충분으로 확인했어요.`);
 if(improvement) parts.push(`가장 먼저 볼 부분은 ${improvement.item}이에요. “${excerpt(improvement.quote,100)}”라는 답변에 대해 ${excerpt(improvement.text.replace('보완: ',''),160)}`);
 if(facts.length) parts.push(`전달 방식은 ${facts.map(f=>`${f.source}: ${f.text}`).join(' ')}`);
 const priority=currentReport(a)?.next_action?.trim()||facts.find(f=>f.action)?.action||null;
 return {script:parts.join(' '),priority,comments};
}
