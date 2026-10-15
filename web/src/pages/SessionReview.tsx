import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import RubricView, { bandClass } from "../components/RubricView";
import Stars from "../components/Stars";
import type { PracticeAnswer, PracticeSession, Rubric } from "../types";

const STT_LABEL = { none: "녹음 없음", done: "전사 완료", failed: "전사 실패", unavailable: "전사 꺼짐" } as const;
const POLL_MS = 2500;
const POLL_GIVE_UP_MS = 120_000;

/** 자동 삭제까지 남은 날짜(올림) */
const daysLeft = (iso: string) => Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);

/** 약점 사유 → 칩 색상 */
const reasonClass = (r: string) => (r.endsWith("부족") ? "band-bad" : r === "건너뜀" ? "band-na" : "band-warn");

/** 다시 연습한 세션에서, 원래 세션의 같은 질문 결과를 한 줄로 보여준다. */
function PrevLine({ prev }: { prev: PracticeAnswer }) {
  const criteria = prev.feedback?.criteria ?? [];
  return (
    <div className="row small muted" style={{ gap: 6, marginTop: 6 }}>
      <span>지난번</span>
      {criteria.map((c) => <span key={c.key} className={`chip ${bandClass(c.band)}`}>{c.label} {c.band}</span>)}
      {prev.self_rating != null && <span>자기평가 {prev.self_rating}점</span>}
      {criteria.length === 0 && prev.self_rating == null && <span>평가 없음</span>}
    </div>
  );
}

function AnswerCard({ a, rubric, prev, onChange }: {
  a: PracticeAnswer;
  rubric: Rubric | null;
  prev?: PracticeAnswer;
  onChange: (a: PracticeAnswer) => void;
}) {
  const [audio, setAudio] = useState<string | null>(null);
  const [audioErr, setAudioErr] = useState<string | null>(null);
  const [transcript, setTranscript] = useState(a.transcript ?? "");
  const [note, setNote] = useState(a.reflection_note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setAudio(null);
    setAudioErr(null);
    if (!a.audio_available) return;
    let url: string | null = null;
    let alive = true;
    api.audioUrl(a.id)
      .then((u) => (alive ? setAudio((url = u)) : URL.revokeObjectURL(u)))
      .catch((e) => alive && setAudioErr(e.message));
    return () => {
      alive = false;
      url && URL.revokeObjectURL(url);
    };
  }, [a.id, a.audio_available, a.recorded_at]);

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

  const textDirty = transcript !== (a.transcript ?? "");
  const dirty = textDirty || note !== (a.reflection_note ?? "");
  // 한국어 발화 속도 참고용: 전사 글자 수 / 분
  const cpm = a.transcript && a.duration_sec ? Math.round((a.transcript.replace(/\s/g, "").length / a.duration_sec) * 60) : null;

  // 고친 전사문이 있으면 먼저 저장하고 채점한다(옛 전사문으로 채점하지 않도록)
  const grade = () =>
    act(async () => {
      if (textDirty) await api.reflect(a.id, { transcript: transcript || null });
      return api.feedback(a.id);
    });

  const removeAudio = () => {
    if (confirm("원본 녹음을 지울까요? 전사문은 남아요.")) act(() => api.deleteAudio(a.id));
  };

  return (
    <section className="card" id={`answer-${a.id}`}>
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>Q{a.order_no}. {a.question.text}</h3>
        <span className="chip">{a.question.category}</span>
      </div>
      {prev && <PrevLine prev={prev} />}
      <div className="spacer" />
      {a.audio_available ? (
        <>
          {audio ? <audio controls src={audio} style={{ width: "100%" }} /> : <p className="muted small">{audioErr ?? "녹음을 불러오는 중…"}</p>}
          <div className="row small muted">
            {a.audio_expires_at && (
              <span className="grow">{daysLeft(a.audio_expires_at) >= 1 ? `${daysLeft(a.audio_expires_at)}일 뒤 자동 삭제` : "곧 자동 삭제"}</span>
            )}
            <button className="small danger" disabled={busy} onClick={removeAudio}>녹음 삭제</button>
          </div>
        </>
      ) : a.audio_deleted_at ? (
        <p className="muted small">원본 녹음은 지웠어요. 전사문만 남겨요.</p>
      ) : (
        <p className="muted small">녹음이 없습니다.</p>
      )}
      <div className="row small muted">
        <span>{STT_LABEL[a.stt_status]}</span>
        {a.duration_sec != null && <span>· {Math.round(a.duration_sec)}초</span>}
        {cpm != null && <span>· 분당 약 {cpm}자</span>}
        {a.stt_status === "failed" && a.audio_available && (
          <button disabled={busy} onClick={() => act(() => api.retryTranscribe(a.id), true)}>전사 다시 시도</button>
        )}
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
        <button disabled={busy || !transcript.trim()} onClick={grade}>{a.feedback ? "다시 채점" : "루브릭 피드백 받기"}</button>
      </div>
      {a.feedback ? (
        <>
          <div className="spacer" />
          <RubricView feedback={a.feedback} rubric={rubric} />
        </>
      ) : (
        a.ai_feedback && (
          <>
            <div className="spacer" />
            <div className="card" style={{ marginBottom: 0 }}>
              <span className="chip accent">AI 생성 · 참고용</span>
              <div style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>{a.ai_feedback}</div>
            </div>
          </>
        )
      )}
      {err && <p className="err">{err}</p>}
    </section>
  );
}

