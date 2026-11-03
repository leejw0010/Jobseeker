import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import Diff from "../components/Diff";
import { StageTrack } from "../components/track/StageTrack";
import { StatusChip } from "../components/track/StatusChip";
import { JOB_CATEGORIES, STAGES, STATUSES, type ApplicationDetail, type ApplicationPatch, type EssayItem } from "../types";

/** 한 번에 하나만 보내는 비동기 동작. 실패하면 서버 메시지를 돌려준다(화면 전체를 오류로 바꾸지 않는다) */
function useAction() {
  const running = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, onFail?: () => void) => {
    if (running.current) return;
    running.current = true;
    setPending(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
      onFail?.();
    } finally {
      running.current = false;
      setPending(false);
    }
  };
  return { run, pending, error };
}

function EssayCard({ item, onChange, onDelete }: { item: EssayItem; onChange: (i: EssayItem) => void; onDelete: () => void }) {
  const latest = item.versions[item.versions.length - 1];
  const [draft, setDraft] = useState(latest?.content ?? "");
  const [sel, setSel] = useState<number>(latest?.version_no ?? 0);
  const [compare, setCompare] = useState(false);
  const { run, pending, error: err } = useAction();
  // 입력란에 마지막으로 채운 서버 내용. 입력란이 이 값 그대로일 때만(사용자가 고치지 않았을 때만) 새 최신 버전으로 바꾼다:
  // 저장하는 동안 이어서 쓴 글이 저장 응답에 덮이지 않는다
  const synced = useRef(latest?.content ?? "");

  useEffect(() => {
    const l = item.versions[item.versions.length - 1];
    const next = l?.content ?? "";
    const prevSynced = synced.current;
    synced.current = next;
    setDraft((d) => (d === prevSynced ? next : d));
    setSel(l?.version_no ?? 0);
  }, [item.versions.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = item.versions.find((v) => v.version_no === sel);
  const prev = item.versions.find((v) => v.version_no === sel - 1);
  const over = item.char_limit != null && draft.length > item.char_limit;

  // 저장 응답이 오면 위 effect가 입력란을 맞춘다: 그사이 더 쓴 글은 synced와 달라 그대로 남는다
  const save = (submitted: boolean) => run(async () => onChange(await api.addVersion(item.id, { content: draft, is_submitted: submitted })));
  /** 되돌리기는 사용자가 고른 내용으로 입력란을 바꾸는 동작이다 */
  const restore = (versionId: string, content: string) => run(async () => {
    const next = await api.restoreVersion(versionId);
    setDraft(content);
    synced.current = content;
    onChange(next);
  });

  return (
    <section className="card">
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>{item.question_text}</h3>
        <button className="small danger" disabled={pending} onClick={onDelete}>문항 삭제</button>
      </div>
      <div className="spacer" />
      <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 16 }}>
        <div className="version-list">
          {[...item.versions].reverse().map((v) => (
            <button key={v.id} className={v.version_no === sel ? "sel" : ""} onClick={() => setSel(v.version_no)}>
              <div>v{v.version_no} {v.is_submitted && <span className="chip good">제출</span>}</div>
              <div className="small muted">{new Date(v.created_at).toLocaleDateString("ko-KR")} · {v.char_count}자{v.source === "extension" ? " · 확장" : ""}</div>
            </button>
          ))}
          {item.versions.length === 0 && <p className="small muted">버전 없음</p>}
        </div>
        <div style={{ minWidth: 0 }}>
          {selected && selected.version_no !== latest?.version_no ? (
            <>
              <div className="row small">
                <span className="grow muted">v{selected.version_no} 보기</span>
                {prev && <label style={{ flexDirection: "row", alignItems: "center" }}><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />v{prev.version_no}와 비교</label>}
                <button disabled={pending} onClick={() => restore(selected.id, selected.content)}>이 버전으로 되돌리기</button>
              </div>
              <div className="spacer" />
              {compare && prev ? <Diff before={prev.content} after={selected.content} /> : <div className="diff">{selected.content}</div>}
            </>
          ) : (
            <>
              {latest && prev && (
                <details>
                  <summary className="small muted">직전 버전(v{prev.version_no})과 비교</summary>
                  <Diff before={prev.content} after={latest.content} />
                </details>
              )}
              <textarea style={{ minHeight: 180 }} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="답변을 입력하세요" />
              <div className="row small">
                <span className={`grow ${over ? "err" : "muted"}`}>
                  {draft.length}자{item.char_limit ? ` / ${item.char_limit}자` : ""} (공백 제외 {draft.replace(/\s/g, "").length}자)
                </span>
                <button disabled={pending || !draft || draft === latest?.content} onClick={() => save(false)}>새 버전 저장</button>
                <button className="primary" disabled={pending || !draft} onClick={() => save(true)}>제출본으로 저장</button>
              </div>
            </>
          )}
        </div>
      </div>
      {err && <p className="err">{err}</p>}
    </section>
  );
}

