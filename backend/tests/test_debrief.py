"""P0-3: 세션 종료 자동 디브리프와 약점 재연습."""
import json

from app import llm
from app.config import settings
from app.db import SessionLocal
from app.models import PracticeSession

T1 = "작년 동아리에서 저는 회계 정리를 맡았고 엑셀 매크로로 정산 시간을 절반으로 줄였습니다."
T2 = "지원 동기는 고객 데이터를 직접 다루는 일을 하고 싶어서입니다."


def _bank(client, h, n):
    qs = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    return [q for q in qs if "자기소개" not in q["text"]][:n]


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
    qs = _bank(client, h, 3)
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
        db.get(PracticeSession, s["id"]).debrief_status = "pending"  # 다른 작업이 만드는 중
        db.commit()
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).json()["debrief_status"] == "pending"
    assert calls == []
