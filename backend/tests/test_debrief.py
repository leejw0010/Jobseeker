"""세션 종료 자동 디브리프(답변 코칭 위에서)와 다시 연습할 답변 고르기."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import httpx
import pytest

from app import coaching, debrief, llm
from app.config import settings
from app.db import SessionLocal
from app.models import PracticeAnswer, PracticeSession
from app.routers import practice

T1 = "작년 동아리에서 저는 회계 정리를 맡았고 엑셀 매크로로 정산 시간을 절반으로 줄였습니다."
T2 = "지원 동기는 고객 데이터를 직접 다루는 일을 하고 싶어서입니다."
SUMMARY = {"lesson": "결과를 수치로 말할 때 답이 선명했다", "next_action": "첫 문장에 결론을 말한다",
           "moments": [{"order_no": 1, "quote": "정산 시간을 절반으로 줄였습니다", "why": "수치"},
                       {"order_no": 2, "quote": "전사문에 없는 문장", "why": "지어냄"}]}


def _bank(client, h, n):
    qs = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    return [q for q in qs if "자기소개" not in q["text"]][:n]


def _session(client, h, n, **body):
    qs = _bank(client, h, n)
    r = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"] for q in qs], **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _coach_reply(transcript: str, weak: bool = True) -> dict:
    """PR #2 코칭 형식의 응답. 인용은 이번 답변 앞부분을 그대로 쓴다(자소서가 없으니 제출본 연결은 판단유보)."""
    quote = transcript[:10]
    return {"summary": "결과 확인 과정을 더 말해 보세요.", "next_action": "결과를 확인한 방법을 한 문장으로 덧붙이세요.",
            "criteria": [
                {"key": "specificity", "label": "구체성", "status": "보완" if weak else "충분",
                 "reason": "결과를 확인한 방법이 없어요.", "answer_quote": quote},
                {"key": "relevance", "label": "질문 적합성", "status": "충분", "reason": "질문에 바로 답했어요.",
                 "answer_quote": quote},
                {"key": "consistency", "label": "제출본 연결", "status": "판단유보", "reason": "비교할 자소서가 없어요."}],
            "followup": {"text": "그 결과는 어떻게 확인했나요?", "focus": "specificity", "reason": "결과 확인 과정",
                         "answer_quote": quote}}


def _fake(calls, weak=True, summary=SUMMARY):
    """코칭·디브리프 요청을 흉내 낸다."""
    def fake_chat(system, user, json_mode=False, **kwargs):
        calls.append({"system": system, "user": user, **kwargs})
        if system == coaching.SYSTEM:
            return json.dumps(_coach_reply(json.loads(user)["answer"], weak), ensure_ascii=False)
        if system == llm._DEBRIEF_SYSTEM:
            return summary if isinstance(summary, str) else json.dumps(summary, ensure_ascii=False)
        raise AssertionError("예상하지 못한 프롬프트")
    return fake_chat


def _kinds(calls):
    return ["coach" if c["system"] == coaching.SYSTEM else "debrief" for c in calls]