export default function ApplicationPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [a, setA] = useState<ApplicationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ev, setEv] = useState({ stage: "서류", result: "합격", event_date: "", memo: "" });
  const [newEssay, setNewEssay] = useState({ question_text: "", char_limit: "" });

  const reload = () => api.application(id).then(setA).catch((e) => setErr(e.message));
  // 수정·기록·삭제는 한 번에 하나씩 보내고, 실패하면 메시지를 보여 준 뒤 서버 상태로 다시 맞춘다
  const { run, pending, error: actionErr } = useAction();
  useEffect(() => {
    reload();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (a) setEv((e) => ({ ...e, stage: a.stage }));
  }, [a?.stage]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <p className="err">{err}</p>;
  if (!a) return <p className="muted">불러오는 중…</p>;

  const patch = (b: ApplicationPatch) => run(async () => setA(await api.updateApplication(a.id, b)), reload);

  return (
    <>
      <Link to="/track" className="small">← 지원 관리</Link>
      <div className="row">
        <h1 className="grow" style={{ margin: "8px 0" }}>{a.company} · {a.position}</h1>
        <StatusChip status={a.status} />
      </div>
      <StageTrack a={a} />
      <div className="spacer" />

      <div className="grid2">
        <section className="card">
          <h2>기본 정보</h2>
          <div className="row">
            <label className="grow">회사<input defaultValue={a.company} onBlur={(e) => e.target.value !== a.company && patch({ company: e.target.value })} /></label>
            <label className="grow">직무<input defaultValue={a.position} onBlur={(e) => e.target.value !== a.position && patch({ position: e.target.value })} /></label>
          </div>
          <div className="spacer" />
          <div className="row">
            <label>분류
              <select value={a.job_category} onChange={(e) => patch({ job_category: e.target.value })}>
                {[...new Set([...JOB_CATEGORIES, a.job_category])].map((j) => <option key={j}>{j}</option>)}
              </select>
            </label>
            <label>지원일<input type="date" value={a.applied_at ?? ""} onChange={(e) => patch({ applied_at: e.target.value || null })} /></label>
            <label>상태
              <select value={a.status} onChange={(e) => patch({ status: e.target.value as ApplicationDetail["status"] })}>
                {STATUSES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
          </div>
          <div className="spacer" />
          <label>공고 URL<input defaultValue={a.url ?? ""} onBlur={(e) => e.target.value !== (a.url ?? "") && patch({ url: e.target.value || null })} /></label>
          {a.url && <a className="small" href={a.url} target="_blank" rel="noreferrer">공고 열기 ↗</a>}
          <div className="spacer" />
          <label>메모<textarea style={{ minHeight: 70 }} defaultValue={a.notes ?? ""} onBlur={(e) => e.target.value !== (a.notes ?? "") && patch({ notes: e.target.value || null })} /></label>
          <div className="spacer" />
          <div className="row">
            <button onClick={() => nav(`/practice?application=${a.id}`)}>이 지원 건으로 면접 질문 만들기</button>
            <button className="danger" disabled={pending} onClick={() => { if (confirm("지원 건과 자소서 버전을 모두 삭제할까요?")) run(async () => { await api.deleteApplication(a.id); nav("/track"); }); }}>삭제</button>
          </div>
          {actionErr && <p className="err" role="alert">{actionErr}</p>}
        </section>

        <section className="card">
          <h2>단계별 결과</h2>
          <table>
            <tbody>
              {a.events.map((e) => (
                <tr key={e.id}>
                  <td className="muted small">{e.event_date}</td>
                  <td>{e.stage}</td>
                  <td><StatusChip status={e.result === "대기" ? "보류" : e.result} /></td>
                  <td className="small">{e.memo}</td>
                  <td><button className="small danger" disabled={pending} onClick={() => run(async () => { await api.deleteEvent(e.id); await reload(); }, reload)}>×</button></td>
                </tr>
              ))}
              {a.events.length === 0 && <tr><td className="muted">아직 기록이 없습니다.</td></tr>}
            </tbody>
          </table>
          <div className="spacer" />
          <div className="row">
            <select value={ev.stage} onChange={(e) => setEv({ ...ev, stage: e.target.value })}>
              {STAGES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select value={ev.result} onChange={(e) => setEv({ ...ev, result: e.target.value })}>
              <option>합격</option><option>불합격</option><option>대기</option>
            </select>
            <input type="date" value={ev.event_date} onChange={(e) => setEv({ ...ev, event_date: e.target.value })} />
          </div>
          <div className="spacer" />
          <div className="row">
            <input className="grow" placeholder="메모 (예: 면접 질문, 분위기)" value={ev.memo} onChange={(e) => setEv({ ...ev, memo: e.target.value })} />
            <button className="primary" disabled={pending} onClick={() => run(async () => {
              setA(await api.addEvent(a.id, { stage: ev.stage, result: ev.result, event_date: ev.event_date || undefined, memo: ev.memo || undefined }));
              setEv({ ...ev, memo: "" });
            })}>기록</button>
          </div>
          <p className="small muted">합격을 기록하면 다음 단계로 넘어가고, 불합격을 기록하면 상태가 '불합격'이 됩니다.</p>
        </section>
      </div>

      <h2>자기소개서 문항 · 답변 버전</h2>
      {a.essay_items.map((item) => (
        <EssayCard key={item.id} item={item}
          onChange={(next) => setA({ ...a, essay_items: a.essay_items.map((x) => (x.id === next.id ? next : x)) })}
          onDelete={() => { if (confirm("문항과 모든 버전을 삭제할까요?")) run(async () => { await api.deleteEssay(item.id); await reload(); }, reload); }} />
      ))}
      <section className="card">
        <div className="row">
          <input className="grow" placeholder="새 문항 (예: 지원 동기와 입사 후 포부를 서술하시오)" value={newEssay.question_text} onChange={(e) => setNewEssay({ ...newEssay, question_text: e.target.value })} />
          <input style={{ width: 110 }} type="number" placeholder="글자 수 제한" value={newEssay.char_limit} onChange={(e) => setNewEssay({ ...newEssay, char_limit: e.target.value })} />
          <button disabled={pending || !newEssay.question_text.trim()} onClick={() => run(async () => {
            await api.addEssay(a.id, { question_text: newEssay.question_text.trim(), char_limit: newEssay.char_limit ? +newEssay.char_limit : null });
            setNewEssay({ question_text: "", char_limit: "" });
            await reload();
          })}>문항 추가</button>
        </div>
      </section>
    </>
  );
}
