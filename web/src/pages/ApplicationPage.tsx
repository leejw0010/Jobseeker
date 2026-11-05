import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import Diff from "../components/Diff";
import { StageTrack } from "../components/track/StageTrack";
import { StatusChip } from "../components/track/StatusChip";
import { mergeApplicationDetail, mergeEssayItem } from "../components/track/state";
import { JOB_CATEGORIES, STAGES, STATUSES, type ApplicationDetail, type ApplicationPatch, type EssayItem, type StageEvent } from "../types";

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
    <section className="card" aria-label={item.question_text}>
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>{item.question_text}</h3>
        <button className="small danger" disabled={pending} onClick={onDelete}>문항 삭제</button>
      </div>
      <div className="spacer" />
      <p className="small muted">{item.submission_confirmation === "confirmed" ? `최근 확인한 제출본: v${item.versions.find((v) => v.id === item.submitted_version_id)?.version_no ?? "–"}` : item.submission_confirmation === "legacy_unverified" ? "이전 제출 표시 · 제출본 확인 필요" : "확인한 제출본 없음"}</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        <div className="version-list" style={{ flex: "0 1 150px" }}>
          {[...item.versions].reverse().map((v) => (
            <button key={v.id} className={v.version_no === sel ? "sel" : ""} onClick={() => setSel(v.version_no)}>
              <div>v{v.version_no} {v.is_submitted && <span className="chip good">제출</span>}</div>
              <div className="small muted">{new Date(v.created_at).toLocaleDateString("ko-KR")} · {v.char_count}자{v.source === "extension" ? " · 확장" : ""}</div>
            </button>
          ))}
          {item.versions.length === 0 && <p className="small muted">버전 없음</p>}
        </div>
        <div style={{ minWidth: 0, flex: "1 1 240px" }}>
          {selected && selected.version_no !== latest?.version_no ? (
            <>
              <div className="row small">
                <span className="grow muted">v{selected.version_no} 보기</span>
                {prev && <label style={{ flexDirection: "row", alignItems: "center" }}><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />v{prev.version_no}와 비교</label>}
                <button disabled={pending} onClick={() => run(async () => onChange(await api.submitVersion(selected.id)))}>이 버전을 제출본으로 확인</button>
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
              <textarea aria-label={`${item.question_text} 답변`} style={{ minHeight: 180 }} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="답변을 입력하세요" />
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

function BasicInfo({ a, save, pending }: { a: ApplicationDetail; save: (body: ApplicationPatch) => Promise<unknown>; pending: boolean }) {
  const values = () => ({ company: a.company, position: a.position, job_category: a.job_category, applied_at: a.applied_at ?? "", stage: a.stage, status: a.status, url: a.url ?? "", notes: a.notes ?? "" });
  const [draft, setDraft] = useState(values);
  const synced = useRef(draft);
  useEffect(() => {
    const next = values();
    const previous = synced.current;
    synced.current = next;
    // Update untouched controls after event calculations while preserving unsaved edits.
    setDraft((current) => Object.fromEntries(Object.keys(next).map((key) => {
      const field = key as keyof typeof next;
      return [field, current[field] === previous[field] ? next[field] : current[field]];
    })) as typeof next);
  }, [a]); // eslint-disable-line react-hooks/exhaustive-deps
  return <>
    <div className="row">
      <label className="grow">회사<input value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
      <label className="grow">직무<input value={draft.position} onChange={(e) => setDraft({ ...draft, position: e.target.value })} /></label>
    </div>
    <div className="row">
      <label>분류<select value={draft.job_category} onChange={(e) => setDraft({ ...draft, job_category: e.target.value })}>{[...new Set([...JOB_CATEGORIES, draft.job_category])].map((job) => <option key={job}>{job}</option>)}</select></label>
      <label>지원일<input type="date" value={draft.applied_at} onChange={(e) => setDraft({ ...draft, applied_at: e.target.value })} /></label>
      <label>현재 단계<select value={draft.stage} onChange={(e) => setDraft({ ...draft, stage: e.target.value as ApplicationDetail["stage"] })}>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</select></label>
      <label>상태<select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as ApplicationDetail["status"] })}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></label>
    </div>
    <label>공고 URL<input value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} /></label>
    {a.url && <a className="small" href={a.url} target="_blank" rel="noreferrer">공고 열기 ↗</a>}
    <label>메모<textarea value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
    <button className="primary" disabled={pending || !draft.company.trim() || !draft.position.trim()} onClick={() => {
      const body: ApplicationPatch = { company: draft.company, position: draft.position, job_category: draft.job_category, applied_at: draft.applied_at || null, url: draft.url || null, notes: draft.notes || null };
      if (draft.stage !== a.stage) body.stage = draft.stage;
      if (draft.status !== a.status) body.status = draft.status;
      void save(body);
    }}>기본 정보 저장</button>
    <p className="small muted">단계나 상태를 직접 바꾸면 수동 상태로 유지됩니다.</p>
  </>;
}