def test_finish_coaches_answers_then_builds_debrief(client, monkeypatch):
    h = {"X-User-Id": "user-debrief"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _fake(calls))
    s = _session(client, h, 3)
    a1, a2, a3 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"transcript": T1, "self_rating": 4, "reflection_note": "결론이 늦었다"},
                 headers=h)
    client.patch(f"/practice/answers/{a2}", json={"transcript": T2}, headers=h)

    r = client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()
    assert r["debrief_status"] == "pending"  # 응답은 바로, 코칭·디브리프는 백그라운드에서
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "done" and got["debrief_running"] is False
    assert _kinds(calls) == ["coach", "coach", "debrief"]
    # 코칭은 /coach와 같은 경로(채팅 모델), 디브리프 요약만 피드백 모델·낮은 temperature
    assert "temperature" not in calls[0] and calls[2]["temperature"] == 0.2
    assert calls[2]["model"] == settings.openai_feedback_model
    by_id = {a["id"]: a for a in got["answers"]}
    for aid in (a1, a2):
        report = by_id[aid]["coaching_report"]
        assert report["method"] == "ai" and report["criteria"][0]["status"] == "보완"
    assert by_id[a3]["coaching_report"] is None
    d = got["debrief"]
    assert d["lesson"] and d["next_action"] and d["generated_at"] and d["model"] == settings.openai_feedback_model
    # 전사문에 없는 인용은 버린다
    assert d["moments"] == [{"answer_id": a1, "order_no": 1, "quote": "정산 시간을 절반으로 줄였습니다", "why": "수치"}]
    assert [(w["answer_id"], w["reasons"]) for w in got["redrill"]] == [(a1, ["AI · 구체성 보완"]), (a2, ["AI · 구체성 보완"])]
    # 디브리프 요청: 기준의 뜻과, 동의 화면에 알린 항목(질문·전사문·자기평가·회고 메모·코칭 결과)만 보낸다
    payload = json.loads(calls[2]["user"])
    assert set(payload["criteria"]) == {"구체성", "질문 적합성", "제출본 연결"}
    first = payload["answers"][0]
    assert set(first) == {"order_no", "question", "transcript", "self_rating", "reflection_note",
                          "coaching_method", "coaching"}
    assert (first["self_rating"], first["reflection_note"], first["coaching_method"]) == (4, "결론이 늦었다", "ai")
    assert first["coaching"] == {"구체성": "보완", "질문 적합성": "충분", "제출본 연결": "판단유보"}

    # 다시 끝내면 요약만 새로 만들고, 이미 있는 코칭은 다시 하지 않는다
    n = len(calls)
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()["debrief_status"] == "pending"
    assert _kinds(calls[n:]) == ["debrief"]
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["debrief_status"] == "done"


