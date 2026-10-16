"""P0-3: 세션 종료 자동 디브리프와 약점 재연습."""
import json
from datetime import datetime, timedelta, timezone

from app import llm
from app.config import settings
from app.db import SessionLocal
from app.models import PracticeAnswer, PracticeSession
from app.routers import practice
from app.rubric import question_type, transcript_sha

T1 = "작년 동아리에서 저는 회계 정리를 맡았고 엑셀 매크로로 정산 시간을 절반으로 줄였습니다."
T2 = "지원 동기는 고객 데이터를 직접 다루는 일을 하고 싶어서입니다."


def _bank(client, h, n):
    qs = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    return [q for q in qs if "자기소개" not in q["text"]][:n]


def _experience(client, h, n):
    """상황·행동·결과를 모두 채점하는 과거 경험 질문 n개."""
    qs = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    return [q for q in qs if question_type(q["category"], q["text"], q["source"]) == "experience"][:n]


def _grader(calls, weak_key=None):
    """채점·디브리프 요청을 흉내 낸다. 채점은 전사문 앞부분을 그대로 인용한다."""
    def fake_chat(system, user, json_mode=False, **kwargs):
        calls.append({"system": system, "user": user, **kwargs})
        if system == llm._GRADE_SYSTEM:
            transcript = user.split("[답변 전사문]\n", 1)[1]
            return json.dumps({"criteria": [
                {"key": "situation", "band": "일부", "quote": transcript[:8], "comment": "맥락이 짧다"},
                {"key": "action", "band": "부족" if weak_key == "action" else "충분", "quote": "", "comment": "-"},
                {"key": "relevance", "band": "일부", "quote": "지어낸 인용입니다", "comment": "-"},
            ], "rewrite": ["결론부터 말해 보세요."], "summary": "요약"})
        if system == llm._DEBRIEF_SYSTEM:
            return json.dumps({"lesson": "결과를 수치로 말할 때 답이 선명했다", "next_action": "첫 문장에 결론을 말한다",
                               "moments": [{"order_no": 1, "quote": "정산 시간을 절반으로 줄였습니다", "why": "수치"},
                                           {"order_no": 2, "quote": "전사문에 없는 문장", "why": "지어냄"}]})
        raise AssertionError("예상하지 못한 프롬프트")
    return fake_chat


def test_finish_runs_debrief_with_mocked_llm(client, monkeypatch):
    h = {"X-User-Id": "user-debrief"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _grader(calls))
    qs = _experience(client, h, 3)
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"] for q in qs]}, headers=h).json()
    a1, a2, a3 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"transcript": T1, "self_rating": 4}, headers=h)
    client.patch(f"/practice/answers/{a2}", json={"transcript": T2}, headers=h)

    r = client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()
    assert r["debrief_status"] == "pending"  # 응답은 바로, 디브리프는 백그라운드에서
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "done"
    grading = [c for c in calls if c["system"] == llm._GRADE_SYSTEM]
    assert len(grading) == 2 and all(c["temperature"] == 0.2 for c in calls)
    by_id = {a["id"]: a for a in got["answers"]}
    for aid in (a1, a2):
        fb = by_id[aid]["feedback"]
        assert fb["rubric"] == "star-v1" and fb["criteria"][0]["quote_verified"] is True
        assert fb["question_type"] == "experience" and fb["transcript_sha"] == transcript_sha(by_id[aid]["transcript"])
        # 인용 없는 '충분'은 근거가 없으니 '일부'로 낮춘다
        assert fb["criteria"][1]["band"] == "일부" and fb["criteria"][1]["evidence_missing"] is True
        assert fb["criteria"][2]["quote"] is None and fb["criteria"][2]["quote_verified"] is False
    assert by_id[a3]["feedback"] is None
    d = got["debrief"]
    assert d["lesson"] and d["next_action"] and d["generated_at"] and d["model"] == settings.openai_feedback_model
    assert d["moments"] == [{"answer_id": a1, "order_no": 1, "quote": "정산 시간을 절반으로 줄였습니다", "why": "수치"}]
    assert [w["reasons"] for w in got["redrill"]] == [["건너뜀"]]

    # 이어서 녹음한 뒤 다시 끝내면 요약만 새로 만들고, 낡지 않은 채점은 다시 하지 않는다
    n = len(calls)
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()["debrief_status"] == "pending"
    assert [c["system"] for c in calls[n:]] == [llm._DEBRIEF_SYSTEM]
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["debrief_status"] == "done"


