import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useRecorder } from "../components/useRecorder";
import type { PracticeSession } from "../types";

type Phase = "ready" | "prep" | "answer" | "uploading" | "done";

const fmt = (s: number) => {
  const t = Math.max(0, Math.ceil(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};

export default function SessionRunner() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("ready");
  const [left, setLeft] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const rec = useRecorder();
  const deadline = useRef(0);

  useEffect(() => {
    api.session(id).then((s) => {
      setSession(s);
      // 이미 녹음한 질문은 건너뛰고 이어서 진행
      const next = s.answers.findIndex((a) => !a.audio_path);
      setIdx(next === -1 ? s.answers.length : next);
      if (next === -1) setPhase("done");
    }).catch((e) => setErr(e.message));
  }, [id]);

  const mock = session?.mode === "mock";
  const answer = session?.answers[idx];

  const finishAnswer = useCallback(async () => {
    if (!answer) return;
    setPhase("uploading");
    const result = await rec.stop();
    try {
      if (result && result.blob.size > 0) await api.uploadAudio(answer.id, result.blob, result.durationSec);
    } catch (e) {
      setErr(`녹음 업로드 실패: ${(e as Error).message}`);
    }
    if (session && idx + 1 >= session.answers.length) {
      await api.finishSession(session.id);
      setPhase("done");
      nav(`/practice/sessions/${session.id}`);
    } else {
      setIdx((i) => i + 1);
      setPhase("ready");
    }
  }, [answer, idx, nav, rec, session]);

  const beginAnswer = useCallback(async () => {
    try {
      await rec.start();
    } catch {
      return;
    }
    setPhase("answer");
    if (session) {
      deadline.current = performance.now() + session.answer_sec * 1000;
      setLeft(session.answer_sec);
    }
  }, [rec, session]);

  const beginQuestion = useCallback(async () => {
    if (!session) return;
    try {
      await rec.ensureStream();
    } catch {
      return;
    }
    if (mock && session.prep_sec > 0) {
      setPhase("prep");
      deadline.current = performance.now() + session.prep_sec * 1000;
      setLeft(session.prep_sec);
    } else {
      beginAnswer();
    }
  }, [beginAnswer, mock, rec, session]);

  // 모의시험: 준비 시간이 끝나면 녹음 시작, 답변 시간이 끝나면 자동 종료
  useEffect(() => {
    if (phase !== "prep" && !(phase === "answer" && mock)) return;
    const t = setInterval(() => {
      const remain = (deadline.current - performance.now()) / 1000;
      setLeft(remain);
      if (remain <= 0) {
        clearInterval(t);
        phase === "prep" ? beginAnswer() : finishAnswer();
      }
    }, 200);
    return () => clearInterval(t);
  }, [phase, mock, beginAnswer, finishAnswer]);

  // 자유 연습: 경과 시간 표시
  useEffect(() => {
    if (phase !== "answer" || mock) return;
    const start = performance.now();
    const t = setInterval(() => setLeft((performance.now() - start) / 1000), 250);
    return () => clearInterval(t);
  }, [phase, mock]);

  if (err && !session) return <p className="err">{err}</p>;
  if (!session) return <p className="muted">불러오는 중…</p>;
  if (phase === "done" || !answer)
    return (
      <div className="card">
        <h2>연습이 끝났습니다</h2>
        <Link to={`/practice/sessions/${session.id}`}>답변 다시 보기 →</Link>
      </div>
    );

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>{session.title}</h1>
        <span className="muted">{idx + 1} / {session.answers.length}</span>
      </div>
      <div className="card">
        <div className="row small">
          <span className="chip">{answer.question.category}</span>
          {mock && <span className="chip accent">모의시험</span>}
        </div>
        <div className="runner-q">{answer.question.text}</div>

        {phase === "prep" && (
          <>
            <div className="phase">답변 준비 시간</div>
            <div className="timer">{fmt(left)}</div>
            <div className="spacer" />
            <button className="primary" onClick={beginAnswer}>바로 답변 시작</button>
          </>
        )}
        {phase === "answer" && (
          <>
            <div className="phase">● 녹음 중 {mock ? "· 남은 시간" : "· 경과 시간"}</div>
            <div className={`timer ${mock && left < 10 ? "low" : ""}`}>{fmt(left)}</div>
            <div className="level" aria-label="마이크 입력 레벨"><div style={{ width: `${rec.level * 100}%` }} /></div>
            <div className="spacer" />
            <button className="rec" onClick={finishAnswer}>답변 끝내기</button>
          </>
        )}
        {phase === "ready" && (
          <div className="row">
            <button className="primary" onClick={beginQuestion}>{mock ? "질문 시작" : "녹음 시작"}</button>
            <button onClick={() => (idx + 1 >= session.answers.length ? nav(`/practice/sessions/${session.id}`) : setIdx(idx + 1))}>건너뛰기</button>
          </div>
        )}
        {phase === "uploading" && <p className="muted">녹음을 저장하고 전사하는 중…</p>}
        {(rec.error || err) && <p className="err">{rec.error || err}</p>}
      </div>
      <Link to={`/practice/sessions/${session.id}`} className="small">중단하고 지금까지 답변 보기</Link>
    </>
  );
}