def test_debrief_failure_keeps_coaching_and_can_regenerate(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-fail"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _fake(calls, summary="깨진 응답"))
    s = _session(client, h, 1)
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "failed" and got["debrief"] is None and got["debrief_running"] is False
    assert got["answers"][0]["coaching_report"]["method"] == "ai"  # 코칭은 남는다

    monkeypatch.setattr(llm, "_chat", _fake(calls))
    r = client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()
    assert r["debrief_status"] == "pending"
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "done" and got["debrief"]["moments"][0]["answer_id"] == aid


def test_finish_without_key_runs_basic_coaching_and_is_unavailable(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-off"}
    s = _session(client, h, 2)
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    r = client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()
    assert r["debrief_status"] == "unavailable"
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    # 키가 없어도 코칭은 기본 점검으로 돈다(AI 평가로 표시하지 않음). 요약은 만들지 않는다
    assert got["answers"][0]["coaching_report"]["method"] == "basic" and got["answers"][1]["coaching_report"] is None
    assert got["debrief_status"] == "unavailable" and got["debrief"] is None and got["debrief_running"] is False
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "unavailable"

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    s2 = _session(client, h, 1)
    r = client.post(f"/practice/sessions/{s2['id']}/finish", headers=h).json()
    assert r["debrief_status"] == "none" and r["debrief_running"] is False


def _edit_transcript(answer_id: str, text: str) -> None:
    """다른 요청(PATCH)이 전사문을 고친 것처럼 별도 DB 세션에서 바꾼다(코칭도 PATCH처럼 무효화)."""
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, answer_id)
        practice._invalidate_coaching(a)
        a.transcript = text
        db.commit()


def test_answer_edited_during_coaching_is_skipped_then_coached_again(client, monkeypatch):
    """점검 중에 전사문이 바뀐 답변은 /coach처럼 409로 버리고, 다음 바퀴에서 새 전사문으로 다시 점검한다."""
    h = {"X-User-Id": "user-debrief-race"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    t2_old, t2_new = "작년 동아리에서 저는 발표를 맡았습니다.", "인턴십에서 저는 데이터 정리 자동화를 맡았습니다."
    a1_new = "고친 첫 답변입니다. 저는 일정을 다시 짰습니다."
    calls: list = []
    fake = _fake(calls)
    ids: dict = {}

    def racing(system, user, json_mode=False, **kwargs):
        out = fake(system, user, json_mode, **kwargs)
        if _kinds(calls) == ["coach"]:
            _edit_transcript(ids["a1"], a1_new)  # 점검 중인 답변을 고침
            _edit_transcript(ids["a2"], t2_new)  # 아직 점검하지 않은 답변을 고침
        return out

    monkeypatch.setattr(llm, "_chat", racing)
    s = _session(client, h, 2)
    ids["a1"], ids["a2"] = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{ids['a1']}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{ids['a2']}", json={"transcript": t2_old}, headers=h)

    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    a1, a2 = got["answers"]
    assert got["debrief_status"] == "done"
    coached = [json.loads(c["user"])["answer"] for c in calls if c["system"] == coaching.SYSTEM]
    assert coached == [T1, t2_new, a1_new]
    assert a1["transcript"] == a1_new and a1["coaching_report"]["criteria"][0]["answer_quote"] == a1_new[:10]
    assert a2["transcript"] == t2_new and a2["coaching_report"]["criteria"][0]["answer_quote"] == t2_new[:10]
    # 요약도 지금 전사문으로 만든다
    summary = next(c["user"] for c in calls if c["system"] == llm._DEBRIEF_SYSTEM)
    assert a1_new in summary and t2_new in summary and T1 not in summary and t2_old not in summary


def test_finish_does_not_start_second_debrief_while_running(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-pending"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _fake(calls))
    s = _session(client, h, 1)
    client.patch(f"/practice/answers/{s['answers'][0]['id']}", json={"transcript": T1}, headers=h)
    with SessionLocal() as db:
        x = db.get(PracticeSession, s["id"])
        x.debrief_status, x.debrief_started_at = "pending", datetime.now(timezone.utc)  # 다른 작업이 만드는 중
        db.commit()
    r = client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()
    assert r["debrief_status"] == "pending" and r["debrief_running"] is True
    # 2분 뒤 화면의 '다시 시도'는 먼저 상태를 확인한다: 작업이 돌고 있으면 재생성을 보내지 않는다
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["debrief_running"] is True
    # 그래도 재생성 요청이 오면 도는 작업이 있으니 하나 더 붙이지 않는다
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "pending"
    assert calls == []

    # 5분이 지나도 끝나지 않았으면 작업이 사라진 것(서버 재시작 등)으로 보고 다시 시작한다
    with SessionLocal() as db:
        db.get(PracticeSession, s["id"]).debrief_started_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()
    lost = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert lost["debrief_status"] == "pending" and lost["debrief_running"] is False
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "pending"
    assert _kinds(calls) == ["coach", "debrief"]
    done = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert done["debrief_status"] == "done" and done["debrief_running"] is False


def test_redrill_also_takes_low_self_ratings_in_order(client, monkeypatch):
    h = {"X-User-Id": "user-redrill"}
    s = _session(client, h, 4, title="금요일 연습")
    a1, a2, a3, a4 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"self_rating": 2}, headers=h)  # 글 답변 없이 자기평가만
    client.patch(f"/practice/answers/{a2}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{a3}", json={"transcript": T2, "self_rating": 3}, headers=h)
    client.patch(f"/practice/answers/{a4}", json={"transcript": T2, "self_rating": 1}, headers=h)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "_chat", _fake([], weak=True))
    assert client.post(f"/practice/answers/{a2}/coach", headers=h).status_code == 200
    monkeypatch.setattr(llm, "_chat", _fake([], weak=False))
    assert client.post(f"/practice/answers/{a3}/coach", headers=h).status_code == 200  # 보완 없음, 자기평가 3점
    assert client.post(f"/practice/answers/{a4}/coach", headers=h).status_code == 200  # 보완 없음, 자기평가 1점
    monkeypatch.setattr(settings, "openai_api_key", "")

    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert [(w["answer_id"], w["reasons"]) for w in got["redrill"]] == [
        (a1, ["자기평가 2점"]), (a2, ["AI · 구체성 보완"]), (a4, ["자기평가 1점"])]
    assert got["redrill"][0]["question_text"] == s["answers"][0]["question"]["text"]

    r = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert r.status_code == 201, r.text
    drill = r.json()
    assert [a["question"]["id"] for a in drill["answers"]] == [s["answers"][i]["question"]["id"] for i in (0, 1, 3)]
    assert drill["title"] == "보완 연습 · 금요일 연습" and drill["mode"] == "free"
    targets = drill["context_snapshot"]["drill_targets"]
    assert [(t["answer_id"], t["focus"]) for t in targets] == [(a1, ["자기평가 2점"]), (a2, ["구체성"]), (a4, ["자기평가 1점"])]
    assert "자기평가 2점" in targets[0]["next_action"]  # 코칭이 없으면 자기평가로 안내한다
    assert targets[1]["next_action"] == "결과를 확인한 방법을 한 문장으로 덧붙이세요."  # 코칭의 다음 연습
    assert targets[2]["next_action"] == "결과를 확인한 방법을 한 문장으로 덧붙이세요."


