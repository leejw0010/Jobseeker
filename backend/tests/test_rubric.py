"""P0-2: 전사문 인용형 STAR 루브릭 피드백."""
import json

import httpx

from app import llm
from app.config import settings
from app.llm import normalize_feedback

TRANSCRIPT = "작년 캡스톤 프로젝트에서 저는 백엔드를 맡았습니다.\n  캐시를 도입해 응답 속도를 40% 줄였습니다."


def test_normalize_feedback_filters_model_output():
    raw = {
        "criteria": [
            {"key": "relevance", "band": "일부", "quote": "", "comment": "직무 연결이 약하다"},
            {"key": "situation", "band": "충분", "quote": "“…작년 캡스톤   프로젝트에서 저는…”", "comment": "c" * 300,
             "score": 5},
            {"key": "action", "band": "충분", "quote": "제가 팀을 이끌어 문제를 해결했습니다", "comment": "지어낸 인용"},
            {"key": "result", "band": "보통", "quote": "40% 줄였습니다", "comment": "없는 등급"},
            {"key": "confidence", "band": "충분", "quote": "저는", "comment": "없는 기준"},
            {"key": "situation", "band": "부족", "quote": "", "comment": "중복"},
        ],
        "rewrite": ["  첫 문장에서 결론을 말하세요.  ", "", "둘째 문장", "셋째 문장"],
        "summary": "요약 " * 100,
        "extra": "무시",
    }
    fb = normalize_feedback(raw, TRANSCRIPT)
    assert set(fb) == {"criteria", "rewrite", "summary"}
    assert [c["key"] for c in fb["criteria"]] == ["situation", "action", "relevance"]  # 루브릭 순서, 중복·무효 제거
    sit, act, rel = fb["criteria"]
    assert set(sit) == {"key", "label", "band", "quote", "quote_verified", "comment"}
    assert (sit["label"], act["label"], rel["label"]) == ("상황·과제", "본인 행동", "질문·직무 연결")
    assert sit["band"] == "충분" and sit["quote"] == "작년 캡스톤 프로젝트에서 저는" and sit["quote_verified"] is True
    assert len(sit["comment"]) == 200
    assert act["quote"] is None and act["quote_verified"] is False
    assert rel["quote"] is None and rel["quote_verified"] is None
    assert fb["rewrite"] == ["첫 문장에서 결론을 말하세요.", "둘째 문장"]
    assert len(fb["summary"]) <= 200


def test_quote_across_line_break_is_verified():
    fb = normalize_feedback({"criteria": [{"key": "result", "band": "충분",
                                           "quote": "맡았습니다. 캐시를 도입해", "comment": "x"}]}, TRANSCRIPT)
    assert fb["criteria"][0]["quote_verified"] is True


def test_relevance_cannot_be_not_applicable():
    fb = normalize_feedback({"criteria": [{"key": "relevance", "band": "해당 없음"},
                                          {"key": "situation", "band": "해당 없음"}]}, TRANSCRIPT)
    assert [(c["key"], c["band"]) for c in fb["criteria"]] == [("situation", "해당 없음")]


def test_grading_uses_feedback_model_low_temperature_and_base_url(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_base_url", "http://fake-openai.local/v1")
    monkeypatch.setattr(settings, "openai_feedback_model", "grader-model")
    sent = {}
    content = json.dumps({"criteria": [{"key": "result", "band": "충분", "quote": "40% 줄였습니다", "comment": "수치"}],
                          "rewrite": [], "summary": "결과가 분명하다"})

    def fake_post(url, headers=None, timeout=None, **kwargs):
        sent.update(url=url, body=kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    fb = llm.grade_answer("성과를 낸 경험은?", TRANSCRIPT, "네이버 · 백엔드")
    assert sent["url"] == "http://fake-openai.local/v1/chat/completions"
    assert sent["body"]["temperature"] == 0.2 and sent["body"]["model"] == "grader-model"
    assert sent["body"]["response_format"] == {"type": "json_object"}
    assert sent["body"]["messages"][0]["content"] == llm._GRADE_SYSTEM
    assert "네이버 · 백엔드" in sent["body"]["messages"][1]["content"]
    assert fb["rubric"] == "star-v1" and fb["model"] == "grader-model" and fb["stale"] is False and fb["graded_at"]
    assert fb["criteria"][0]["quote_verified"] is True


def test_generation_keeps_chat_model_and_temperature(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    seen = {}

    def fake_chat(system, user, json_mode=False, **kwargs):
        seen.update(kwargs)
        return json.dumps({"questions": [{"category": "직무", "text": "질문"}]})

    monkeypatch.setattr(llm, "_chat", fake_chat)
    llm.generate_questions("A", "B", "", 1)
    assert seen.get("temperature", 0.7) == 0.7 and seen.get("model") is None


def test_rubric_endpoint(client):
    r = client.get("/practice/rubric").json()
    assert r["version"] == "star-v1" and r["bands"] == ["충분", "일부", "부족", "해당 없음"]
    assert [c["key"] for c in r["criteria"]] == ["situation", "action", "result", "relevance"]
    assert "Kendall" in r["note"]


def test_feedback_errors_and_stale_on_transcript_change(client, monkeypatch):
    h = {"X-User-Id": "user-rubric"}
    bank = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [bank[0]["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    assert client.post(f"/practice/answers/{aid}/feedback", headers=h).status_code == 422  # 전사문 없음
    client.patch(f"/practice/answers/{aid}", json={"transcript": TRANSCRIPT}, headers=h)
    assert client.post(f"/practice/answers/{aid}/feedback", headers=h).status_code == 503  # 키 없음

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "_chat", lambda system, user, **kwargs: "JSON이 아님")
    r = client.post(f"/practice/answers/{aid}/feedback", headers=h)
    assert r.status_code == 502 and r.json()["detail"] == "AI 응답을 해석하지 못했습니다"

    def http_down(system, user, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(llm, "_chat", http_down)
    assert client.post(f"/practice/answers/{aid}/feedback", headers=h).status_code == 502

    monkeypatch.setattr(llm, "_chat", lambda system, user, **kwargs: json.dumps(
        {"criteria": [{"key": "action", "band": "부족", "quote": "", "comment": "본인 몫이 없다"}],
         "rewrite": ["저는 캐시 키 설계를 맡았습니다."], "summary": "본인 행동을 말하세요"}))
    a = client.post(f"/practice/answers/{aid}/feedback", headers=h).json()
    assert a["feedback"]["criteria"][0]["band"] == "부족" and a["feedback"]["stale"] is False

    # 같은 전사문이면 그대로, 달라지면 낡은 피드백으로 표시(내용은 유지)
    a = client.patch(f"/practice/answers/{aid}", json={"transcript": TRANSCRIPT, "self_rating": 3}, headers=h).json()
    assert a["feedback"]["stale"] is False
    a = client.patch(f"/practice/answers/{aid}", json={"transcript": "고친 전사문"}, headers=h).json()
    assert a["feedback"]["stale"] is True and a["feedback"]["criteria"][0]["key"] == "action"
    again = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert again["feedback"]["stale"] is True  # 저장까지 됐는지
