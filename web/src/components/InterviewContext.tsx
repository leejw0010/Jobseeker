import { Link } from "react-router-dom";
import type { InterviewContext as Context } from "../types";

export default function InterviewContext({ context }: { context: Context | null }) {
  if (!context) return null;
  const essays = context.essays ?? [];
  return (
    <section className="card source-context">
      <div className="row"><h2 className="grow" style={{ margin: 0 }}>이번 면접의 기준 자료</h2>
        {context.company && <span className="chip">{context.company} · {context.position}</span>}
      </div>
      <p className="small muted">면접을 시작할 때 보관한 자료예요. 이후 자소서를 수정해도 이 면접의 기준은 유지돼요.</p>
      {essays.length === 0 && <p className="small muted">연결된 자소서가 없어요. 질문과 답변을 중심으로 연습해요.</p>}
      {essays.map((e) => (
        <details key={e.version_id} className="source-detail">
          <summary>{e.question_text} <span className="chip">v{e.version_no} · {e.selection === "submitted" ? "제출본" : "최신본"}</span></summary>
          {context.essay_basis === "submitted" && e.selection === "latest" && <p className="small muted">제출 표시가 없어 이 문항은 최신본을 사용했어요.</p>}
          <p className="evidence-text">{e.content}</p>
        </details>
      ))}
      {context.job_description && <details className="source-detail"><summary>채용 공고</summary><p className="evidence-text">{context.job_description}</p></details>}
      {!!context.drill_targets?.length && <div className="drill-focus">
        <strong>이번에 보완할 부분</strong>
        {context.drill_targets.map((t) => <p key={t.answer_id}><span className="chip">{t.focus.join(" · ")}</span> {t.next_action}</p>)}
        {context.origin_session_id && <Link className="small" to={`/practice/sessions/${context.origin_session_id}`}>이전 답변과 회고 보기</Link>}
      </div>}
    </section>
  );
}