def test_basic_coaching_reasons_are_not_labeled_ai_and_redrill_caps_at_20(client):
    h = {"X-User-Id": "user-redrill-basic"}
    app = client.post("/track/applications", headers=h, json={"company": "테스트회사", "position": "백엔드"}).json()
    client.post(f"/track/applications/{app['id']}/essays", headers=h,
                json={"question_text": "성과", "content": "캐시를 도입해 응답 시간을 40% 줄였습니다."})
    qs = [client.post("/practice/questions", headers=h, json={"category": "직무", "text": f"성과 질문 {i}번"}).json()["id"]
          for i in range(21)]
    s = client.post("/practice/sessions", headers=h, json={"mode": "free", "application_id": app["id"],
                                                          "question_ids": qs}).json()
    first = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{first}", json={"transcript": "제가 캐시를 도입했습니다."}, headers=h)
    report = client.post(f"/practice/answers/{first}/coach", headers=h).json()["coaching_report"]
    assert report["method"] == "basic"
    for a in s["answers"][1:]:
        client.patch(f"/practice/answers/{a['id']}", json={"self_rating": 1}, headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["redrill"][0]["reasons"] == ["구체성 보완"]  # 기본 점검은 'AI ·'를 붙이지 않는다
    assert len(got["redrill"]) == 20 and got["redrill"][-1]["order_no"] == 20
    drill = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h).json()
    assert len(drill["answers"]) == 20
    assert [t["answer_id"] for t in drill["context_snapshot"]["drill_targets"]] == [w["answer_id"] for w in got["redrill"]]


def test_redrill_nothing_qualifies_and_other_user(client):
    h, other = {"X-User-Id": "user-redrill-none"}, {"X-User-Id": "user-redrill-other"}
    s = _session(client, h, 1)
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"self_rating": 3}, headers=h)
    r = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert r.status_code == 422 and "보완" in r.json()["detail"] and "자기평가" in r.json()["detail"]
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["redrill"] == []
    assert client.post(f"/practice/sessions/{s['id']}/redrill", headers=other).status_code == 404
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=other).status_code == 404
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=other).status_code == 404
    assert client.delete(f"/practice/answers/{aid}/audio", headers=other).status_code == 404


def test_rubric_endpoint_serves_coaching_criteria_with_anchors(client):
    r = client.get("/practice/rubric", headers={"X-User-Id": "user-rubric"}).json()
    assert [c["key"] for c in r["criteria"]] == ["specificity", "relevance", "consistency"]
    assert [c["label"] for c in r["criteria"]] == ["구체성", "질문 적합성", "제출본 연결"]
    assert {c["key"]: c["label"] for c in r["criteria"]} == coaching.LABELS
    for c in r["criteria"]:
        assert c["checks"] and set(c["anchors"]) == {"충분", "보완"}
        for anchor in c["anchors"].values():
            assert anchor in coaching.SYSTEM  # 화면에 보이는 앵커와 프롬프트의 앵커가 같다
    star = r["criteria"][0]["star"]
    assert star["when"] == "과거 경험을 묻는 질문"
    assert [a.split(":")[0] for a in star["anchors"]] == ["상황·과제", "본인 몫과 판단 근거", "결과와 배운 점"]
    assert all(a in coaching.SYSTEM for a in star["anchors"])
    assert set(r["statuses"]) == {"충분", "보완", "판단유보"}
    assert "τ=.19–.44" in r["note"] and "정답 여부" in r["note"]
    assert r["version"] == coaching.RUBRIC_VERSION


def test_coaching_prompt_rules():
    system = coaching.SYSTEM
    assert "후하게 주지 마라" in system and "관대" in system  # 엄격하게
    assert "꼬리질문에도" in system and "지어내지 마라" in system  # 장점·사실·수치를 지어내지 않음
    assert "목소리, 감정, 성격" in system  # 내용만
    assert "말버릇" in system  # 말버릇 무시
    assert "'우리'를 '저'로 바꾸라는 조언은 하지 마라" in system
    assert "'우리'를 '저'로 바꾸라는 조언은 하지 않는다" in llm._DEBRIEF_SYSTEM


