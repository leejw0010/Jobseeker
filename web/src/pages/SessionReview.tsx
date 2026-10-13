import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import Stars from "../components/Stars";
import type { PracticeAnswer, PracticeSession } from "../types";

const STT_LABEL = { none: "녹음 없음", done: "전사 완료", failed: "전사 실패", unavailable: "전사 꺼짐" } as const;

function AnswerCard({ a, onChange }: { a: PracticeAnswer; onChange: (a: PracticeAnswer) => void }) {
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
      </div>
      <div className="spacer" />
      {audio ? <audio controls src={audio} style={{ width: "100%" }} /> : <p className="muted small">녹음이 없습니다.</p>}
      <div className="row small muted">
        <span>{STT_LABEL[a.stt_status]}</span>
        {a.duration_sec != null && <span>· {Math.round(a.duration_sec)}초</span>}
        {cpm != null && <span>· 분당 약 {cpm}자</span>}
        {a.stt_status === "failed" && <button disabled={busy} onClick={() => act(() => api.retryTranscribe(a.id), true)}>전사 다시 시도</button>}
      </div>
      <div className="spacer" />
      <label>전사문 (직접 고칠 수 있어요)
        <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} placeholder="전사문이 없으면 기억나는 대로 적어 두세요." />
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
        <button disabled={busy || !a.transcript} onClick={() => act(() => api.feedback(a.id))}>AI 피드백 받기</button>
      </div>
      {a.ai_feedback && (
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
  useEffect(() => {
    api.session(id).then(setS).catch((e) => setErr(e.message));
  }, [id]);
  if (err) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">불러오는 중…</p>;
  const remaining = s.answers.filter((a) => !a.audio_path).length;

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>{s.title}</h1>
        {remaining > 0 && <Link to={`/practice/sessions/${s.id}/run`}>남은 {remaining}개 이어서 연습</Link>}
        <button className="danger" onClick={async () => { if (confirm("이 연습 기록을 삭제할까요?")) { await api.deleteSession(s.id); nav("/practice/history"); } }}>삭제</button>
      </div>
      <p className="muted small">{new Date(s.created_at).toLocaleString("ko-KR")} · {s.mode === "mock" ? `모의시험 (준비 ${s.prep_sec}초 / 답변 ${s.answer_sec}초)` : "자유 연습"}</p>
      {s.answers.map((a) => (
        <AnswerCard key={a.id} a={a} onChange={(next) => setS({ ...s, answers: s.answers.map((x) => (x.id === next.id ? next : x)) })} />
      ))}
    </>
  );
}
