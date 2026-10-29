import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import Stars from "../components/Stars";
import CoachingPanel from "../components/CoachingPanel";
import ConsentPanel from "../components/ConsentPanel";
import InterviewContext from "../components/InterviewContext";
import VideoReportCard from "../components/VideoReportCard";
import type { CoachingRubric, InterviewContext as Context, PracticeAnswer, PracticeSession, PracticeSettings } from "../types";
import { clearSessionVideo } from "../video/metrics";

const STT_LABEL = { none: "녹음 없음", done: "음성 인식 완료", failed: "음성 인식 재시도 필요", unavailable: "자동 전사 미연결" } as const;
const POLL_MS = 2500;
const POLL_GIVE_UP_MS = 120_000;

/** 자동 삭제까지 남은 날짜(올림) */
const daysLeft = (iso: string) => Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);

/** 음성 인식 상태. 전사하지 못한 녹음의 원본이 없으면 다시 시도할 수 없으니 '재시도 필요'라고 하지 않는다 */
function sttLabel(a: PracticeAnswer) {
  if (a.audio_available || (a.stt_status !== "failed" && a.stt_status !== "unavailable")) return STT_LABEL[a.stt_status];
  const what = a.stt_status === "failed" ? "음성 인식 실패" : "자동 전사 안 됨";
  return a.audio_deleted_at ? `${what} · 원본 녹음 삭제됨` : what;
}

function AnswerCard({ a, context, rubric, onChange, onReload }: {
  a: PracticeAnswer;
  context: Context | null;
  rubric: CoachingRubric | null;
  onChange: (a: PracticeAnswer) => void;
  /** 실패했을 때 서버 상태로 다시 맞춘다(중간 단계가 이미 저장됐을 수 있다) */
  onReload: () => void;
}) {
  const [audio, setAudio] = useState<string | null>(null);
  const [audioErr, setAudioErr] = useState<string | null>(null);
  const [transcript, setTranscript] = useState(a.transcript ?? "");
  const [note, setNote] = useState(a.reflection_note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 음성 인식 다시 시도가 403(녹음 동의 없음)이면 지금 설정으로 동의 패널을 띄운다
  const [needConsent, setNeedConsent] = useState<PracticeSettings | null>(null);
  // 서버 전사문이 바뀌면(다시 불러옴 등) 입력란을 고치지 않았을 때만 맞춘다. 실패한 다시 전사도 서버가 이미 얻은 전사문을
  // 남겼을 수 있다(전사 중 동의 철회): 맞추지 않으면 빈 입력란이 바뀐 것으로 보여 '저장'이 그 전사문을 지운다
  const shownTranscript = useRef(a.transcript ?? "");
  useEffect(() => {
    const prev = shownTranscript.current;
    const next = a.transcript ?? "";
    shownTranscript.current = next;
    setTranscript((t) => (t === prev ? next : t));
  }, [a.transcript]);

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
    setNeedConsent(null);
    try {
      const next = await fn();
      onChange(next);
      if (syncText) setTranscript(next.transcript ?? "");
    } catch (e) {
      // 녹음을 OpenAI로 다시 보내려면 녹음 동의가 필요하다(다른 곳에서 철회한 경우)
      if (e instanceof ApiError && e.status === 403)
        setNeedConsent(await api.settings().catch(() => ({ consented_at: null, keep_audio: false, retention_days: 30 })));
      else setErr((e as Error).message);
      onReload();
    } finally {
      setBusy(false);
    }
  };

  const dirty = transcript !== (a.transcript ?? "") || note !== (a.reflection_note ?? "");
  const hasTranscript = !!a.transcript?.trim();
  // 한국어 발화 속도 참고용: 전사 글자 수 / 분
  const cpm = a.transcript && a.duration_sec ? Math.round((a.transcript.replace(/\s/g, "").length / a.duration_sec) * 60) : null;

  const retranscribe = () => act(async () => {
    if (dirty) onChange(await api.reflect(a.id, { transcript: transcript || null, reflection_note: note || null }));
    return api.retryTranscribe(a.id);
  }, true);

  const removeAudio = () => {
    const ask = hasTranscript ? "원본 녹음을 지울까요? 전사문은 남아요." : "전사문이 없어 지우면 이 답변 내용이 남지 않아요. 원본 녹음을 지울까요?";
    if (confirm(ask)) act(() => api.deleteAudio(a.id));
  };

  return (
    <section className="card" id={`answer-${a.id}`}>
      <div className="row">
        <h3 className="grow" style={{ margin: 0 }}>Q{a.order_no}. {a.question.text}</h3>
        <span className="chip">{a.question.category}</span>
        {a.parent_answer_id && <span className="chip accent">꼬리질문</span>}
      </div>
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
        <p className="muted small">{hasTranscript ? "원본 녹음은 지웠어요. 전사문만 남겨요." : "원본 녹음은 지웠어요."}</p>
      ) : (
        <p className="muted small">녹음이 없습니다.</p>
      )}
      <div className="row small muted">
        <span>{sttLabel(a)}</span>
        {a.duration_sec != null && <span>· {Math.round(a.duration_sec)}초</span>}
        {cpm != null && <span>· 분당 약 {cpm}자</span>}
        {a.audio_available && (a.stt_status === "failed" || a.stt_status === "unavailable") && <button disabled={busy} onClick={retranscribe}>음성 인식 다시 시도</button>}
      </div>
      {/* 다시 불러온 답변에 원본이 없으면(그 사이 지움) 동의해도 다시 전사할 수 없으니 동의를 묻지 않는다 */}
      {needConsent && a.audio_available && (
        <ConsentPanel
          retentionDays={needConsent.retention_days}
          initialKeepAudio={needConsent.keep_audio}
          notice="녹음을 다시 전사하려면 먼저 녹음 동의가 필요해요."
          buttonLabel="동의하고 다시 전사"
          onConsented={retranscribe}
        />
      )}
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
      {a.coaching_report && <CoachingPanel report={a.coaching_report} context={context} rubric={rubric} />}
      {a.ai_feedback && !a.coaching_report && (
        <>
          <div className="spacer" />
          <div className="card" style={{ marginBottom: 0 }}>
            <span className="chip accent">AI 생성</span>
            <div style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>{a.ai_feedback}</div>
          </div>
        </>
      )}
      {err && <p className="err">{err}</p>}
    </section>
  );
}