def test_debrief_failure_keeps_grades_and_can_regenerate(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-fail"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    good = _grader(calls)

    def no_summary(system, user, json_mode=False, **kwargs):
        if system == llm._DEBRIEF_SYSTEM:
            return "깨진 응답"
        return good(system, user, json_mode, **kwargs)

    monkeypatch.setattr(llm, "_chat", no_summary)
    q = _bank(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "failed" and got["debrief"] is None
    assert got["answers"][0]["feedback"]["rubric"] == "star-v1"  # 채점은 남는다

    monkeypatch.setattr(llm, "_chat", good)
    r = client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()
    assert r["debrief_status"] == "pending"
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["debrief_status"] == "done" and got["debrief"]["moments"][0]["answer_id"] == aid


def test_finish_without_key_or_transcript(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-off"}
    q = _bank(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    client.patch(f"/practice/answers/{s['answers'][0]['id']}", json={"transcript": T1}, headers=h)
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()["debrief_status"] == "unavailable"
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "unavailable"

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    s2 = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    assert client.post(f"/practice/sessions/{s2['id']}/finish", headers=h).json()["debrief_status"] == "none"


def test_weak_list_and_redrill(client, monkeypatch):
    h = {"X-User-Id": "user-redrill"}
    qs = _bank(client, h, 4)
    app_id = client.post("/track/applications", json={"company": "토스", "position": "데이터 분석가"},
                         headers=h).json()["id"]
    s = client.post("/practice/sessions", json={"mode": "mock", "question_ids": [q["id"] for q in qs],
                                                "prep_sec": 20, "answer_sec": 45, "title": "금요일 모의",
                                                "application_id": app_id},
                    headers=h).json()
    a1, a2, a3, a4 = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{a1}", json={"self_rating": 2}, headers=h)
    client.patch(f"/practice/answers/{a2}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{a4}", json={"transcript": T2, "self_rating": 5}, headers=h)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _grader(calls, weak_key="action"))
    assert client.post(f"/practice/answers/{a2}/feedback", headers=h).status_code == 200
    assert "토스 · 데이터 분석가" in calls[0]["user"]  # 지원 건의 회사·직무를 채점에 넘긴다
    monkeypatch.setattr(settings, "openai_api_key", "")

    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert [(w["answer_id"], w["reasons"]) for w in got["redrill"]] == [(a1, ["자기평가 2점"]), (a2, ["본인 행동 부족"])]
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)  # 끝나면 녹음 안 한 질문은 '건너뜀'
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    weak = got["redrill"]
    assert [w["answer_id"] for w in weak] == [a1, a2, a3] and weak[2]["reasons"] == ["건너뜀"]
    assert weak[0]["question_id"] == qs[0]["id"] and weak[0]["question_text"] == qs[0]["text"]
    assert weak[2]["order_no"] == 3

    r = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["redrill_of"] == s["id"] and new["mode"] == "mock"
    assert (new["prep_sec"], new["answer_sec"], new["application_id"]) == (20, 45, app_id)
    assert new["title"] == "다시 연습 · 금요일 모의"
    assert [a["question"]["id"] for a in new["answers"]] == [qs[0]["id"], qs[1]["id"], qs[2]["id"]]  # 자기소개 없음
    assert [a["order_no"] for a in new["answers"]] == [1, 2, 3]
    me = next(x for x in client.get("/practice/sessions", headers=h).json() if x["id"] == new["id"])
    assert me["redrill_of"] == s["id"]

    one = client.post(f"/practice/sessions/{s['id']}/redrill", json={"answer_ids": [a4]}, headers=h).json()
    assert [a["question"]["id"] for a in one["answers"]] == [qs[3]["id"]]
    bad = client.post(f"/practice/sessions/{s['id']}/redrill", json={"answer_ids": [new["answers"][0]["id"]]},
                      headers=h)
    assert bad.status_code == 422

    # 전사문을 고치면 낡은 '부족'은 약점 이유에서 빠진다
    client.patch(f"/practice/answers/{a2}", json={"transcript": "고친 답변"}, headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert [w["answer_id"] for w in got["redrill"]] == [a1, a3]

    # 원래 세션을 지우면 재연습 세션의 연결만 끊긴다
    assert client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code == 204
    assert client.get(f"/practice/sessions/{new['id']}", headers=h).json()["redrill_of"] is None


def test_redrill_nothing_weak_and_other_user(client):
    h, other = {"X-User-Id": "user-redrill-none"}, {"X-User-Id": "user-redrill-other"}
    q = _bank(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    r = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert r.status_code == 422 and r.json()["detail"] == "다시 연습할 약점 질문이 없어요"
    assert client.post(f"/practice/sessions/{s['id']}/redrill", headers=other).status_code == 404
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=other).status_code == 404
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=other).status_code == 404
    assert client.delete(f"/practice/answers/{s['answers'][0]['id']}/audio", headers=other).status_code == 404
    assert client.post(f"/practice/answers/{s['answers'][0]['id']}/feedback", headers=other).status_code == 404


def test_finish_does_not_start_second_debrief_while_pending(client, monkeypatch):
    h = {"X-User-Id": "user-debrief-pending"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    calls: list = []
    monkeypatch.setattr(llm, "_chat", _grader(calls))
    q = _bank(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    client.patch(f"/practice/answers/{s['answers'][0]['id']}", json={"transcript": T1}, headers=h)
    with SessionLocal() as db:
        x = db.get(PracticeSession, s["id"])
        x.debrief_status, x.debrief_started_at = "pending", datetime.now(timezone.utc)  # 다른 작업이 만드는 중
        db.commit()
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()["debrief_status"] == "pending"
    # 2분 뒤 화면의 '다시 시도'가 보내는 재생성 요청도 도는 작업이 있으면 하나 더 붙이지 않는다
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "pending"
    assert calls == []

    # 5분이 지나도 'pending'이면 작업이 사라진 것(서버 재시작 등)으로 보고 다시 시작한다
    with SessionLocal() as db:
        db.get(PracticeSession, s["id"]).debrief_started_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()
    assert client.post(f"/practice/sessions/{s['id']}/debrief", headers=h).json()["debrief_status"] == "pending"
    assert [c["system"] for c in calls] == [llm._GRADE_SYSTEM, llm._DEBRIEF_SYSTEM]
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["debrief_status"] == "done"


def _edit_transcript(answer_id: str, text: str) -> None:
    """다른 요청(PATCH)이 전사문을 고친 것처럼 별도 DB 세션에서 바꾼다."""
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, answer_id)
        practice._set_transcript(a, text)
        db.commit()


def test_debrief_never_pairs_new_transcript_with_old_grade(client, monkeypatch):
    """디브리프가 앞 답변을 채점하는 동안 전사문을 고쳐도, 옛 전사문의 채점이 새 전사문에 붙지 않는다."""
    h = {"X-User-Id": "user-debrief-race"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    t2_old, t2_new = "작년 동아리에서 저는 발표를 맡았습니다.", "인턴십에서 저는 데이터 정리 자동화를 맡았습니다."
    a1_new = "고친 첫 답변입니다. 저는 일정을 다시 짰습니다."
    calls: list = []
    grade = _grader(calls)
    ids: dict = {}

    def racing(system, user, json_mode=False, **kwargs):
        out = grade(system, user, json_mode, **kwargs)
        if system == llm._GRADE_SYSTEM and len([c for c in calls if c["system"] == llm._GRADE_SYSTEM]) == 1:
            _edit_transcript(ids["a1"], a1_new)  # 채점 중인 답변을 고침
            _edit_transcript(ids["a2"], t2_new)  # 아직 채점하지 않은 답변을 고침
        return out

    monkeypatch.setattr(llm, "_chat", racing)
    qs = _experience(client, h, 2)
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"] for q in qs]}, headers=h).json()
    ids["a1"], ids["a2"] = (a["id"] for a in s["answers"])
    client.patch(f"/practice/answers/{ids['a1']}", json={"transcript": T1}, headers=h)
    client.patch(f"/practice/answers/{ids['a2']}", json={"transcript": t2_old}, headers=h)

    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    a1, a2 = got["answers"]
    assert got["debrief_status"] == "done"
    # 채점 중에 바뀐 a1: 옛 전사문의 채점은 버린다
    assert a1["transcript"] == a1_new and a1["feedback"] is None
    # a2: 채점 직전에 다시 읽어 새 전사문으로 채점한다
    graded = [c["user"] for c in calls if c["system"] == llm._GRADE_SYSTEM]
    assert len(graded) == 2 and t2_new in graded[1] and t2_old not in graded[1]
    assert a2["transcript"] == t2_new and a2["feedback"]["stale"] is False
    assert a2["feedback"]["criteria"][0]["quote"] == t2_new[:8]
    # 요약도 지금 전사문으로 만든다
    summary = next(c["user"] for c in calls if c["system"] == llm._DEBRIEF_SYSTEM)
    assert a1_new in summary and t2_new in summary and t2_old not in summary


def test_feedback_for_other_transcript_counts_as_stale(client):
    """저장된 채점의 전사문 지문이 지금 전사문과 다르면 API·약점 목록 모두 낡은 피드백으로 본다."""
    h = {"X-User-Id": "user-sha-stale"}
    q = _experience(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    fb = {"rubric": "star-v1", "criteria": [{"key": "action", "label": "본인 행동", "band": "부족"}], "stale": False}
    with SessionLocal() as db:
        db.get(PracticeAnswer, aid).feedback = {**fb, "transcript_sha": transcript_sha("다른 전사문")}
        db.commit()
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["answers"][0]["feedback"]["stale"] is True and got["redrill"] == []

    with SessionLocal() as db:
        db.get(PracticeAnswer, aid).feedback = {**fb, "transcript_sha": transcript_sha(T1)}
        db.commit()
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert got["answers"][0]["feedback"]["stale"] is False and got["redrill"][0]["reasons"] == ["본인 행동 부족"]


def test_manual_grade_is_not_saved_when_transcript_changes_meanwhile(client, monkeypatch):
    h = {"X-User-Id": "user-grade-race"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    q = _experience(client, h, 1)[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": T1}, headers=h)
    grade = _grader([])

    def racing(system, user, json_mode=False, **kwargs):
        _edit_transcript(aid, "채점 중에 고친 전사문입니다.")
        return grade(system, user, json_mode, **kwargs)

    monkeypatch.setattr(llm, "_chat", racing)
    r = client.post(f"/practice/answers/{aid}/feedback", headers=h)
    assert r.status_code == 409
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert a["transcript"] == "채점 중에 고친 전사문입니다." and a["feedback"] is None