export default function ApplicationPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [a, setA] = useState<ApplicationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const route = useRef({ id, generation: 0 });
  const deletedEssays = useRef(new Set<string>());
  if (route.current.id !== id) {
    route.current = { id, generation: route.current.generation + 1 };
    deletedEssays.current = new Set();
  }
  const generation = route.current.generation;
  const currentId = useRef(id);
  currentId.current = id;
  const latestRequest = useRef(0);
  const [editing, setEditing] = useState<StageEvent | null>(null);
  const [baseline, setBaseline] = useState({ stage: "서류", status: "진행중" });
  const [ev, setEv] = useState({ stage: "서류", result: "합격", event_date: "", memo: "" });
  const [newEssay, setNewEssay] = useState({ question_text: "", char_limit: "" });

  // Full-detail actions and individual cards can complete independently.
  const applyDetail = (next: ApplicationDetail) => {
    setA((current) => route.current.generation === generation && next.id === route.current.id
      ? mergeApplicationDetail(current, next, deletedEssays.current)
      : current);
  };
  const applyEssay = (next: EssayItem, allowAdd = false) => {
    setA((current) => {
      if (current?.id !== id || route.current.generation !== generation || deletedEssays.current.has(next.id)) return current;
      const exists = current.essay_items.some((item) => item.id === next.id);
      return { ...current, essay_items: exists
        ? current.essay_items.map((item) => item.id === next.id ? mergeEssayItem(item, next) : item)
        : allowAdd ? [...current.essay_items, next] : current.essay_items };
    });
  };
  const reload = () => {
    const request = ++latestRequest.current;
    return api.application(id).then((next) => { if (route.current.generation === generation && request === latestRequest.current) { applyDetail(next); setErr(null); } }).catch((e) => { if (route.current.generation === generation && request === latestRequest.current) setErr(e.message); });
  };
  // 수정·기록·삭제는 한 번에 하나씩 보내고, 실패하면 메시지를 보여 준 뒤 서버 상태로 다시 맞춘다
  const { run, pending, error: actionErr } = useAction();
  useEffect(() => {
    setA(null);
    setErr(null);
    setEditing(null);
    reload();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (a) setEv((e) => ({ ...e, stage: a.stage }));
  }, [a?.stage]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <p className="err">{err}</p>;
  if (!a) return <p className="muted">불러오는 중…</p>;

  const requiresBaseline = a.state_requires_baseline ?? a.state_source === "legacy";
  const patch = async (b: ApplicationPatch) => { const next = await api.updateApplication(a.id, b); if (currentId.current === next.id && route.current.generation === generation) applyDetail(next); };

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
          <BasicInfo key={a.id} a={a} save={(body) => run(() => patch(body))} pending={pending} />
          <div className="row">
            <button onClick={() => nav(`/practice?application=${a.id}`)}>이 지원 건으로 면접 질문 만들기</button>
            <button className="danger" disabled={pending} onClick={() => { if (confirm("지원 건과 자소서 버전을 모두 삭제할까요?")) run(async () => { await api.deleteApplication(a.id); if (currentId.current === a.id && route.current.generation === generation) nav("/track"); }); }}>삭제</button>
          </div>
          {actionErr && <p className="err" role="alert">{actionErr}</p>}
        </section>

        <section className="card">
          <h2>단계별 결과</h2>
          <div className="table-scroll"><table>
            <tbody>
              {a.events.map((e) => (
                <tr key={e.id}>
                  <td className="muted small">{e.event_date}</td>
                  <td>{e.stage}</td>
                  <td><StatusChip status={e.result === "대기" ? "보류" : e.result} /></td>
                  <td className="small">{e.memo}</td>
                  <td><button className="small" disabled={pending} onClick={() => setEditing(e)}>수정</button><button aria-label={`${e.stage} ${e.event_date} 기록 삭제`} className="small danger" disabled={pending} onClick={() => run(async () => { await api.deleteEvent(e.id); await reload(); }, reload)}>×</button></td>
                </tr>
              ))}
              {a.events.length === 0 && <tr><td className="muted">아직 기록이 없습니다.</td></tr>}
            </tbody>
          </table></div>
          {editing && <div className="card">
            <h3>기록 수정</h3>
            <label>수정 단계<select value={editing.stage} onChange={(e) => setEditing({ ...editing, stage: e.target.value as StageEvent["stage"] })}>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</select></label>
            <label>수정 결과<select value={editing.result} onChange={(e) => setEditing({ ...editing, result: e.target.value as StageEvent["result"] })}><option>합격</option><option>불합격</option><option>대기</option></select></label>
            <label>수정 날짜<input type="date" value={editing.event_date} onChange={(e) => setEditing({ ...editing, event_date: e.target.value })} /></label>
            <label>수정 메모<input value={editing.memo ?? ""} onChange={(e) => setEditing({ ...editing, memo: e.target.value })} /></label>
            <button disabled={pending || !editing.event_date} onClick={() => run(async () => { await api.updateEvent(editing.id, { stage: editing.stage, result: editing.result, event_date: editing.event_date, memo: editing.memo }); setEditing(null); await reload(); })}>기록 수정 저장</button>
            <button disabled={pending} onClick={() => setEditing(null)}>취소</button>
          </div>}
          <div className="spacer" />
          <div className="row">
            <select aria-label="기록 단계" value={ev.stage} onChange={(e) => setEv({ ...ev, stage: e.target.value })}>
              {STAGES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select aria-label="기록 결과" value={ev.result} onChange={(e) => setEv({ ...ev, result: e.target.value })}>
              <option>합격</option><option>불합격</option><option>대기</option>
            </select>
            <input aria-label="기록 날짜" type="date" value={ev.event_date} onChange={(e) => setEv({ ...ev, event_date: e.target.value })} />
          </div>
          <div className="spacer" />
          <div className="row">
            <input className="grow" placeholder="메모 (예: 면접 질문, 분위기)" value={ev.memo} onChange={(e) => setEv({ ...ev, memo: e.target.value })} />
            <button className="primary" disabled={pending} onClick={() => run(async () => {
              const next = await api.addEvent(a.id, { stage: ev.stage, result: ev.result, event_date: ev.event_date || undefined, memo: ev.memo || undefined });
              if (currentId.current === a.id && route.current.generation === generation) applyDetail(next);
              setEv({ ...ev, memo: "" });
            })}>기록</button>
          </div>
          <p className="small muted">{a.state_source === "events" ? "기록 날짜 순서로 현재 단계와 상태를 계산합니다. 합격은 다음 단계로 넘어갑니다." : a.state_source === "manual" ? "수동으로 정한 단계와 상태를 유지합니다. 기록을 추가·수정·삭제해도 현재 상태는 바뀌지 않습니다." : "이전 데이터의 현재 상태를 유지합니다. 기록 계산으로 전환하려면 기록 전 기준을 직접 선택하세요."}</p>
          {a.state_source !== "events" && <div>
            {requiresBaseline && <>
              <label>기록 전 기준 단계<select value={baseline.stage} onChange={(e) => setBaseline({ ...baseline, stage: e.target.value })}>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</select></label>
              <label>기록 전 기준 상태<select value={baseline.status} onChange={(e) => setBaseline({ ...baseline, status: e.target.value })}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></label>
            </>}
            <button disabled={pending} onClick={() => run(async () => { await api.useEventState(a.id, requiresBaseline ? { baseline_stage: baseline.stage as ApplicationDetail["stage"], baseline_status: baseline.status as ApplicationDetail["status"] } : {}); await reload(); })}>기록으로 현재 상태 계산</button>
          </div>}
        </section>
      </div>

      <h2>자기소개서 문항 · 답변 버전</h2>
      {a.essay_items.map((item) => (
        <EssayCard key={item.id} item={item}
          onChange={(next) => applyEssay(next)}
          onDelete={() => { if (confirm("문항과 모든 버전을 삭제할까요?")) run(async () => {
            await api.deleteEssay(item.id);
            if (route.current.generation !== generation) return;
            deletedEssays.current.add(item.id);
            setA((current) => current?.id === id ? { ...current, essay_items: current.essay_items.filter((essay) => essay.id !== item.id) } : current);
            await reload();
          }, reload); }} />
      ))}
      <section className="card">
        <div className="row">
          <input aria-label="새 자소서 문항" className="grow" placeholder="새 문항 (예: 지원 동기와 입사 후 포부를 서술하시오)" value={newEssay.question_text} onChange={(e) => setNewEssay({ ...newEssay, question_text: e.target.value })} />
          <input aria-label="글자 수 제한" style={{ width: 110 }} type="number" placeholder="글자 수 제한" value={newEssay.char_limit} onChange={(e) => setNewEssay({ ...newEssay, char_limit: e.target.value })} />
          <button disabled={pending || !newEssay.question_text.trim()} onClick={() => run(async () => {
            const next = await api.addEssay(a.id, { question_text: newEssay.question_text.trim(), char_limit: newEssay.char_limit ? +newEssay.char_limit : null });
            applyEssay(next, true);
            if (route.current.generation === generation) setNewEssay({ question_text: "", char_limit: "" });
            await reload();
          })}>문항 추가</button>
        </div>
      </section>
    </>
  );
}
