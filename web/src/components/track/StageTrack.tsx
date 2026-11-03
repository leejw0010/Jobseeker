import { STAGES, type Application } from "../../types";

/** 지원 건의 단계 진행 막대(목록·상세에서 함께 쓴다) */
export function StageTrack({ a }: { a: Pick<Application, "stage" | "status"> }) {
  const cur = STAGES.indexOf(a.stage);
  return (
    <div className="stage-track" title={`${a.stage} · ${a.status}`}>
      {STAGES.map((s, i) => (
        <span key={s} className={i < cur || (i === cur && a.status === "합격") ? "on" : i === cur && a.status === "불합격" ? "fail" : i === cur ? "on" : ""}
          style={i === cur && a.status === "진행중" ? { opacity: 0.45 } : undefined} />
      ))}
    </div>
  );
}
