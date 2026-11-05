import { useMemo } from "react";
import { CRITERIA, MIN_RATE_SEC, sessionInsights, splitPoints, type AnswerMetrics, type CriterionState, type ImprovementPoint } from "../review/insights";
import type { PracticeSession } from "../types";

// 회고 한눈에 보기(R1): 세션 상세 값만으로 계산한다(LLM 호출 없음). 계산은 review/insights.ts

const STATE_MARK: Record<CriterionState, { mark: string; cls: string }> = {
  충분: { mark: "✓", cls: "good" },
  보완: { mark: "!", cls: "warn" },
  판단유보: { mark: "–", cls: "neutral" },
  "점검 전": { mark: "·", cls: "none" },
};

interface Bar {
  key: string;
  label: string;
  value: number;
  text: string;
  tip: string;
}

/** 가로 막대(단일 계열). 기준선은 점선, 값은 막대 끝에 쓰고 표 보기를 함께 둔다 */
function BarChart({ title, note, bars, max, refLine, empty, unit }: {
  title: string;
  note?: string;
  bars: Bar[];
  max: number;
  refLine?: { value: number; label: string } | null;
  empty: string;
  unit: string;
}) {
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`;
  return (
    <figure className="viz" aria-label={title}>
      <figcaption>
        <span className="viz-title">{title}</span>
        {refLine && bars.length > 0 && <span className="viz-key small muted"><i className="viz-ref-key" aria-hidden="true" />{refLine.label}</span>}
      </figcaption>
      {bars.length === 0 ? (
        <p className="muted small viz-empty">{empty}</p>
      ) : (
        <>
          <div className="bars" role="img" aria-label={`${title}: ${bars.map((b) => `${b.label} ${b.text}`).join(", ")}`}>
            {bars.map((b) => (
              <div className="bar-row" key={b.key} title={b.tip}>
                <span className="bar-label">{b.label}</span>
                <span className="bar-track">
                  <span className="bar-fill" style={{ width: pct(b.value) }} />
                  {refLine && <span className="bar-ref" style={{ left: pct(refLine.value) }} />}
                </span>
                <span className="bar-value">{b.text}</span>
              </div>
            ))}
          </div>
          <details className="viz-table">
            <summary className="small">표로 보기</summary>
            <table>
              <thead><tr><th>답변</th><th>{unit}</th></tr></thead>
              <tbody>{bars.map((b) => <tr key={b.key}><td>{b.label}</td><td>{b.text}</td></tr>)}</tbody>
            </table>
          </details>
        </>
      )}
      {note && bars.length > 0 && <p className="muted small viz-note">{note}</p>}
    </figure>
  );
}

function StatusGrid({ answers, reasons }: { answers: AnswerMetrics[]; reasons: Map<string, Record<string, string>> }) {
  return (
    <figure className="viz" aria-label="코칭 점검 상태">
      <figcaption><span className="viz-title">코칭 점검 상태</span></figcaption>
      <div className="table-scroll">
      <table className="status-grid" aria-label="답변별 코칭 점검 상태">
        <thead>
          <tr><th>답변</th>{CRITERIA.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {answers.map((m) => (
            <tr key={m.id}>
              <th scope="row"><a href={`#answer-${m.id}`} title={m.question}>Q{m.order}</a></th>
              {CRITERIA.map((c) => {
                const st = m.statuses[c.key];
                return (
                  <td key={c.key} title={reasons.get(m.id)?.[c.key] || undefined}>
                    <span className="st"><i className={`st-mark ${STATE_MARK[st].cls}`} aria-hidden="true">{STATE_MARK[st].mark}</i>{st}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </figure>
  );
}

function PointItem({ p }: { p: ImprovementPoint }) {
  return (
    <li>
      <div className="row">
        <strong className="grow">{p.title}</strong>
        {p.source === "coaching" && <span className="chip">코칭 결과</span>}
        <span className="small point-answers">
          {p.answers.map((a, i) => <span key={a.id}>{i > 0 && " · "}<a href={`#answer-${a.id}`}>Q{a.order}</a></span>)}
        </span>
      </div>
      <div className="small muted">{p.evidence}</div>
      {p.answers.filter((a) => a.quote).map((a) => (
        <blockquote className="quote small" key={a.id}>Q{a.order} “{a.quote}”</blockquote>
      ))}
      <div className="small">다음 연습: {p.action}</div>
    </li>
  );
}

export default function ReviewInsights({ s }: { s: PracticeSession }) {
  const ins = useMemo(() => sessionInsights(s), [s]);
  const reasons = useMemo(
    () => new Map(s.answers.map((a) => [a.id, Object.fromEntries((a.coaching_report?.input_status === "legacy_unverified" ? [] : a.coaching_report?.criteria ?? []).map((c) => [c.key, c.reason]))])),
    [s],
  );
  const answered = ins.answers.filter((m) => m.recorded || m.hasTranscript);

  if (answered.length === 0)
    return (
      <section className="card insights">
        <h2 style={{ margin: 0 }}>한눈에 보기</h2>
        <p className="muted small" style={{ marginBottom: 0 }}>아직 답변이 없어요. 답변하면 코칭 상태·답변 시간·말 빠르기·보완점을 여기에 모아 보여 줘요.</p>
      </section>
    );

  const recorded = ins.answers.filter((m) => m.durationSec != null);
  const limit = ins.answers.find((m) => m.limitSec != null)?.limitSec ?? null;
  const timeBars: Bar[] = recorded.map((m) => ({
    key: m.id, label: `Q${m.order}`, value: m.durationSec as number, text: `${Math.round(m.durationSec as number)}초`,
    tip: `Q${m.order} · ${Math.round(m.durationSec as number)}초${m.usage != null ? ` (제한의 ${Math.round(m.usage * 100)}%)` : ""}`,
  }));
  const timeMax = Math.max(limit ?? 0, ...recorded.map((m) => m.durationSec as number), 1);

  const rated = ins.answers.filter((m) => m.spm != null);
  const speedBars: Bar[] = rated.map((m) => ({
    key: m.id, label: `Q${m.order}`, value: m.spm as number, text: `${m.spm}`,
    tip: `Q${m.order} · 분당 ${m.spm}음절${ins.avgSpm != null ? ` (평균 ${Math.round(ins.avgSpm)})` : ""}`,
  }));
  const speedMax = Math.max(...rated.map((m) => m.spm as number), ins.avgSpm ?? 0, 1);
  const speedEmpty = recorded.length === 0
    ? "녹음 답변이 없어 말 빠르기를 계산하지 못했어요."
    : `전사문이 있는 ${MIN_RATE_SEC}초 이상 녹음이 없거나, 전사문이 수정되었거나 녹음과의 연결을 확인하지 못해 말 빠르기를 계산하지 못했어요.`;

  const ratingBars: Bar[] = ins.answers.filter((m) => m.rating != null).map((m) => ({
    key: m.id, label: `Q${m.order}`, value: m.rating as number, text: `${m.rating}점`, tip: `Q${m.order} · 자기 평가 ${m.rating}점`,
  }));

  const { shown, more } = splitPoints(ins.points);

  return (
    <section className="card insights" aria-labelledby="insights-title">
      <h2 id="insights-title" style={{ margin: 0 }}>한눈에 보기</h2>
      <p className="muted small" style={{ marginTop: 4 }}>이 세션의 답변을 정해진 규칙과 코칭 결과로 정리했어요. 점수나 합격 판단이 아니라 다음 연습을 고르기 위한 참고예요.</p>
      <div className="insights-grid">
        <StatusGrid answers={ins.answers} reasons={reasons} />
        <BarChart
          title="답변 시간" unit="녹음 길이" bars={timeBars} max={timeMax}
          refLine={limit != null ? { value: limit, label: `제한 ${limit}초` } : null}
          empty="녹음 답변이 없어 답변 시간을 표시하지 못했어요."
        />
        <BarChart
          title="말 빠르기(분당 음절)" unit="분당 음절" bars={speedBars} max={speedMax}
          refLine={ins.avgSpm != null ? { value: ins.avgSpm, label: `이 세션 평균 ${Math.round(ins.avgSpm)}` } : null}
          empty={speedEmpty}
          note="녹음 길이로 나눠 앞뒤 침묵이 들어 있어요. 실제보다 느리게 나오니 같은 세션 안에서 비교해 보세요."
        />
        <BarChart title="자기 평가" unit="점수(5점 만점)" bars={ratingBars} max={5} empty="자기 평가를 남긴 답변이 없어요." />
      </div>

      <h3 className="insights-sub">보완점</h3>
      {ins.points.length === 0 ? (
        <p className="muted small" data-testid="insight-points">규칙에 걸린 보완점이 없어요. 답변별 코칭 결과는 아래 카드에서 확인할 수 있어요.</p>
      ) : (
        <div data-testid="insight-points">
          <ol className="plain insight-points">{shown.map((p) => <PointItem key={p.key} p={p} />)}</ol>
          {more.length > 0 && (
            <details>
              <summary className="small">보완점 {more.length}개 더 보기</summary>
              <ol className="plain insight-points">{more.map((p) => <PointItem key={p.key} p={p} />)}</ol>
            </details>
          )}
        </div>
      )}
      {ins.untranscribed > 0 && (
        <p className="muted small">녹음했지만 전사문이 없는 답변 {ins.untranscribed}개는 점검하지 못했어요. 전사문을 입력하거나 음성 인식을 다시 시도하면 점검할 수 있어요.</p>
      )}
    </section>
  );
}
