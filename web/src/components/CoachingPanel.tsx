import type { CoachingReport, CoachingRubric, InterviewContext } from "../types";

/** 코칭 기준과 앵커(GET /practice/rubric). 프롬프트와 같은 정의를 보여준다. */
function RubricDetails({ rubric }: { rubric: CoachingRubric }) {
  return (
    <details className="rubric-details">
      <summary>채점 기준 보기</summary>
      {rubric.criteria.map((c) => (
        <div key={c.key} className="rubric-row">
          <strong>{c.label}</strong> <span className="small muted">{c.checks}</span>
          <ul className="bullets small">
            <li><span className="chip good">충분</span> {c.anchors.충분}</li>
            <li><span className="chip needs-work">보완</span> {c.anchors.보완}</li>
          </ul>
          {c.star && <>
            <p className="small muted">{c.star.when}이면 이 세 가지를 봐요.</p>
            <ul className="bullets small">{c.star.anchors.map((a) => <li key={a}>{a}</li>)}</ul>
          </>}
        </div>
      ))}
      <p className="small muted">판단유보: {rubric.statuses.판단유보}</p>
      <p className="small muted">{rubric.note}</p>
    </details>
  );
}

export default function CoachingPanel({ report, context, rubric }: { report: CoachingReport; context: InterviewContext | null; rubric?: CoachingRubric | null }) {
  return (
    <div className="coaching-panel">
      <div className="row"><strong>답변 회고</strong><span className="chip accent">{report.method === "ai" ? "AI 코칭" : "기본 점검"}</span></div>
      <p>{report.summary}</p>
      {report.method === "basic" && <p className="small muted">표현을 확인하는 기본 점검이에요. 답변의 의미나 사실 여부를 판정하지 않아요.</p>}
      {report.method === "ai" && rubric && <p className="small muted">{rubric.note}</p>}
      <div className="next-action"><strong>다음 연습</strong><p>{report.next_action}</p></div>
      <div className="criteria-list">
        {report.criteria.map((c) => {
          const source = context?.essays?.find((e) => e.version_id === c.source_version_id);
          return <details key={c.key} className="criterion" open={c.status === "보완"}>
            <summary>{c.label} <span className={`chip ${c.status === "보완" ? "needs-work" : c.status === "충분" ? "good" : ""}`}>{c.status}</span></summary>
            <p>{c.reason}</p>
            {c.answer_quote && <blockquote><span className="small muted">내 답변</span><p>{c.answer_quote}</p></blockquote>}
            {c.source_quote && <blockquote className="source-quote"><span className="small muted">기준 자소서{source ? ` · v${source.version_no}` : ""}</span><p>{c.source_quote}</p></blockquote>}
          </details>;
        })}
      </div>
      {rubric && <RubricDetails rubric={rubric} />}
    </div>
  );
}
