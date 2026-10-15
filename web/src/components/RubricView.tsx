import type { Band, Rubric, RubricFeedback } from "../types";

/** 판정 단계 → 칩 색상 클래스 */
export function bandClass(b: Band | string) {
  return b === "충분" ? "band-good" : b === "일부" ? "band-warn" : b === "부족" ? "band-bad" : "band-na";
}

/** 채점 기준(행동 앵커)을 접어서 보여준다. */
function RubricGuide({ rubric }: { rubric: Rubric }) {
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
      <p className="small muted">‘해당 없음’은 지원 동기·지식 질문처럼 과거 경험을 묻지 않을 때 상황·행동·결과에만 써요. 질문·직무 연결은 항상 봐요.</p>
      <p className="small muted" style={{ marginBottom: 0 }}>{rubric.note}</p>
    </details>
  );
}

/** 전사문 인용형 STAR 루브릭 피드백 */
export default function RubricView({ feedback, rubric }: { feedback: RubricFeedback; rubric: Rubric | null }) {
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>루브릭 피드백</h3>
        <span className="chip accent">AI 생성 · 참고용</span>
      </div>
      {feedback.stale && <p className="warn-text">전사문이 바뀌었어요. 다시 채점해 주세요.</p>}
      {feedback.summary && <p style={{ marginBottom: 6 }}>{feedback.summary}</p>}
      <div className="spacer" />
      {feedback.criteria.map((c) => (
        <div key={c.key} className="rubric-row">
          <div className="row">
            <b className="grow">{c.label}</b>
            <span className={`chip ${bandClass(c.band)}`}>{c.band}</span>
          </div>
          {c.comment && <div className="small" style={{ marginTop: 4 }}>{c.comment}</div>}
          {c.quote && <blockquote className="quote small">“{c.quote}”</blockquote>}
          {c.quote_verified === false && <div className="small muted">AI가 인용한 문장을 전사문에서 찾지 못해 인용은 뺐어요.</div>}
        </div>
      ))}
      {feedback.criteria.length === 0 && <p className="small muted">채점 결과를 읽지 못했어요. 다시 채점해 주세요.</p>}
      {feedback.rewrite.length > 0 && (
        <div className="rubric-row">
          <b>이렇게 말해 보세요</b>
          <ul className="bullets small">
            {feedback.rewrite.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
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
