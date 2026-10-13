import { useEffect, useState } from "react";
import { api } from "../api";
import type { FunnelRow, Stats } from "../types";

const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);

/** 단계별 도달 건수 막대(단일 계열). 마우스를 올리면 통과·탈락·대기 내역을 보여준다. */
function Funnel({ rows }: { rows: FunnelRow[] }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.reached));
  return (
    <div className="bars" onMouseLeave={() => setTip(null)}>
      {rows.map((r) => (
        <div key={r.stage} className="bar-row"
          onMouseMove={(e) => setTip({ x: e.clientX + 12, y: e.clientY + 12, text: `${r.stage}\n도달 ${r.reached}건\n통과 ${r.passed} · 탈락 ${r.failed} · 대기 ${r.pending}\n통과율(확정 건 기준) ${pct(r.pass_rate)}` })}>
          <span>{r.stage}</span>
          <div className="bar-bg"><div className="bar" style={{ width: `${(r.reached / max) * 100}%` }} /></div>
          <span className="muted">{r.reached}건 · 통과율 {pct(r.pass_rate)}</span>
        </div>
      ))}
      {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  );
}

export default function StatsPage() {
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [table, setTable] = useState(false);
  useEffect(() => {
    api.stats().then(setS).catch((e) => setErr(e.message));
  }, []);
  if (err) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">불러오는 중…</p>;
  if (s.total === 0) return <><h1>통계</h1><p className="muted">지원 건이 쌓이면 단계별 통과율과 직무별 통계가 여기에 표시됩니다.</p></>;

  const decided = s.status["합격"] + s.status["불합격"];
  return (
    <>
      <h1>통계</h1>
      <div className="tiles">
        <div className="tile"><div className="v">{s.total}</div><div className="l">전체 지원</div></div>
        <div className="tile"><div className="v">{s.status["진행중"]}</div><div className="l">진행중</div></div>
        <div className="tile"><div className="v" style={{ color: "var(--good)" }}>{s.status["합격"]}</div><div className="l">✓ 최종 합격</div></div>
        <div className="tile"><div className="v" style={{ color: "var(--bad)" }}>{s.status["불합격"]}</div><div className="l">✕ 불합격</div></div>
        <div className="tile"><div className="v">{decided ? pct(s.status["합격"] / decided) : "–"}</div><div className="l">최종 합격률(결과 확정 건)</div></div>
      </div>

      <section className="card">
        <div className="row">
          <h2 className="grow" style={{ margin: 0 }}>단계별 진행</h2>
          <button className="small" onClick={() => setTable(!table)}>{table ? "막대로 보기" : "표로 보기"}</button>
        </div>
        <div className="spacer" />
        {table ? (
          <table>
            <thead><tr><th>단계</th><th>도달</th><th>통과</th><th>탈락</th><th>대기</th><th>통과율</th></tr></thead>
            <tbody>{s.funnel.map((r) => <tr key={r.stage}><td>{r.stage}</td><td>{r.reached}</td><td>{r.passed}</td><td>{r.failed}</td><td>{r.pending}</td><td>{pct(r.pass_rate)}</td></tr>)}</tbody>
          </table>
        ) : (
          <Funnel rows={s.funnel} />
        )}
        <p className="small muted">통과율 = 통과 ÷ (통과 + 탈락). 아직 결과가 나오지 않은 건은 분모에서 뺐습니다.</p>
      </section>

      <section className="card">
        <h2>직무 분류별</h2>
        <table>
          <thead>
            <tr><th>분류</th><th>지원</th>{s.funnel.map((r) => <th key={r.stage}>{r.stage} 통과율</th>)}<th>최종 합격</th></tr>
          </thead>
          <tbody>
            {s.by_job_category.map((c) => (
              <tr key={c.job_category}>
                <td>{c.job_category}</td>
                <td>{c.total}</td>
                {c.funnel.map((r) => <td key={r.stage} title={`통과 ${r.passed} / 탈락 ${r.failed} / 대기 ${r.pending}`}>{pct(r.pass_rate)}</td>)}
                <td>{c.final_pass}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>월별 지원 수</h2>
        <table>
          <tbody>{s.monthly.map((m) => <tr key={m.month}><td>{m.month}</td><td>{m.count}건</td></tr>)}</tbody>
        </table>
      </section>
    </>
  );
}
