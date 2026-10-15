import type { CoachingReport, InterviewContext } from "../types";

export default function CoachingPanel({ report, context }: { report: CoachingReport; context: InterviewContext | null }) {
  return (
    <div className="coaching-panel">
      <div className="row"><strong>답변 회고</strong><span className="chip accent">{report.method === "ai" ? "AI 코칭" : "기본 점검"}</span></div>
      <p>{report.summary}</p>
      {report.method === "basic" && <p className="small muted">표현을 확인하는 기본 점검이에요. 답변의 의미나 사실 여부를 판정하지 않아요.</p>}
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
    </div>
  );
}