/** 세션 끝 자동 디브리프 + 약점 질문 다시 연습 */
function DebriefCard({ s, gaveUp, busy, err, onDebrief, onRedrill }: {
  s: PracticeSession;
  gaveUp: boolean;
  busy: boolean;
  err: string | null;
  onDebrief: () => void;
  onRedrill: () => void;
}) {
  const d = s.debrief;
  const status = s.debrief_status;
  const hasTranscript = s.answers.some((a) => a.transcript);

  return (
    <section className="card">
      <div className="row">
        <h2 className="grow" style={{ margin: 0 }}>세션 디브리프</h2>
        {status === "done" && d && <span className="chip accent">AI 생성</span>}
      </div>
      <div className="spacer" />
      {status === "pending" &&
        (gaveUp ? (
          <div className="row">
            <span className="small muted grow">디브리프가 오래 걸리고 있어요.</span>
            <button disabled={busy} onClick={onDebrief}>다시 시도</button>
          </div>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>세션 디브리프를 만드는 중이에요…</p>
        ))}
      {status === "done" && d && (
        <>
          {d.lesson && (
            <>
              <div className="small muted">핵심 교훈</div>
              <p style={{ marginTop: 2, fontWeight: 600 }}>{d.lesson}</p>
            </>
          )}
          {d.next_action && (
            <>
              <div className="small muted">다음 행동</div>
              <p style={{ marginTop: 2 }}>{d.next_action}</p>
            </>
          )}
          {d.moments.length > 0 && (
            <>
              <div className="small muted">주목할 순간</div>
              <ul className="plain">
                {d.moments.map((m, i) => (
                  <li key={i}>
                    <a href={`#answer-${m.answer_id}`} className="small">Q{m.order_no}</a>
                    <blockquote className="quote">“{m.quote}”</blockquote>
                    {m.why && <div className="small">{m.why}</div>}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="row">
            <span className="small muted grow">AI 요약은 참고용이에요. 전사문을 고쳤다면 다시 만들어 보세요.</span>
            <button className="small" disabled={busy} onClick={onDebrief}>다시 만들기</button>
          </div>
        </>
      )}
      {status === "failed" && (
        <div className="row">
          <span className="err grow">디브리프를 만들지 못했어요. 루브릭 채점 결과는 아래 답변에 남아 있어요.</span>
          <button disabled={busy} onClick={onDebrief}>다시 만들기</button>
        </div>
      )}
      {status === "unavailable" && (
        <p className="muted small" style={{ margin: 0 }}>
          OpenAI 키가 없어 자동 디브리프는 꺼져 있어요. 자기평가로 고른 약점 질문은 아래에서 다시 연습할 수 있어요.
        </p>
      )}
      {status === "none" &&
        (hasTranscript ? (
          <button disabled={busy} onClick={onDebrief}>디브리프 만들기</button>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>전사문이 생기면 디브리프를 만들 수 있어요.</p>
        ))}

      <div className="divider" />
      <h3>약점 다시 연습</h3>
      {s.redrill.length === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>자기평가 2점 이하이거나 루브릭에 ‘부족’이 있는 질문이 여기에 모여요.</p>
      ) : (
        <>
          <ul className="plain">
            {s.redrill.map((w) => (
              <li key={w.answer_id}>
                <div className="small"><a href={`#answer-${w.answer_id}`}>Q{w.order_no}.</a> {w.question_text}</div>
                <div className="row small" style={{ gap: 6, marginTop: 4 }}>
                  {w.reasons.map((r) => <span key={r} className={`chip ${reasonClass(r)}`}>{r}</span>)}
                </div>
              </li>
            ))}
          </ul>
          <div className="spacer" />
          <button className="primary" disabled={busy} onClick={onRedrill}>약점 {s.redrill.length}개 다시 연습</button>
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
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [source, setSource] = useState<PracticeSession | null>(null);
  const [sourceGone, setSourceGone] = useState(false);
  const [gaveUp, setGaveUp] = useState(false);
  const [cardBusy, setCardBusy] = useState(false);
  const [cardErr, setCardErr] = useState<string | null>(null);

  // 늦게 온 이전 응답이 새 결과를 덮지 않도록 요청 순번을 센다
  const seq = useRef(0);
  const load = useCallback(async () => {
    const n = ++seq.current;
    const next = await api.session(id);
    if (n === seq.current) setS(next);
  }, [id]);
  const apply = (next: PracticeSession) => {
    seq.current++;
    setS(next);
  };

  useEffect(() => {
    setS(null);
    setErr(null);
    setGaveUp(false);
    setCardErr(null);
    load().catch((e) => setErr(e.message));
    return () => {
      seq.current++;
    };
  }, [load]);

  useEffect(() => {
    api.rubric().then(setRubric).catch(() => {});
  }, []);

  // 다시 연습한 세션이면 원래 세션을 한 번 불러와 "지난번" 결과를 보여준다
  const sourceId = s?.redrill_of ?? null;
  useEffect(() => {
    setSource(null);
    setSourceGone(false);
    if (!sourceId) return;
    let alive = true;
    api.session(sourceId)
      .then((x) => alive && setSource(x))
      .catch(() => alive && setSourceGone(true));
    return () => {
      alive = false;
    };
  }, [sourceId]);

  // 디브리프를 만드는 동안 2.5초마다 확인하고, 2분이 지나면 멈춘다
  const pending = s?.debrief_status === "pending";
  useEffect(() => {
    if (!pending || gaveUp) return;
    const until = Date.now() + POLL_GIVE_UP_MS;
    let alive = true;
    let t = 0;
    const tick = async () => {
      if (Date.now() > until) return setGaveUp(true);
      try {
        await load();
      } catch {
        /* 다음 차례에 다시 확인 */
      }
      if (alive) t = window.setTimeout(tick, POLL_MS);
    };
    t = window.setTimeout(tick, POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [pending, gaveUp, load]);

  const cardAct = async (fn: () => Promise<void>) => {
    setCardBusy(true);
    setCardErr(null);
    try {
      await fn();
    } catch (e) {
      setCardErr((e as Error).message);
    } finally {
      setCardBusy(false);
    }
  };
  const makeDebrief = () =>
    cardAct(async () => {
      apply(await api.debrief(id));
      setGaveUp(false);
    });
  const redrill = () =>
    cardAct(async () => {
      const next = await api.redrill(id);
      nav(`/practice/sessions/${next.id}/run`);
    });

  /** 답변이 바뀌면 바로 반영하고, 약점 목록이 맞도록 세션을 다시 불러온다. */
  const onAnswer = (next: PracticeAnswer) => {
    setS((cur) => cur && { ...cur, answers: cur.answers.map((x) => (x.id === next.id ? next : x)) });
    load().catch(() => {});
  };

  if (err) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">불러오는 중…</p>;
  const remaining = s.answers.filter((a) => !a.recorded_at).length;
  const prevByQuestion = new Map(source?.answers.map((a) => [a.question.id, a]) ?? []);

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>{s.title}</h1>
        {remaining > 0 && <Link to={`/practice/sessions/${s.id}/run`}>남은 {remaining}개 이어서 연습</Link>}
        <button className="danger" onClick={async () => { if (confirm("이 연습 기록을 삭제할까요?")) { await api.deleteSession(s.id); nav("/practice/history"); } }}>삭제</button>
      </div>
      <p className="muted small">{new Date(s.created_at).toLocaleString("ko-KR")} · {s.mode === "mock" ? `모의시험 (준비 ${s.prep_sec}초 / 답변 ${s.answer_sec}초)` : "자유 연습"}</p>
      {s.redrill_of && (
        <p className="small row" style={{ gap: 6 }}>
          <span className="chip accent">다시 연습</span>
          {sourceGone ? (
            <span className="muted">원래 세션은 삭제됐어요.</span>
          ) : (
            <Link to={`/practice/sessions/${s.redrill_of}`}>원래 세션{source ? ` 「${source.title}」` : ""} 보기 →</Link>
          )}
        </p>
      )}
      <DebriefCard s={s} gaveUp={gaveUp} busy={cardBusy} err={cardErr} onDebrief={makeDebrief} onRedrill={redrill} />
      {s.answers.map((a) => (
        <AnswerCard key={a.id} a={a} rubric={rubric} prev={prevByQuestion.get(a.question.id)} onChange={onAnswer} />
      ))}
    </>
  );
}