@pytest.mark.parametrize("quote,transcript,expected", [
    ("정산 시간을 절반으로", "저는 음, 정산 시간을 절반으로 줄였습니다", ("정산 시간을 절반으로", True)),
    ("“정산 시간을, 절반으로”", "저는 정산 시간을 절반으로 줄였습니다", ("정산 시간을 절반으로", True)),
    ("지어낸 문장입니다", "저는 정산 시간을 절반으로 줄였습니다", (None, False)),
    ("저는", "저는 정산 시간을 절반으로 줄였습니다", (None, False)),
    ("", "저는", (None, None)),
])
def test_verify_quote(quote, transcript, expected):
    assert llm.verify_quote(quote, transcript) == expected


def test_debrief_summary_keeps_only_verified_moments(monkeypatch):
    raw = {"lesson": "교훈", "next_action": "행동",
           "moments": [{"order_no": 9, "quote": "정산 시간을 절반으로", "why": "없는 답변"},
                       {"order_no": "1", "quote": "“정산 시간을 절반으로”", "why": "수치"},
                       {"order_no": 1, "quote": "지어낸 인용입니다", "why": "지어냄"}]}
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: json.dumps(raw, ensure_ascii=False))
    items = [{"answer_id": "a1", "order_no": 1, "question": "Q", "transcript": T1, "self_rating": 2,
              "reflection_note": None, "coaching_method": None, "coaching": {}}]
    out = llm.debrief_summary(items, {"구체성": "막연하지 않은가"})
    assert out == {"lesson": "교훈", "next_action": "행동",
                   "moments": [{"answer_id": "a1", "order_no": 1, "quote": "정산 시간을 절반으로", "why": "수치"}]}
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: json.dumps({"moments": []}))
    with pytest.raises(llm.AIResponseError):
        llm.debrief_summary(items, {})


# ───────── 다른 전사문을 채점한 보고서 ─────────

def test_report_for_an_older_transcript_counts_as_missing(client, monkeypatch):
    """전사문을 고치는 요청이 보고서보다 먼저 답변을 읽고 나중에 저장하면(_invalidate_coaching이 지울 보고서를 못 봄)
    남은 보고서는 옛 전사문을 채점한 것이다. 응답·다시 연습할 답변·재연습·디브리프는 그 보고서를 없는 것으로 본다."""
    h = {"X-User-Id": "user-stale-report"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _fake(calls))
    s = _session(client, h, 1)
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    with SessionLocal() as edit:  # '저장'(또는 다시 전사) 요청: 보고서가 생기기 전에 답변을 읽었다
        a = edit.get(PracticeAnswer, aid)
        assert a.coaching_report is None
        assert client.post(f"/practice/answers/{aid}/coach", headers=h).json()["coaching_report"]["method"] == "ai"
        practice._invalidate_coaching(a)  # 이 요청이 읽은 답변에는 보고서가 없다
        a.transcript = T2
        edit.commit()

    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["answers"][0]["transcript"] == T2 and got["answers"][0]["coaching_report"] is None
    assert got["redrill"] == []
    assert client.post(f"/practice/sessions/{s['id']}/redrill", headers=h).status_code == 422
    # 디브리프는 이 답변을 지금 전사문으로 다시 점검하고, 요약에도 옛 보고서를 쓰지 않는다
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    coached = [json.loads(c["user"])["answer"] for c in calls if c["system"] == coaching.SYSTEM]
    assert coached == [T1, T2]
    report = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]["coaching_report"]
    assert report["criteria"][0]["answer_quote"] == T2[:10]


