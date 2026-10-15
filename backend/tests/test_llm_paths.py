"""API 키가 있을 때의 경로를 OpenAI 호출 없이 확인한다."""
import json

from app import llm
from app.config import settings

U = {"X-User-Id": "user-llm"}


def test_openai_paths(client, monkeypatch, consent):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    def fake_chat(system, user, json_mode=False, **kwargs):
        if system == llm._GEN_SYSTEM:
            return json.dumps({"questions": [{"category": "직무", "text": "Redis를 고른 이유는?"},
                                             {"category": "없는분류", "text": "협업 경험은?"}]})
        return json.dumps({"criteria": [{"key": "relevance", "band": "일부", "quote": "안녕하세요",
                                         "comment": "결론이 늦다"}],
                           "rewrite": ["저는 캐시 장애를 줄이려고 Redis를 골랐습니다."], "summary": "결론부터 말하기"})

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "안녕하세요 저는")
    consent(U)

    qs = client.post("/practice/questions/generate", json={"company": "X", "count": 2}, headers=U).json()
    assert [q["category"] for q in qs] == ["직무", "인성"]  # 알 수 없는 분류는 '인성'으로

    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [qs[0]["id"]]}, headers=U).json()
    aid = s["answers"][0]["id"]
    a = client.post(f"/practice/answers/{aid}/audio", files={"file": ("r.webm", b"abc", "audio/webm")}, headers=U).json()
    assert a["stt_status"] == "done" and a["transcript"] == "안녕하세요 저는"
    a = client.post(f"/practice/answers/{aid}/feedback", headers=U).json()
    fb = a["feedback"]
    assert fb["rubric"] == "star-v1" and fb["stale"] is False and a["ai_feedback"] is None
    assert fb["criteria"] == [{"key": "relevance", "label": "질문·직무 연결", "band": "일부", "quote": "안녕하세요",
                               "quote_verified": True, "comment": "결론이 늦다"}]
