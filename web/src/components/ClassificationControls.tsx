import type { ClassificationInput, PracticeTaxonomy, QuestionClassification } from '../types';
export function ClassificationControls({taxonomy,value,onChange,label='분류'}:{taxonomy:PracticeTaxonomy|null;value:ClassificationInput;onChange:(v:ClassificationInput)=>void;label?:string}) {
 if(!taxonomy?.enabled) return null;
 const keys=value.competency_keys??[];
 return <fieldset style={{minWidth:0}}><legend>{label}</legend><label>질문 유형<select value={value.question_type??''} onChange={e=>onChange({...value,question_type:e.target.value||null})}><option value="">미분류</option>{taxonomy.question_types.map(t=><option value={t.key} key={t.key}>{t.label}</option>)}</select></label>
 <p className="small muted">역량은 최대 {taxonomy.max_competencies}개 · 질문이 다루는 범위이며 실력 점수가 아니에요.</p><div className="row small">{taxonomy.competencies.map(c=><label key={c.key} className="check-label" title={c.definition}><input type="checkbox" checked={keys.includes(c.key)} disabled={!keys.includes(c.key)&&keys.length>=taxonomy.max_competencies} onChange={()=>onChange({...value,competency_keys:keys.includes(c.key)?keys.filter(k=>k!==c.key):[...keys,c.key]})}/>{c.label}</label>)}</div></fieldset>;
}
export function FrozenClassification({snapshot}:{snapshot:QuestionClassification|null|undefined}) {
 if(!snapshot) return <p className="small muted">시작 시점 분류 없음 · 현재 질문의 태그로 과거 연습을 추정하지 않아요.</p>;
 return <div className="small"><span className="muted">시작 시점 분류</span><div className="row small">{snapshot.question_type_label&&<span className="chip" title={snapshot.question_type_definition??''}>{snapshot.question_type_label}</span>}{snapshot.competencies.map(c=><span className="chip" key={c.key} title={c.definition}>{c.label}</span>)}</div><span className="muted">{snapshot.taxonomy_version} · {snapshot.question_role==='followup'?'꼬리질문':'기본 질문'}</span></div>;
}