def test_reports_carry_the_current_rubric_version_and_old_reports_are_kept(client, monkeypatch):
    """PR #2의 기준에 STAR 앵커와 판단 규칙이 더해졌으므로 새 보고서는 새 버전을 찍는다. main이 만든 보고서는 그대로 둔다."""
    assert coaching.RUBRIC_VERSION != "2026-10-15"
    h = {"X-User-Id": "user-rubric-version"}
    s = _session(client, h, 2)
    a1, a2 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{a2}", json={"transcript": T2}, headers=h)
    basic = client.post(f"/practice/answers/{a1}/coach", headers=h).json()["coaching_report"]
    assert basic["method"] == "basic" and basic["rubric_version"] == coaching.RUBRIC_VERSION
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _fake(calls))
    ai = client.post(f"/practice/answers/{a2}/coach", headers=h).json()["coaching_report"]
    assert ai["method"] == "ai" and ai["rubric_version"] == coaching.RUBRIC_VERSION
    assert client.get("/practice/rubric").json()["version"] == coaching.RUBRIC_VERSION

    # main이 만든 보고서(2026-10-15, 전사문 지문 없음)는 지금 전사문의 것으로 보고 다시 점검하지 않는다
    old = {**_coach_reply(T1), "method": "ai", "rubric_version": "2026-10-15"}
    with SessionLocal() as db:
        db.get(PracticeAnswer, a1).coaching.report = old
        db.commit()
    n = len(calls)
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    assert _kinds(calls[n:]) == ["debrief"]
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]["coaching_report"]
    assert got["rubric_version"] == "2026-10-15" and got["method"] == "ai"


# ───────── AI 점검 실패로 대신 붙은 기본 점검 ─────────

def test_basic_fallback_after_an_ai_error_is_coached_again_by_the_next_debrief(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-fallback"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    fake = _fake(calls)
    down = {"on": True}

    def flaky(system, user, json_mode=False, **kwargs):
        if system == coaching.SYSTEM and json.loads(user)["answer"] == T2 and down["on"]:
            calls.append({"system": system, "user": user})
            raise httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"),
                                        response=httpx.Response(429))
        return fake(system, user, json_mode, **kwargs)

    monkeypatch.setattr(llm, "_chat", flaky)
    s = _session(client, h, 2)
    a1, a2 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{a2}", json={"transcript": T2}, headers=h)
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert [a["coaching_report"]["method"] for a in got["answers"]] == ["ai", "basic"]
    assert _kinds(calls) == ["coach", "coach", "debrief"]  # 한 작업 안에서는 실패한 점검을 되풀이하지 않는다

    # /coach는 그대로 기본 점검을 돌려준다
    assert client.post(f"/practice/answers/{a2}/coach", headers=h).json()["coaching_report"]["method"] == "basic"
    down["on"] = False
    n = len(calls)
    client.post(f"/practice/sessions/{s['id']}/debrief", headers=h)  # '다시 만들기'
    assert _kinds(calls[n:]) == ["coach", "debrief"]
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert [a["coaching_report"]["method"] for a in got["answers"]] == ["ai", "ai"]
    assert [w["answer_id"] for w in got["redrill"]] == [a1, a2]

    # 키 없이 만든 기본 점검(실패가 아님)은 키가 생겨도 다시 점검하지 않는다
    monkeypatch.setattr(settings, "openai_api_key", "")
    s2 = _session(client, h, 1)
    b1 = s2["answers"][0]["id"]
    client.patch(f"/practice/answers/{b1}", json={"transcript": T1}, headers=h)
    assert client.post(f"/practice/answers/{b1}/coach", headers=h).json()["coaching_report"]["method"] == "basic"
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    n = len(calls)
    client.post(f"/practice/sessions/{s2['id']}/finish", headers=h)
    assert _kinds(calls[n:]) == ["debrief"]


# ───────── 오래 걸리는 작업과 작업 중에 들어온 요청 ─────────

