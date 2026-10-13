import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { SessionSummary } from "../types";

export default function SessionList() {
  const nav = useNavigate();
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
      <div className="card">
        {rows.length === 0 ? (
          <p className="muted">아직 연습 기록이 없습니다.</p>
        ) : (
          <table>
            <thead>
              <tr><th>제목</th><th>방식</th><th>녹음</th><th>평균 자기평가</th><th>날짜</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="click" onClick={() => nav(`/practice/sessions/${r.id}`)}>
                  <td>{r.title}{!r.finished_at && <span className="chip" style={{ marginLeft: 6 }}>진행 중</span>}</td>
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
