import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import Stars from "../components/Stars";
import CoachingPanel from "../components/CoachingPanel";
import InterviewContext from "../components/InterviewContext";
import type { InterviewContext as Context, PracticeAnswer, PracticeSession } from "../types";

const STT_LABEL = { none: "녹음 없음", done: "음성 인식 완료", failed: "음성 인식 재시도 필요", unavailable: "자동 전사 미연결" } as const;

function AnswerCard({ a, context, onChange }: { a: PracticeAnswer; context: Context | null; onChange: (a: PracticeAnswer) => void }) {
  const [audio, setAudio] = useState<string | null>(null);
  const [transcript, setTranscript] = useState(a.transcript ?? "");
  const [note, setNote] = useState(a.reflection_note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!a.audio_path) return;
    let url: string | null = null;
    api.audioUrl(a.id).then((u) => setAudio((url = u))).catch(() => {});
    return () => {
      url && URL.revokeObjectURL(url);
    };
  }, [a.id, a.audio_path]);

  /** syncText: 서버가 전사문을 새로 만든 경우에만 입력란을 덮어쓴다(작성 중인 내용 보호). */
  const act = async (fn: () => Promise<PracticeAnswer>, syncText = false) => {
    setBusy(true);
    setErr(null);
    try {
      const next = await fn();
      onChange(next);
      if (syncText) setTranscript(next.transcript ?? "");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const dirty = transcript !== (a.transcript ?? "") || note !== (a.reflection_note ?? "");
  // 한국어 발화 속도 참고용: 전사 글자 수 / 분
  const cpm = a.transcript && a.duration_sec ? Math.round((a.transcript.replace(/\s/g, "").length / a.duration_sec) * 60) : null;

  return (
    <section className="card">
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>Q{a.order_no}. {a.question.text}</h3>
        <span className="chip">{a.question.category}</span>
        {a.parent_answer_id && <span className="chip accent">꼬리질문</span>}
      </div>
      <div className="spacer" />
      {audio ? <audio controls src={audio} style={{ width: "100%" }} /> : <p className="muted small">녹음이 없습니다.</p>}
      <div className="row small muted">
        <span>{STT_LABEL[a.stt_status]}</span>
        {a.duration_sec != null && <span>· {Math.round(a.duration_sec)}초</span>}
        {cpm != null && <span>· 분당 약 {cpm}자</span>}
        {a.audio_path && (a.stt_status === "failed" || a.stt_status === "unavailable") && <button disabled={busy} onClick={() => act(async () => {
          if (dirty) onChange(await api.reflect(a.id, { transcript: transcript || null, reflection_note: note || null }));
          return api.retryTranscribe(a.id);
        }, true)}>음성 인식 다시 시도</button>}
      </div>
      <div className="spacer" />
      <label>전사문 (직접 고칠 수 있어요)
        <textarea disabled={busy} value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="전사문이 없으면 기억나는 대로 적어 두세요." />
      </label>
      <div className="spacer" />
      <div className="row">
        <span className="small muted">자기 평가</span>
        <Stars value={a.self_rating} onChange={(v) => act(() => api.reflect(a.id, { self_rating: v }))} />
      </div>
      <label>회고 메모
        <textarea style={{ minHeight: 70 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="다음엔 무엇을 바꿀지" />
      </label>
      <div className="spacer" />
      <div className="row">
        <button className="primary" disabled={busy || !dirty} onClick={() => act(() => api.reflect(a.id, { transcript: transcript || null, reflection_note: note || null }))}>저장</button>
        <button disabled={busy || !transcript.trim()} onClick={() => act(async () => {
          if (dirty) await api.reflect(a.id, { transcript: transcript || null, reflection_note: note || null });
          return api.coach(a.id);
        })}>{busy ? "점검 중…" : "답변 점검"}</button>
      </div>
      {a.coaching_report && <CoachingPanel report={a.coaching_report} context={context} />}
      {a.ai_feedback && !a.coaching_report && (
        <>
          <div className="spacer" />
          <div className="card" style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{a.ai_feedback}</div>
        </>
      )}
      {err && <p className="err">{err}</p>}
    </section>
  );
}

export default function SessionReview() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [s, setS] = useState<PracticeSession | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.session(id).then(setS).catch((e) => setErr(e.message));
  }, [id]);
  if (err && !s) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">불러오는 중…</p>;
  const remaining = s.answers.filter((a) => !a.audio_path && !a.transcript?.trim()).length;
  const weak = s.answers.filter((a) => a.coaching_report?.criteria.some((c) => c.status === "보완")).length;

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>{s.title}</h1>
        {!s.finished_at && <Link to={`/practice/sessions/${s.id}/run`}>{remaining > 0 ? `남은 ${remaining}개 이어서 연습` : "면접 이어서 마치기"}</Link>}
        <button className="danger" onClick={async () => { if (confirm("이 연습 기록을 삭제할까요?")) { await api.deleteSession(s.id); nav("/practice/history"); } }}>삭제</button>
      </div>
      <p className="muted small">{new Date(s.created_at).toLocaleString("ko-KR")} · {s.mode === "mock" ? `모의시험 (준비 ${s.prep_sec}초 / 답변 ${s.answer_sec}초)` : "자유 연습"}</p>
      {err && <p className="err">{err}</p>}
      <InterviewContext context={s.context_snapshot} />
      <section className="card review-summary">
        <h2>다음 연습으로 연결하기</h2>
        <p className="small muted">답변을 점검하면 보완할 부분을 확인할 수 있어요. 이전 기록은 보관하고 같은 기준 자료로 다시 연습해요.</p>
        <button className="primary" disabled={busy || !weak} onClick={async () => {
          setBusy(true); setErr(null);
          try { const drill = await api.redrill(s.id); nav(`/practice/sessions/${drill.id}/run`); }
          catch (e) { setErr((e as Error).message); }
          finally { setBusy(false); }
        }}>보완 항목 {weak}개 다시 연습</button>
      </section>
      {s.answers.map((a) => (
        <AnswerCard key={a.id} a={a} context={s.context_snapshot} onChange={(next) => setS((current) => current ? { ...current, answers: current.answers.map((x) => (x.id === next.id ? next : x)) } : current)} />
      ))}
    </>
  );
}