class _Clock:
    """디브리프 모듈이 보는 시각을 테스트가 정한다(실제로 몇 분씩 기다리지 않고 오래 걸리는 작업을 흉내 낸다)."""

    def __init__(self, monkeypatch):
        self.now = datetime.now(timezone.utc)
        clock = self

        class Fixed(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now if tz else clock.now.replace(tzinfo=None)

        monkeypatch.setattr(debrief, "datetime", Fixed)


def test_long_job_keeps_a_heartbeat_so_retry_does_not_start_a_second_job(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-heartbeat"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    clock = _Clock(monkeypatch)
    calls: list = []
    fake = _fake(calls)
    entered, resume = Event(), Event()

    def slow(system, user, json_mode=False, **kwargs):
        out = fake(system, user, json_mode, **kwargs)
        if system == coaching.SYSTEM:
            clock.now += timedelta(minutes=4)
            if _kinds(calls).count("coach") == 2:
                entered.set()
                assert resume.wait(5)
        return out

    monkeypatch.setattr(llm, "_chat", slow)
    s = _session(client, h, 3)
    for a, t in zip(s["answers"], (T1, T2, T1)):
        client.patch(f"/practice/answers/{a['id']}", json={"transcript": t}, headers=h)
    with ThreadPoolExecutor(max_workers=1) as pool:
        finish = pool.submit(client.post, f"/practice/sessions/{s['id']}/finish", headers=h)
        assert entered.wait(5)
        try:
            # 작업을 시작한 지 8분: 시작 시각만 보면 사라진 작업이지만, 4분 전에 신호를 남겼으니 도는 중이다
            mid = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
            again = client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()
        finally:
            resume.set()
        finish.result(timeout=10)
    assert mid["debrief_status"] == "pending" and mid["debrief_running"] is True
    assert again["debrief_running"] is True
    assert _kinds(calls).count("coach") == 3  # 같은 답변을 두 작업이 점검하지 않는다
    done = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert done["debrief_status"] == "done" and done["debrief_running"] is False
    with SessionLocal() as db:
        x = db.get(PracticeSession, s["id"])
        assert (x.debrief_started_at, x.debrief_heartbeat_at, x.debrief_requested_at) == (None, None, None)


def test_lost_job_that_comes_back_does_not_overwrite_the_new_job(client, monkeypatch):
    """신호가 5분 넘게 끊겨 다시 시작했다면, 돌아온 옛 작업은 결과를 쓰지 않고 새 작업의 표시도 지우지 않는다."""
    h = {"X-User-Id": "user-debrief-takeover"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    clock = _Clock(monkeypatch)
    calls: list = []
    fake = _fake(calls)
    entered, resume = Event(), Event()

    def stuck_once(system, user, json_mode=False, **kwargs):
        out = fake(system, user, json_mode, **kwargs)
        if system == coaching.SYSTEM and not entered.is_set():
            entered.set()
            assert resume.wait(5)
        return out

    monkeypatch.setattr(llm, "_chat", stuck_once)
    s = _session(client, h, 2)
    for a, t in zip(s["answers"], (T1, T2)):
        client.patch(f"/practice/answers/{a['id']}", json={"transcript": t}, headers=h)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, f"/practice/sessions/{s['id']}/finish", headers=h)
        assert entered.wait(5)
        try:
            clock.now += timedelta(minutes=6)
            assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["debrief_running"] is False
            client.post(f"/practice/sessions/{s['id']}/debrief", headers=h)  # 새 작업이 이어받아 끝낸다
            taken = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
        finally:
            resume.set()
        first.result(timeout=10)
    assert taken["debrief_status"] == "done"
    assert _kinds(calls).count("debrief") == 1  # 돌아온 옛 작업은 요약을 만들지 않는다
    after = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert after["debrief"] == taken["debrief"] and after["debrief_status"] == "done"


def test_finish_during_a_running_job_makes_the_job_run_again(client, monkeypatch):
    """작업이 요약을 만드는 동안 마지막 답변을 저장하고 '면접 마치고 회고 보기'를 누르면, 그 요청을 버리지 않고
    작업이 한 바퀴 더 돌아 그 답변까지 점검하고 요약한다."""
    h = {"X-User-Id": "user-debrief-rerun"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    fake = _fake(calls)
    entered, resume = Event(), Event()

    def slow_summary(system, user, json_mode=False, **kwargs):
        out = fake(system, user, json_mode, **kwargs)
        if system == llm._DEBRIEF_SYSTEM and not entered.is_set():
            entered.set()
            assert resume.wait(5)
        return out

    monkeypatch.setattr(llm, "_chat", slow_summary)
    s = _session(client, h, 2)
    a1, a2 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"transcript": T1}, headers=h)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(client.post, f"/practice/sessions/{s['id']}/debrief", headers=h)  # 끝내기 전에 '디브리프 만들기'
        assert entered.wait(5)
        try:
            client.patch(f"/practice/answers/{a2}", json={"transcript": T2}, headers=h)
            fin = client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()
        finally:
            resume.set()
        job.result(timeout=10)
    assert fin["debrief_running"] is True  # 작업을 하나 더 붙이지 않는다
    assert _kinds(calls) == ["coach", "debrief", "coach", "debrief"]
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "done" and got["finished_at"]
    assert got["answers"][1]["coaching_report"]["method"] == "ai"
    last = json.loads(calls[-1]["user"])
    assert [x["transcript"] for x in last["answers"]] == [T1, T2]
