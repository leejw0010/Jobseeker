import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { JOB_CATEGORIES, STAGES, STATUSES, type Application } from "../types";

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

export function StatusChip({ status }: { status: string }) {
  const cls = status === "합격" ? "good" : status === "불합격" ? "bad" : status === "진행중" ? "accent" : "";
  return <span className={`chip ${cls}`}>{status}</span>;
}

const EMPTY = { company: "", position: "", job_category: "개발", url: "", applied_at: "" };

export default function TrackList() {
  const nav = useNavigate();
  const [rows, setRows] = useState<Application[]>([]);
  const [f, setF] = useState({ status: "", stage: "", job_category: "", q: "" });
  const [form, setForm] = useState(EMPTY);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.applications(f).then(setRows).catch((e) => setErr(e.message));
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [f.status, f.stage, f.job_category, f.q]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    try {
      const a = await api.createApplication({
        company: form.company,
        position: form.position,
        job_category: form.job_category,
        url: form.url || null,
        applied_at: form.applied_at || null,
      });
      nav(`/track/${a.id}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>지원 관리</h1>
        <button className="primary" onClick={() => setOpen(!open)}>+ 지원 건 추가</button>
      </div>
      <div className="spacer" />
      {open && (
        <section className="card">
          <div className="row">
            <label className="grow">회사<input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></label>
            <label className="grow">직무(포지션)<input value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} /></label>
            <label>직무 분류
              <select value={form.job_category} onChange={(e) => setForm({ ...form, job_category: e.target.value })}>
                {JOB_CATEGORIES.map((j) => <option key={j}>{j}</option>)}
              </select>
            </label>
            <label>지원일<input type="date" value={form.applied_at} onChange={(e) => setForm({ ...form, applied_at: e.target.value })} /></label>
          </div>
          <div className="spacer" />
          <div className="row">
            <label className="grow">채용 공고 URL<input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></label>
            <button className="primary" disabled={!form.company || !form.position} onClick={create}>저장</button>
          </div>
        </section>
      )}
      {err && <p className="err">{err}</p>}
      <section className="card">
        <div className="row">
          <input className="grow" placeholder="회사·직무 검색" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
          <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            <option value="">전체 상태</option>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}>
            <option value="">전체 단계</option>
            {STAGES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select value={f.job_category} onChange={(e) => setF({ ...f, job_category: e.target.value })}>
            <option value="">전체 직무</option>
            {JOB_CATEGORIES.map((j) => <option key={j}>{j}</option>)}
          </select>
        </div>
        <div className="spacer" />
        {rows.length === 0 ? (
          <p className="muted">지원 건이 없습니다. 직접 추가하거나 크롬 확장에서 지원서를 제출하면 자동으로 저장됩니다.</p>
        ) : (
          <table>
            <thead>
              <tr><th>회사</th><th>직무</th><th>분류</th><th style={{ width: 160 }}>진행 단계</th><th>상태</th><th>지원일</th></tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="click" onClick={() => nav(`/track/${a.id}`)}>
                  <td>{a.company}{a.source === "extension" && <span className="chip" style={{ marginLeft: 6 }}>확장</span>}</td>
                  <td>{a.position}</td>
                  <td>{a.job_category}</td>
                  <td><StageTrack a={a} /><div className="small muted">{a.stage}</div></td>
                  <td><StatusChip status={a.status} /></td>
                  <td className="muted">{a.applied_at ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