/** 세션을 마치면 자동으로 만드는 디브리프(답변 코칭 위에서). 키가 없으면 기본 점검만 돈다. */
function DebriefCard({ s, ai, gaveUp, busy, err, onDebrief, onRetry }: {
  s: PracticeSession;
  /** 지금 서버에 OpenAI 키가 있는가(/health). 아직 모르면 null이고, 그때는 저장된 상태만 보고 판단한다 */
  ai: boolean | null;
  gaveUp: boolean;
  busy: boolean;
  err: string | null;
  onDebrief: () => void;
  /** 작업이 사라졌거나 오래 걸려 확인을 멈춘 뒤의 '다시 시도' */
  onRetry: () => void;
}) {
  const d = s.debrief;
  const status = s.debrief_status;
  const hasTranscript = s.answers.some((a) => a.transcript?.trim());
  const hasCoaching = s.answers.some((a) => a.coaching_report);
  // 저장된 'unavailable'은 마칠 때 키가 없었다는 뜻일 뿐이다. 지금 키가 있으면 만들 수 있고, 지금 키가 없으면 어떤 상태든 만들 수 없다
  const noKey = ai === false || (ai === null && status === "unavailable");
  // 'pending'인데 서버가 도는 작업이 없다고 하면 작업이 사라진 것(서버 재시작 등)이다: 기다리게 하지 않고 바로 다시 시도를 보인다
  const lost = status === "pending" && !s.debrief_running;
  const noKeyText = (
    <p className="muted small" style={{ margin: 0 }}>
      OpenAI 키가 없어 자동 디브리프는 꺼져 있어요. 면접을 마치면 전사문이 있는 답변마다 기본 점검이 붙고, 보완 항목이 있거나 자기평가가 1~2점인
      답변은 아래에서 다시 연습할 수 있어요.
    </p>
  );

  return (
    <section className="card debrief-card">
      <div className="row">
        <h2 className="grow" style={{ margin: 0 }}>세션 디브리프</h2>
        {status === "done" && d && <span className="chip accent">AI 생성</span>}
      </div>
      <div className="spacer" />
      {status === "pending" &&
        (lost || gaveUp ? (
          <div className="row">
            <span className="small muted grow">{lost ? "디브리프 작업이 중간에 멈췄어요." : "디브리프가 오래 걸리고 있어요."}</span>
            <button disabled={busy} onClick={onRetry}>다시 시도</button>
          </div>
        ) : (
          <p className="muted small" role="status" style={{ margin: 0 }}>답변을 점검하고 세션 디브리프를 만드는 중이에요…</p>
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
            {noKey ? (
              <span className="small muted grow">AI 요약은 참고용이에요. 지금은 OpenAI 키가 없어 다시 만들 수 없어요.</span>
            ) : (
              <>
                <span className="small muted grow">AI 요약은 참고용이에요. 답변을 고쳤다면 다시 만들어 보세요.</span>
                <button className="small" disabled={busy} onClick={onDebrief}>다시 만들기</button>
              </>
            )}
          </div>
        </>
      )}
      {status === "failed" &&
        (noKey ? (
          <>
            <p className="err" style={{ marginTop: 0 }}>디브리프를 만들지 못했어요.{hasCoaching && " 답변 코칭 결과는 아래 답변에 남아 있어요."}</p>
            {noKeyText}
          </>
        ) : (
          <div className="row">
            <span className="err grow">디브리프를 만들지 못했어요.{hasCoaching && " 답변 코칭 결과는 아래 답변에 남아 있어요."}</span>
            <button disabled={busy} onClick={onDebrief}>다시 만들기</button>
          </div>
        ))}
      {(status === "unavailable" || status === "none") &&
        (noKey ? (
          <>
            {noKeyText}
            {s.debrief_running && !gaveUp && <p className="muted small" role="status">답변을 기본 점검하는 중이에요…</p>}
          </>
        ) : hasTranscript ? (
          <div className="row">
            {status === "unavailable" && <span className="small muted grow">면접을 마칠 때 OpenAI 키가 없어 디브리프를 만들지 않았어요.</span>}
            <button disabled={busy} onClick={onDebrief}>디브리프 만들기</button>
          </div>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>답변이 생기면 디브리프를 만들 수 있어요.</p>
        ))}
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
  const [rubric, setRubric] = useState<CoachingRubric | null>(null);
  const [ai, setAi] = useState<boolean | null>(null);
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
    // 디브리프를 만들 수 있는지는 저장된 상태가 아니라 지금 키가 있는지로 정한다
    api.health().then((h) => setAi(h.openai)).catch(() => {});
  }, []);

  // 답변 점검·디브리프 작업이 도는 동안 2.5초마다 확인하고, 2분이 지나면 멈춘다.
  // 'pending'이어도 서버가 도는 작업이 없다고 하면(작업이 사라짐) 기다리지 않는다: 카드가 바로 '다시 시도'를 보인다
  const waiting = !!s?.debrief_running;
  useEffect(() => {
    if (!waiting || gaveUp) return;
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
  }, [waiting, gaveUp, load]);

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
  // '다시 시도'(작업이 사라졌거나 확인을 멈춘 뒤): 먼저 지금 상태를 다시 확인한다. 작업이 아직 돌고 있으면(마지막 진행 신호가 5분 안)
  // 재생성을 요청하지 않고 확인만 이어 가고, 'pending'인데 작업이 사라졌을 때(서버 재시작 등)만 다시 만들기를 요청한다.
  const retryDebrief = () =>
    cardAct(async () => {
      const cur = await api.session(id);
      apply(cur.debrief_status === "pending" && !cur.debrief_running ? await api.debrief(id) : cur);
      setGaveUp(false);
    });

  /** 답변이 바뀌면 바로 반영하고, 다시 연습할 답변 목록이 맞도록 세션을 다시 불러온다. */
  const onAnswer = (next: PracticeAnswer) => {
    setS((cur) => cur && { ...cur, answers: cur.answers.map((x) => (x.id === next.id ? next : x)) });
    load().catch(() => {});
  };
  const reload = () => {
    load().catch(() => {});
  };

  const removeSession = async () => {
    if (!confirm("이 연습 기록을 삭제할까요? 전사문과 원본 녹음도 함께 지워져요.")) return;
    setErr(null);
    try {
      await api.deleteSession(id);
      clearSessionVideo(id);
      nav("/practice/history");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (err && !s) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">불러오는 중…</p>;
  // 원본 녹음은 전사가 끝나면 지워질 수 있으니 녹음 여부는 recorded_at으로 본다
  const remaining = s.answers.filter((a) => !a.recorded_at && !a.transcript?.trim()).length;
  const weak = s.redrill.length;
  // '보완 항목 N개'(PR #2 문구)는 고른 답변마다 코칭의 보완이 있을 때만 맞다. 자기평가만으로 고른 답변이 있으면 답변 수로 말한다
  const allNeedWork = s.redrill.every((w) => w.reasons.some((r) => r.endsWith("보완")));

  return (
    <>
      <div className="row">
        <h1 className="grow" style={{ margin: 0 }}>{s.title}</h1>
        {!s.finished_at && <Link to={`/practice/sessions/${s.id}/run`}>{remaining > 0 ? `남은 ${remaining}개 이어서 연습` : "면접 이어서 마치기"}</Link>}
        <button className="danger" onClick={removeSession}>삭제</button>
      </div>
      <p className="muted small">{new Date(s.created_at).toLocaleString("ko-KR")} · {s.mode === "mock" ? `모의시험 (준비 ${s.prep_sec}초 / 답변 ${s.answer_sec}초)` : "자유 연습"}</p>
      {err && <p className="err">{err}</p>}
      <DebriefCard s={s} ai={ai} gaveUp={gaveUp} busy={cardBusy} err={cardErr} onDebrief={makeDebrief} onRetry={retryDebrief} />
      <VideoReportCard sessionId={s.id} answers={s.answers} />
      <InterviewContext context={s.context_snapshot} />
      <section className="card review-summary">
        <h2>다음 연습으로 연결하기</h2>
        <p className="small muted">답변을 점검하면 보완할 부분을 확인할 수 있어요. 이전 기록은 보관하고 같은 기준 자료로 다시 연습해요.</p>
        {weak === 0 ? (
          <p className="muted small">코칭에 ‘보완’이 있거나 자기평가가 1~2점인 답변이 여기에 모여요.</p>
        ) : (
          <ul className="plain weak-list">
            {s.redrill.map((w) => (
              <li key={w.answer_id}>
                <div className="small"><a href={`#answer-${w.answer_id}`}>Q{w.order_no}.</a> {w.question_text}</div>
                <div className="row small" style={{ gap: 6, marginTop: 4 }}>
                  {w.reasons.map((r) => <span key={r} className={`chip ${r.endsWith("보완") ? "needs-work" : ""}`}>{r}</span>)}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="spacer" />
        <button className="primary" disabled={busy || !weak} onClick={async () => {
          setBusy(true); setErr(null);
          try { const drill = await api.redrill(s.id); nav(`/practice/sessions/${drill.id}/run`); }
          catch (e) { setErr((e as Error).message); }
          finally { setBusy(false); }
        }}>{allNeedWork ? `보완 항목 ${weak}개 다시 연습` : `답변 ${weak}개 다시 연습`}</button>
      </section>
      {s.answers.map((a) => (
        <AnswerCard key={a.id} a={a} context={s.context_snapshot} rubric={rubric} onChange={onAnswer} onReload={reload} />
      ))}
    </>
  );
}
