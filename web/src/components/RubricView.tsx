import type { Band, Rubric, RubricCriterion, RubricFeedback } from "../types";

/** 판정 단계 → 칩 색상 클래스 */
export function bandClass(b: Band | string) {
  return b === "충분" ? "band-good" : b === "일부" ? "band-warn" : b === "부족" ? "band-bad" : "band-na";
}

/** 인용 근거에 관한 짧은 안내(AI가 지어낸 인용은 빼고, 근거 없는 '충분'은 서버가 '일부'로 낮춘다) */
function evidenceNote(c: RubricCriterion) {
  if (c.quote_verified === false)
    return c.model_band ? "AI가 든 인용을 전사문에서 확인하지 못해 인용을 빼고 ‘충분’을 ‘일부’로 낮췄어요." : "AI가 인용한 문장을 전사문에서 확인하지 못해 인용은 뺐어요.";
  if (c.evidence_missing) return c.model_band ? "근거 인용이 없어 ‘충분’을 ‘일부’로 낮췄어요." : "근거 인용이 없어요.";
  return null;
}

/** 채점 기준(행동 앵커)을 접어서 보여준다. */
function RubricGuide({ rubric }: { rubric: Rubric }) {
  const label = (key: string) => rubric.criteria.find((c) => c.key === key)?.label ?? key;
  return (
    <details>
      <summary>채점 기준 보기</summary>
      {rubric.criteria.map((c) => (
        <div key={c.key} className="rubric-row small">
          <b>{c.label}</b> · {c.question}
          <ul className="plain">
            {rubric.bands.filter((b) => c.anchors[b]).map((b) => (
              <li key={b}><span className={`chip ${bandClass(b)}`}>{b}</span> {c.anchors[b]}</li>
            ))}
          </ul>
        </div>
      ))}
      {rubric.variants?.map((v) => (
        <div key={v.key} className="rubric-row small">
          <b>{label(v.key)}</b> · {v.when}
          <ul className="plain">
            {rubric.bands.filter((b) => v.anchors[b]).map((b) => (
              <li key={b}><span className={`chip ${bandClass(b)}`}>{b}</span> {v.anchors[b]}</li>
            ))}
          </ul>
        </div>
      ))}
      <p className="small muted">
        ‘해당 없음’은 대부분 질문 유형으로 정해요. 자기소개·지원 동기·지식·인적성 질문은 상황·행동·결과를, 가상 상황 질문은 상황·결과를 채점하지 않아요. 유형을 정하지 못한 질문은 AI가 판단해요.
        질문·직무 연결은 항상 보고, 지원 회사·직무와의 연결은 지원 건이 있을 때 지식·인적성·가상 상황 질문을 뺀 나머지에서만 봐요.
      </p>
      <p className="small muted" style={{ marginBottom: 0 }}>{rubric.note}</p>
    </details>
  );
}

/** 전사문 인용형 STAR 루브릭 피드백 */
export default function RubricView({ feedback, rubric }: { feedback: RubricFeedback; rubric: Rubric | null }) {
  const qtype = feedback.question_type;
  const typeLabel = qtype && rubric?.question_types?.[qtype];
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>루브릭 피드백</h3>
        <span className="chip accent">AI 생성 · 참고용</span>
      </div>
      {typeLabel && <div className="small muted">질문 유형: {typeLabel}</div>}
      {(qtype === "knowledge" || qtype === "aptitude" || qtype === "general") && (
        <div className="small muted">내용이 맞는지(정답 여부)는 채점하지 않아요.</div>
      )}
      {feedback.stale && <p className="warn-text">전사문이 바뀌었어요. 다시 채점해 주세요.</p>}
      {feedback.summary && <p style={{ marginBottom: 6 }}>{feedback.summary}</p>}
      <div className="spacer" />
      {feedback.criteria.map((c) => {
        const note = evidenceNote(c);
        return (
          <div key={c.key} className="rubric-row">
            <div className="row">
              <b className="grow">{c.label}</b>
              <span className={`chip ${bandClass(c.band)}`}>{c.band}</span>
            </div>
            {c.comment && <div className="small" style={{ marginTop: 4 }}>{c.comment}</div>}
            {c.quote && <blockquote className="quote small">“{c.quote}”</blockquote>}
            {note && <div className="small muted">{note}</div>}
          </div>
        );
      })}
      {feedback.criteria.length === 0 && <p className="small muted">채점 결과를 읽지 못했어요. 다시 채점해 주세요.</p>}
      {feedback.rewrite.length > 0 && (
        <div className="rubric-row">
          <b>이렇게 말해 보세요</b>
          <ul className="bullets small">
            {feedback.rewrite.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          {feedback.rewrite.some((r) => r.includes("[")) && <div className="small muted">[수치]처럼 빈칸은 실제로 한 일로 채워 말해 보세요.</div>}
        </div>
      )}
      {rubric && (
        <div className="rubric-row">
          <RubricGuide rubric={rubric} />
        </div>
      )}
    </div>
  );
}
