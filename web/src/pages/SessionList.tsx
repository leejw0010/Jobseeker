import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { SessionSummary, PracticeTaxonomy } from "../types";

export default function SessionList() {
  const nav = useNavigate();
  const [taxonomy,setTaxonomy]=useState<PracticeTaxonomy|null>(null);
  const [competency,setCompetency]=useState("");
  useEffect(()=>{api.taxonomy().then(setTaxonomy).catch(()=>{});},[]);
  const [rows, setRows] = useState<SessionSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.sessions().then(setRows).catch((e) => setErr(e.message));
  }, []);
  if (err) return <p className="err">{err}</p>;
  if (!rows) return <p className="muted">불러오는 중…</p>;
  return (
    <>
      <h1>연습 기록</h1>
      {taxonomy?.enabled&&<label>연습 역량 필터<select value={competency} onChange={e=>setCompetency(e.target.value)}><option value="">전체 역량</option>{taxonomy.competencies.map(c=><option value={c.key} key={c.key}>{c.label}</option>)}</select></label>}
      <div className="card table-scroll">
        {rows.length === 0 ? (
          <p className="muted">아직 연습 기록이 없습니다.</p>
        ) : (
          <table>
            <thead>
              <tr><th>제목</th><th>방식</th><th>녹음</th><th>평균 자기평가</th><th>날짜</th></tr>
            </thead>
            <tbody>
              {rows.filter(r=>!competency||r.competency_keys?.includes(competency)).map((r) => (
                <tr key={r.id} className="click" onClick={() => nav(`/practice/sessions/${r.id}`)}>
                  <td><Link to={`/practice/sessions/${r.id}`}>{r.title}</Link>{taxonomy?.enabled&&<div className="row small">{r.competency_keys?.map(k=><span className="chip" key={k}>{taxonomy.competencies.find(c=>c.key===k)?.label??k}</span>)}{!!r.classification_missing_count&&<span className="muted">분류 없음 {r.classification_missing_count}개</span>}</div>}{!r.finished_at && <span className="chip" style={{ marginLeft: 6 }}>진행 중</span>}</td>
                  <td>{r.mode === "mock" ? "모의시험" : "자유 연습"}</td>
                  <td>{r.recorded_count} / {r.answer_count}</td>
                  <td>{r.avg_rating != null ? `★ ${r.avg_rating.toFixed(1)}` : "–"}</td>
                  <td className="muted">{new Date(r.created_at).toLocaleDateString("ko-KR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
