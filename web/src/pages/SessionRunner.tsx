import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import ConsentPanel from "../components/ConsentPanel";
import InterviewContext from "../components/InterviewContext";
import { useRecorder } from "../components/useRecorder";
import type { PracticeAnswer, PracticeSession, PracticeSettings } from "../types";

type Phase = "ready" | "prep" | "answer" | "uploading" | "reviewing";
const fmt = (s: number) => `${Math.floor(Math.max(0, Math.ceil(s)) / 60)}:${String(Math.max(0, Math.ceil(s)) % 60).padStart(2, "0")}`;

export default function SessionRunner() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("ready");
  const [left, setLeft] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [inputMode, setInputMode] = useState<"audio" | "text">("audio");
  const [draft, setDraft] = useState("");
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [busy, setBusy] = useState(false);
  const [uploadFailed, setUploadFailed] = useState(false);
  // 녹음 동의: 녹음으로 답할 때만 필요하다(글 답변에는 묻지 않는다)
  const [consent, setConsent] = useState<"checking" | "ok" | "needed">("checking");
  const [prefs, setPrefs] = useState<PracticeSettings | null>(null);
  // 서버가 403(동의 없음)을 돌려준 동작. 동의하면 이어서 다시 한다
  const [consentFor, setConsentFor] = useState<"upload" | "transcribe" | null>(null);
  const rec = useRecorder();
  const { start, stop, ensureStream } = rec;
  const deadline = useRef(0);
  const processing = useRef(false);
  const pendingAudio = useRef<{ blob: Blob; durationSec: number } | null>(null);

  useEffect(() => {
    let alive = true;
    api.session(id).then((s) => {
      if (!alive) return;
      setSession(s);
      if (s.finished_at) { nav(`/practice/sessions/${id}`, { replace: true }); return; }
      // 원본 녹음은 전사가 끝나면 지워질 수 있으니 녹음 여부는 recorded_at으로 본다
      const next = s.answers.findIndex((a) => !a.recorded_at && !a.transcript?.trim());
      setIdx(next === -1 ? Math.max(0, s.answers.length - 1) : next);
      if (next === -1) {
        setDraft(s.answers[s.answers.length - 1]?.transcript ?? "");
        setPhase("reviewing");
      } else setPhase("ready");
    }).catch((e) => setErr(e.message));
    return () => { alive = false; };
  }, [id, nav]);

  /** 설정을 불러온다. 못 불러와도 연습은 막지 않는다(업로드가 403이면 그때 동의를 받는다). */
  const loadPrefs = useCallback(() => api.settings().then((st) => { setPrefs(st); return st; }), []);
  useEffect(() => {
    loadPrefs().then((st) => setConsent(st.consented_at ? "ok" : "needed")).catch(() => setConsent("ok"));
  }, [loadPrefs]);
  /** 다른 곳에서 동의를 철회한 경우: 서버가 녹음을 받지 않았다. 동의하면 같은 동작을 다시 한다 */
  const askConsent = useCallback((action: "upload" | "transcribe") => {
    setConsent("needed");
    setConsentFor(action);
    loadPrefs().catch(() => {}); // 동의 패널의 보관 체크를 지금 설정으로
  }, [loadPrefs]);

  const mock = session?.mode === "mock";
  const answer = session?.answers[idx];
  const updateAnswer = useCallback((a: PracticeAnswer) => {
    setSession((s) => s ? { ...s, answers: s.answers.map((x) => x.id === a.id ? a : x) } : s);
  }, []);

  const finishAnswer = useCallback(async () => {
    if (!answer || processing.current) return;
    processing.current = true;
    setPhase("uploading");
    setErr(null);
    try {
      let saved: PracticeAnswer;
      if (inputMode === "audio") {
        pendingAudio.current ??= await stop();
        const recording = pendingAudio.current;
        if (!recording?.blob.size) throw new Error("녹음된 소리가 없어요. 글로 답변하거나 다시 녹음해 주세요.");
        saved = await api.uploadAudio(answer.id, recording.blob, recording.durationSec);
        pendingAudio.current = null;
      } else {
        saved = await api.reflect(answer.id, { transcript: draftRef.current.trim() || null });
      }
      updateAnswer(saved);
      setDraft(saved.transcript ?? "");
      setUploadFailed(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) askConsent("upload");
      else setErr((e as Error).message);
      setUploadFailed(inputMode === "audio" && !!pendingAudio.current);
    } finally {
      processing.current = false;
      setPhase("reviewing");
    }
  }, [answer, askConsent, inputMode, stop, updateAnswer]);

  const beginAnswer = useCallback(async () => {
    try {
      if (inputMode === "audio") await start();
      setPhase("answer");
      if (session) {
        deadline.current = performance.now() + session.answer_sec * 1000;
        setLeft(session.answer_sec);
      }
    } catch { setPhase("ready"); }
  }, [inputMode, start, session]);

  const beginQuestion = async () => {
    if (!session) return;
    setErr(null);
    setDraft("");
    setUploadFailed(false);
    setConsentFor(null); // 앞 질문에서 띄운 동의 패널(다시 전사 등)은 이 질문과 상관없다
    try { if (inputMode === "audio") await ensureStream(); } catch { return; }
    if (mock && session.prep_sec > 0) {
      deadline.current = performance.now() + session.prep_sec * 1000;
      setLeft(session.prep_sec);
      setPhase("prep");
    } else await beginAnswer();
  };

  useEffect(() => {
    if (phase !== "prep" && !(phase === "answer" && mock)) return;
    const t = setInterval(() => {
      const remain = (deadline.current - performance.now()) / 1000;
      setLeft(remain);
      if (remain <= 0) { clearInterval(t); void (phase === "prep" ? beginAnswer() : finishAnswer()); }
    }, 200);
    return () => clearInterval(t);
  }, [phase, mock, beginAnswer, finishAnswer]);

  useEffect(() => {
    if (phase !== "answer" || mock) return;
    const began = performance.now();
    const t = setInterval(() => setLeft((performance.now() - began) / 1000), 250);
    return () => clearInterval(t);
  }, [phase, mock]);

  const retranscribe = async () => {
    if (!answer || processing.current) return;
    processing.current = true; setBusy(true); setErr(null);
    // 입력란이 서버 전사문과 같은가(고친 내용은 아래에서 먼저 저장한다). 저장하지 못했으면 다시 맞출 때 입력란을 덮지 않는다
    let saved = draft === (answer.transcript ?? "");
    try {
      if (!saved) { updateAnswer(await api.reflect(answer.id, { transcript: draft.trim() || null })); saved = true; }
      const recognized = await api.retryTranscribe(answer.id);
      updateAnswer(recognized); setDraft(recognized.transcript ?? draft);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) askConsent("transcribe");
      else setErr((e as Error).message);
      // 서버 상태로 다시 맞춘다: 그 사이 원본이 지워졌으면(404) '녹음은 보관되어 있어요'와 다시 시도 버튼을 내린다.
      // 실패해도 서버가 이미 얻은 전사문을 남겼을 수 있다(전사 중 동의 철회): 입력란도 맞춘다. 맞추지 않으면 '다음 질문'이
      // 입력란과 다르다고 보고 그 전사문을 빈 입력란으로 덮어쓴다. 다 맞출 때까지 입력란은 잠가 둔다(busy)
      const cur = await api.session(id).then((s) => s.answers.find((x) => x.id === answer.id)).catch(() => undefined);
      if (cur) {
        updateAnswer(cur);
        if (saved) setDraft(cur.transcript ?? "");
      }
    }
    finally { processing.current = false; setBusy(false); }
  };

  const consentPanel = (notice: string | null, buttonLabel: string, then: () => void) => (
    <ConsentPanel retentionDays={prefs?.retention_days} initialKeepAudio={prefs?.keep_audio} notice={notice} buttonLabel={buttonLabel}
      onConsented={(st) => { setPrefs(st); setConsent("ok"); setConsentFor(null); setErr(null); then(); }} />
  );

  const next = async (withFollowup = false, save = true) => {
    if (!answer || !session || processing.current) return;
    processing.current = true;
    setBusy(true);
    setErr(null);
    try {
      if (save && draft !== (answer.transcript ?? "")) {
        updateAnswer(await api.reflect(answer.id, { transcript: draft.trim() || null }));
      }
      if (withFollowup) {
        const updated = await api.followup(answer.id);
        setSession(updated);
        setIdx(updated.answers.findIndex((a) => a.parent_answer_id === answer.id));
      } else if (idx + 1 < session.answers.length) setIdx(idx + 1);
      else {
        await api.finishSession(session.id);
        nav(`/practice/sessions/${session.id}`);
        return;
      }
      setDraft("");
      setConsentFor(null); // 앞 답변의 동의 패널을 다음 질문에 남기지 않는다
      setPhase("ready");
    } catch (e) { setErr((e as Error).message); }
    finally { processing.current = false; setBusy(false); }
  };

  if (err && !session) return <p className="err">{err}</p>;
  if (!session || consent === "checking") return <p className="muted">불러오는 중…</p>;
  if (!answer) return <div className="card"><Link to={`/practice/sessions/${id}`}>답변 다시 보기</Link></div>;
  return <>
    <div className="row"><h1 className="grow">{session.title}</h1><span className="muted">{idx + 1} / {session.answers.length}</span></div>
    <InterviewContext context={session.context_snapshot} />
    <section className="card">
      <div className="row small"><span className="chip">{answer.question.category}</span>{mock && <span className="chip accent">모의시험</span>}{answer.parent_answer_id && <span className="chip accent">꼬리질문</span>}</div>
      {answer.followup_reason && <p className="followup-reason">{answer.followup_reason}</p>}
      <div className="runner-q">{answer.question.text}</div>
      {phase === "ready" && <>
        <div className="row input-choice">
          <label className="check-label"><input type="radio" name="input-mode" checked={inputMode === "audio"} onChange={() => setInputMode("audio")} />녹음으로 답변</label>
          <label className="check-label"><input type="radio" name="input-mode" checked={inputMode === "text"} onChange={() => setInputMode("text")} />글로 답변</label>
        </div>
        {inputMode === "audio" && consent === "needed" ? <>
          {consentPanel(null, "동의하고 시작", () => void beginQuestion())}
          <div className="row"><button disabled={busy} onClick={() => next(false, false)}>건너뛰기</button></div>
        </> : <div className="row"><button className="primary" onClick={beginQuestion}>답변 시작</button><button disabled={busy} onClick={() => next(false, false)}>건너뛰기</button></div>}
      </>}
      {phase === "prep" && <><p className="phase">답변 준비 시간</p><div className="timer">{fmt(left)}</div><button className="primary" onClick={beginAnswer}>바로 답변 시작</button></>}
      {phase === "answer" && <>
        <p className="phase">{inputMode === "audio" ? "녹음 중" : "답변 작성 중"} · {mock ? "남은 시간" : "경과 시간"}</p><div className="timer">{fmt(left)}</div>
        {inputMode === "audio" ? <div className="level" aria-label="마이크 입력 레벨"><div style={{ width: `${rec.level * 100}%` }} /></div> :
          <label>내 답변<textarea autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="질문에 대한 답변을 적어 주세요." /></label>}
        <div className="spacer" /><button className="primary" onClick={finishAnswer}>답변 끝내기</button>
      </>}
      {phase === "uploading" && <p role="status">답변을 저장하는 중…</p>}
      {phase === "reviewing" && <>
        {answer.audio_available && answer.stt_status !== "done" && <div className="row small">
          <p className="muted grow">{answer.stt_status === "failed" ? "말소리를 인식하지 못했거나 전사 요청이 실패했어요. 녹음은 보관되어 있어요." : "자동 음성 인식이 연결되지 않았어요. 녹음을 보관하고 있으니 직접 입력하거나 연결 후 다시 시도할 수 있어요."}
            {prefs && ` 원본은 ${prefs.retention_days}일이 지나면 자동으로 지워져요.`}</p>
          <button disabled={busy || uploadFailed} onClick={retranscribe}>음성 인식 다시 시도</button>
        </div>}
        {answer.recorded_at && answer.audio_deleted_at && <p className="small muted">
          {answer.transcript?.trim() ? "원본 녹음은 지웠어요. 전사문만 남겨요." : "원본 녹음은 지웠어요. 답변을 직접 입력해 주세요."}</p>}
        {consentFor === "upload" && uploadFailed && consentPanel("녹음을 저장하려면 먼저 동의가 필요해요. 동의하면 방금 녹음을 저장해요.", "동의하고 녹음 저장", () => void finishAnswer())}
        {/* 다시 전사할 원본이 있을 때만 묻는다(글 답변이거나 원본을 지웠으면 동의해도 할 일이 없다) */}
        {consentFor === "transcribe" && answer.audio_available && consentPanel("녹음을 다시 전사하려면 먼저 녹음 동의가 필요해요.", "동의하고 다시 전사", () => void retranscribe())}
        <label>답변 확인 · 전사문을 고칠 수 있어요<textarea disabled={busy} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="녹음의 전사문이 없으면 답변을 직접 입력해 주세요." /></label>
        <p className="small muted">확인한 답변을 저장하고 다음 단계로 진행해요.</p>
        {uploadFailed && consentFor !== "upload" && <button onClick={finishAnswer}>녹음 저장 다시 시도</button>}
        {inputMode === "audio" && (uploadFailed || !answer.recorded_at) && <button onClick={() => {
          pendingAudio.current = null; setUploadFailed(false); setInputMode("text"); setErr(null); setConsentFor(null);
        }}>녹음 대신 글로 답변</button>}
        <div className="row">
          <button disabled={busy || uploadFailed || !draft.trim()} onClick={async () => {
            setBusy(true); setErr(null);
            try { updateAnswer(await api.reflect(answer.id, { transcript: draft.trim() })); }
            catch (e) { setErr((e as Error).message); }
            finally { setBusy(false); }
          }}>답변만 저장</button>
          {session.followups_enabled && !answer.parent_answer_id && <button className="primary" disabled={busy || uploadFailed || !draft.trim()} onClick={() => next(true)}>꼬리질문 받기</button>}
          <button disabled={busy || uploadFailed} onClick={() => next()}>{idx + 1 < session.answers.length ? "다음 질문" : "면접 마치고 회고 보기"}</button>
        </div>
        {busy && <p className="small muted" role="status">답변을 확인하고 다음 질문을 준비하는 중…</p>}
      </>}
      {(rec.error || err) && <p className="err" role="alert">{err || rec.error}</p>}
    </section>
    <Link className="small" to={`/practice/sessions/${id}`}>지금까지 저장한 답변 보기</Link>
  </>;
}
