import type { PracticeSession } from '../types';
import { answerComments, answerCoaching, competencyCoverage, groundedOutline, integratedCoaching, type DeliveryFact } from '../review/coaching';
import { getVoiceSegment, withVoiceTranscript } from '../delivery/voice';
import { getVideoSegments } from '../video/metrics';

export function localDeliveryFacts(s:PracticeSession):DeliveryFact[] {
 return s.answers.flatMap(a=>{
  if(!a.recorded_at) return [];
  const facts:DeliveryFact[]=[];
  const voice=getVoiceSegment(s.id,a.id,a.recorded_at,a.transcript??'');
  if(voice) {
   const v=withVoiceTranscript(voice,a.transcript??'');
   if(v.quality==='usable'&&v.activeCandidateSec!=null) facts.push({answerId:a.id,order:a.order_no,source:'브라우저 음성 에너지 표본',text:`전체 ${v.totalSec.toFixed(1)}초 중 발화 후보 ${v.activeCandidateSec.toFixed(1)}초, 분석 범위 ${Math.round(v.coverage*100)}%예요. ${v.longestPauseSec!=null?`가장 긴 에너지 휴지 후보는 ${v.longestPauseSec.toFixed(1)}초예요.`:''}`,action:v.longPauseCount&&v.longPauseCount>0?'긴 쉼이 있던 답변의 전사문에서 문단을 나누고 한 번 더 녹음하기':undefined});
  }
  const v=getVideoSegments(s.id,a.id,a.recorded_at);
  if(v&&v.analyzedMs>0) facts.push({answerId:a.id,order:a.order_no,source:'브라우저 카메라 표본',text:`분석 ${Math.round(v.analyzedMs/1000)}초 중 얼굴 일부가 프레임 밖이던 시간은 ${(v.edgeMs/1000).toFixed(1)}초예요.`,action:v.edgeMs>=1000?'카메라 미리보기에서 이마와 턱이 모두 보이도록 위치를 맞추고 다시 녹음하기':undefined});
  return facts;
 });
}
export default function IntegratedCoaching({s,paused=false}:{s:PracticeSession;paused?:boolean}) {
 if(paused) return <div className="integrated-coaching"><h2>통합 코칭</h2><p role="status" data-testid="integrated-content-paused" className="small muted">전사문을 수정 중이거나 변경한 회고 자료를 확인하고 있어요. 현재 대화를 확인할 때까지 세션 해석과 다음 행동을 잠시 멈춰요.</p></div>;
 const result=integratedCoaching(s,localDeliveryFacts(s));
 return <div className="integrated-coaching"><h2>통합 코칭</h2><p className="small muted">저장된 답변 코칭과 이 탭의 측정값을 함께 읽어요. 새로운 AI 요청 없이 만들며, 자료가 적으면 짧게 안내해요.</p><div style={{whiteSpace:'pre-wrap',lineHeight:1.85}}>{result.script}</div>{result.actions.length>0&&<><h3>다음 연습에서 해볼 일</h3><ol>{result.actions.map((x,i)=><li key={i}><a href={`#answer-${x.answerId}`}>Q{x.order}</a> {x.text}</li>)}</ol></>}</div>;
}
export function CompetencyPanel({s}:{s:PracticeSession}) {
 const {missing,untagged,extraObservations,rows}=competencyCoverage(s.answers);
 if(!rows.length&&!s.answers.some(a=>a.question_classification)) return null;
 return <section className="card competency-review"><h2>연습 역량과 관찰 근거</h2><p className="small muted">질문 수는 연습한 범위예요. 인용 근거 수는 AI가 답변의 인용과 연결한 관찰이며, 역량 점수나 합격 예측이 아니에요. 한 질문에 여러 역량이 있으면 각 항목에 중복 집계해요.</p>{missing>0&&<p className="small muted">시작 시점 분류가 없는 답변 {missing}개는 집계하지 않았어요.</p>}{untagged>0&&<p className="small muted">분류 스냅샷은 있지만 역량 태그를 지정하지 않은 답변 {untagged}개가 있어요.</p>}{rows.map((r,i)=><div key={i}><h3>{r.label}</h3><p className="small">{r.definition}</p><p>질문 {r.questionCount}개 · 인용 근거 {r.observedCount}개</p><p className="small">배정 {r.questionCount} · 답변 {r.answeredCount} · 전사문 {r.transcribedCount} · 역량 분석 {r.analyzedCount} · 인용 연결 {r.observedCount} · 기본 질문 {r.primaryCount} / 꼬리질문 {r.followupCount}</p>{r.observations.length?<ul className="plain">{r.observations.map((o,j)=><li key={j}><a href={`#answer-${o.answerId}`}>Q{o.order}</a> <span className="chip">{o.basis==='past_action'?'과거 행동 서술':o.basis==='proposed_action'?'제안한 행동':'설명'}</span><blockquote className="quote">“{o.quote}”</blockquote><p className="small">{o.reason}</p></li>)}</ul>:<p className="small muted">확인 가능한 인용 근거가 아직 없어요. 질문 태그만으로 역량을 판단하지 않아요.</p>}</div>)}{extraObservations.length>0&&<details><summary>질문에 지정되지 않은 역량의 추가 관찰</summary>{extraObservations.map((o,i)=><div key={i}><a href={`#answer-${o.answerId}`}>Q{o.order}</a> {o.key}<blockquote className="quote">“{o.quote}”</blockquote><p>{o.reason}</p></div>)}</details>}</section>;
}
export function AnswerGuidance({a,sessionId}:{a:PracticeSession['answers'][number];sessionId:string}) {
 const comments=answerComments(a); const outline=groundedOutline(a);
 const facts=localDeliveryFacts({id:sessionId,answers:[a]} as PracticeSession);
 const coaching=answerCoaching(a,facts);
 return <>{(coaching.script||coaching.priority)&&<div><h4>이번 답변의 코칭</h4><p>{coaching.script}</p>{coaching.priority&&<p><b>우선 해볼 일:</b> {coaching.priority}</p>}</div>}{facts.length>0&&<details><summary>전달 관찰의 근거와 다음 행동</summary>{facts.map((f,i)=><div key={i}><h4>{f.source.includes("음성")?"말하기":"카메라 위치"}</h4><p className="small muted">근거: {f.source}</p><p>{f.text}</p>{f.action&&<p>다음 행동: {f.action}</p>}</div>)}</details>}{comments.length>0&&<details><summary>근거로 보는 답변별 코멘트</summary>{comments.map((c,i)=><div key={i}><p className="small muted">{c.source}</p><blockquote className="quote">“{c.quote}”</blockquote><p>{c.text}</p></div>)}</details>}{outline.length>0&&<details><summary>내 답변으로 개선 틀 만들기</summary><p className="small muted">실제 전사문을 재료로 가져왔어요. 대괄호는 본인이 확인해 채울 자리이며, 새 경험이나 성과를 만들어 넣지 않아요.</p><ol>{outline.map((line,i)=><li key={i} style={{whiteSpace:'pre-wrap'}}>{line}</li>)}</ol></details>}</>;
}
