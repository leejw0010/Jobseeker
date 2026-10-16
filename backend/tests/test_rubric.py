"""P0-2: 전사문 인용형 STAR 루브릭 피드백."""
import json

import httpx
import pytest

from app import llm
from app.config import settings
from app.llm import normalize_feedback, verify_quote
from app.rubric import question_type
from app.seed import BANK

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
    # 인용으로 확인되지 않은 긍정 판단: '충분'은 '일부'로 낮추고 근거 없음 표시
    assert act["band"] == "일부" and act["model_band"] == "충분" and act["evidence_missing"] is True
    assert rel["quote"] is None and rel["quote_verified"] is None and rel["evidence_missing"] is True
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
    q = next(x for x in bank if question_type(x["category"], x["text"]) == "experience")
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
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


def test_non_string_key_or_band_is_skipped_not_500(client, monkeypatch):
    fb = normalize_feedback({"criteria": [{"key": ["situation"], "band": "충분"}, {"key": {"k": 1}, "band": "일부"},
                                          {"key": "result", "band": ["부족"]},
                                          {"key": "action", "band": "부족", "quote": "", "comment": "x"}]}, TRANSCRIPT)
    assert [(c["key"], c["band"]) for c in fb["criteria"]] == [("action", "부족")]

    h = {"X-User-Id": "user-rubric-badkey"}
    bank = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [bank[0]["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": TRANSCRIPT}, headers=h)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "_chat", lambda system, user, **kwargs: json.dumps(
        {"criteria": [{"key": ["relevance"], "band": "충분"}]}))
    r = client.post(f"/practice/answers/{aid}/feedback", headers=h)
    assert r.status_code == 502 and r.json()["detail"] == "AI 응답을 해석하지 못했습니다"


@pytest.mark.parametrize("quote", ["", None, "성과를 수치로 잘 제시했습니다", "반응"])
def test_positive_band_without_verified_quote_is_downgraded(quote):
    """빈 인용·지어낸 인용·너무 짧은 인용의 '충분'은 '일부'로 낮추고 근거 없음으로 표시한다."""
    transcript = "결과적으로 반응이 좋았습니다"
    raw = {"criteria": [{"key": "result", "band": "충분", "quote": quote, "comment": "성과를 수치로 잘 제시함"},
                        {"key": "relevance", "band": "일부", "quote": quote, "comment": "c"},
                        {"key": "action", "band": "부족", "quote": "", "comment": "행동이 없다"}]}
    act, res, rel = normalize_feedback(raw, transcript, "experience")["criteria"]  # 루브릭 순서
    assert (res["band"], res["model_band"], res["evidence_missing"], res["quote"]) == ("일부", "충분", True, None)
    assert rel["band"] == "일부" and rel["evidence_missing"] is True and "model_band" not in rel
    assert act["band"] == "부족" and "evidence_missing" not in act  # '부족'은 인용이 없어도 된다
    # 전사문에서 확인된 인용이 있으면 '충분' 그대로
    raw["criteria"][0]["quote"] = "반응이 좋았습니다."
    res = normalize_feedback(raw, transcript, "experience")["criteria"][1]
    assert res["band"] == "충분" and res["quote_verified"] is True and "evidence_missing" not in res


@pytest.mark.parametrize("quote, transcript, expected", [
    ("응답 속도를 40% 줄였습니다.", "응답 속도를 40% 줄였습니다", ("응답 속도를 40% 줄였습니다", True)),  # 문장부호만 다름
    ("저는 데이터를", "어 그 저는 음 데이터를 정리했습니다", ("저는 음 데이터를", True)),  # 말버릇을 뺀 인용
    ("저는, 데이터를 정리했습니다", "저는 데이터를 정리했습니다.", ("저는 데이터를 정리했습니다", True)),
    ("네.", "네. 저는 데이터를 정리했습니다", (None, False)),  # 너무 짧은 인용은 근거로 치지 않는다
    ("저는", "저는 데이터를 정리했습니다", (None, False)),
    ("음... 어", "음 어 저는", (None, None)),  # 말버릇뿐이면 빈 인용
    ("데이터를 지웠습니다", "저는 데이터를 정리했습니다", (None, False)),
])
def test_verify_quote_ignores_punctuation_and_fillers(quote, transcript, expected):
    assert verify_quote(quote, transcript) == expected


def test_rewrite_with_invented_numbers_is_dropped():
    raw = {"criteria": [{"key": "result", "band": "일부", "quote": "응답 속도를 40% 줄였습니다", "comment": "c"}],
           "rewrite": ["그 결과 2주 만에 재방문율이 18% 올랐습니다.", "캐시로 응답 속도를 40% 줄여 [수치]명이 혜택을 봤습니다.",
                       "[기간] 동안 [본인 역할]로 캐시를 설계했습니다."]}
    fb = normalize_feedback(raw, TRANSCRIPT, "experience", "성과를 낸 경험은?")
    assert fb["rewrite"] == ["캐시로 응답 속도를 40% 줄여 [수치]명이 혜택을 봤습니다.", "[기간] 동안 [본인 역할]로 캐시를 설계했습니다."]
    # 질문에 있던 숫자는 지어낸 것이 아니다
    fb = normalize_feedback({"rewrite": ["10년 뒤에는 결제 팀을 이끌고 싶습니다."]}, "저는 리더가 되고 싶습니다", "self",
                            "입사 후 10년 뒤 본인의 모습을 말씀해 주세요.")
    assert fb["rewrite"] == ["10년 뒤에는 결제 팀을 이끌고 싶습니다."]


# 공용 질문은행 30개의 기대 유형(바꿀 때는 채점에 미치는 영향을 확인할 것)
EXPECTED_TYPES = {
    "1분 동안 자기소개를 해 주세요.": "self",
    "본인의 장점과 단점을 하나씩 말씀해 주세요.": "self",
    "살면서 가장 몰입했던 경험은 무엇인가요?": "experience",
    "스트레스를 받을 때 어떻게 해소하나요?": "hypothetical",
    "가장 크게 실패했던 경험과 그 경험에서 배운 점을 말씀해 주세요.": "experience",
    "주변 사람들은 본인을 어떤 사람이라고 평가하나요?": "self",
    "팀 프로젝트에서 무임승차하는 팀원이 있다면 어떻게 하겠습니까?": "hypothetical",
    "상사의 지시가 본인 생각과 다를 때 어떻게 하겠습니까?": "hypothetical",
    "마감 직전에 큰 오류를 발견했다면 어떻게 대처하겠습니까?": "hypothetical",
    "동시에 여러 업무가 몰렸을 때 우선순위를 어떻게 정하나요?": "hypothetical",
    "우리 회사에 지원한 동기는 무엇인가요?": "self",
    "입사 후 10년 뒤 본인의 모습을 말씀해 주세요.": "self",
    "다른 회사에도 지원했나요? 우리 회사가 1순위인 이유는 무엇인가요?": "self",
    "마지막으로 하고 싶은 말이 있나요?": "self",
    "가장 자신 있는 프로젝트를 소개하고, 본인이 맡은 기술적 역할을 설명해 주세요.": "experience",
    "프로세스와 스레드의 차이를 설명해 주세요.": "knowledge",
    "REST API를 설계할 때 중요하게 생각하는 원칙은 무엇인가요?": "knowledge",
    "데이터베이스 인덱스는 언제 성능을 높이고, 언제 오히려 떨어뜨리나요?": "knowledge",
    "해결하기 어려웠던 버그를 어떻게 찾아 고쳤는지 말씀해 주세요.": "experience",
    "코드 리뷰에서 지적을 받았을 때 어떻게 대응하나요?": "hypothetical",
    "최근 인상 깊게 사용한 서비스와 그 이유를 말씀해 주세요.": "knowledge",
    "서비스 지표가 갑자기 떨어졌다면 원인을 어떻게 분석하겠습니까?": "hypothetical",
    "개발자와 일정·범위를 두고 의견이 다를 때 어떻게 조율하나요?": "hypothetical",
    "최근 본 마케팅 캠페인 중 성공적이라고 생각한 사례를 분석해 주세요.": "knowledge",
    "한정된 예산으로 신규 고객을 늘려야 한다면 어떤 전략을 쓰겠습니까?": "hypothetical",
    "분석 결과가 직관과 다르게 나왔을 때 어떻게 검증하나요?": "hypothetical",
    "A/B 테스트를 설계할 때 주의해야 할 점은 무엇인가요?": "knowledge",
    "[언어] 다음 글의 핵심 주장을 한 문장으로 요약하는 연습: 최근 읽은 기사 하나를 30초 안에 요약해 보세요.": "aptitude",
    "[수리] 정가의 20%를 할인한 뒤 다시 10%를 할인하면 정가 대비 총 몇 % 할인인가요? 풀이 과정을 말해 보세요.": "aptitude",
    "[추리] 'A는 B보다 크고, C는 A보다 작지만 B보다 크다'일 때 세 값의 순서를 말해 보세요.": "aptitude",
}


def test_question_type_of_every_bank_question():
    assert len(BANK) == len(EXPECTED_TYPES) == 30
    got = {text: question_type(category, text, "bank") for category, _, text in BANK}
    assert got == EXPECTED_TYPES


def test_question_type_of_custom_questions():
    assert question_type("인성", "협업 경험은?", "custom") == "experience"
    assert question_type("직무", "Redis를 고른 이유는?", "generated") == "general"  # 단서 없으면 모델이 판단
    assert question_type("기업", "네이버에 지원한 이유와 입사 후 목표를 말씀해 주세요.", "generated") == "self"
    assert question_type("인성", "갈등이 생긴다면 어떻게 할 건가요?", "custom") == "hypothetical"
    # 과거형으로 끝나는 질문은 '~했을 때 어떻게'가 있어도 경험 질문(AI 꼬리질문에 자주 나오는 꼴)
    for text in ("팀에서 갈등이 생겼을 때 어떻게 해결했나요?", "협업 중 의견 충돌이 있었을 때 어떻게 대처하셨나요?",
                 "문제가 생겼을 때 어떻게 행동했습니까?"):
        assert question_type("인성", text, "generated") == "experience", text
    assert question_type("상황", "실수를 했을 때 어떻게 하겠습니까?", "custom") == "hypothetical"


def test_server_decides_not_applicable_by_question_type():
    model = {"criteria": [
        {"key": "situation", "band": "부족", "quote": "", "comment": "상황 없음"},
        {"key": "action", "band": "해당 없음"},
        {"key": "result", "band": "해당 없음"},
        {"key": "relevance", "band": "일부", "quote": "작년 캡스톤 프로젝트에서", "comment": "c"},
    ]}
    # 경험 질문: 모델이 '해당 없음'으로 피한 기준은 '부족'
    fb = normalize_feedback(model, TRANSCRIPT, "experience")
    assert [c["band"] for c in fb["criteria"]] == ["부족", "부족", "부족", "일부"]
    # 자기소개류: 상황·행동·결과는 모델 답과 상관없이 '해당 없음', relevance만 채점
    fb = normalize_feedback(model, TRANSCRIPT, "self")
    assert [c["band"] for c in fb["criteria"]] == ["해당 없음", "해당 없음", "해당 없음", "일부"]
    assert fb["criteria"][0]["comment"] is None
    # 가상 상황: 상황·결과는 '해당 없음', 행동은 채점(모델이 피하면 '부족')
    fb = normalize_feedback(model, TRANSCRIPT, "hypothetical")
    assert [c["band"] for c in fb["criteria"]] == ["해당 없음", "부족", "해당 없음", "일부"]
    # 유형을 모르면 모델이 판단(relevance만 '해당 없음' 불가)
    fb = normalize_feedback(model, TRANSCRIPT, "general")
    assert [c["band"] for c in fb["criteria"]] == ["부족", "해당 없음", "해당 없음", "일부"]


def _capture_grade(monkeypatch, reply: dict) -> list:
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    sent: list = []

    def fake_chat(system, user, json_mode=False, **kwargs):
        sent.append({"system": system, "user": user})
        return json.dumps(reply)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    return sent


def test_grade_prompt_carries_type_and_job_tie(monkeypatch):
    sent = _capture_grade(monkeypatch, {"criteria": [{"key": "relevance", "band": "부족", "quote": "", "comment": "c"}]})
    fb = llm.grade_answer("프로세스와 스레드의 차이를 설명해 주세요.", TRANSCRIPT, "네이버 · 백엔드", "knowledge")
    assert fb["question_type"] == "knowledge"
    assert [c["band"] for c in fb["criteria"]] == ["해당 없음", "해당 없음", "해당 없음", "부족"]
    assert "[질문 유형]\n지식·의견 질문" in sent[0]["user"] and "보지 않음" in sent[0]["user"]  # 지식 질문은 직무 연결 안 봄
    llm.grade_answer("가장 크게 실패했던 경험은?", TRANSCRIPT, "네이버 · 백엔드", "experience")
    assert "[질문·직무 연결]\n봄" in sent[1]["user"]
    llm.grade_answer("가장 크게 실패했던 경험은?", TRANSCRIPT, None, "experience")
    assert "[질문·직무 연결]\n보지 않음" in sent[2]["user"]  # 지원 건을 모르면 직무 연결을 요구하지 않는다


def test_prompts_forbid_we_to_i_advice_and_say_correctness_is_not_graded():
    for system in (llm._GRADE_SYSTEM, llm._DEBRIEF_SYSTEM):
        assert "'우리'를 '저'로 바꾸라는 조언은 하지 않는다" in system
    assert "정답 여부" in llm._GRADE_SYSTEM and "[수치]·[기간]·[본인 역할]" in llm._GRADE_SYSTEM
    assert "정답 여부" in llm.RUBRIC["note"]


def test_job_hint_only_from_application(client, monkeypatch):
    """지원 건이 없으면 회사·직무 정보 없이 채점한다(질문의 직무 분류를 회사·직무로 넘기지 않는다)."""
    h = {"X-User-Id": "user-rubric-hint"}
    bank = client.get("/practice/questions", params={"source": "bank", "category": "직무"}, headers=h).json()
    q = next(x for x in bank if question_type(x["category"], x["text"]) == "experience")
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    client.patch(f"/practice/answers/{aid}", json={"transcript": TRANSCRIPT}, headers=h)
    sent = _capture_grade(monkeypatch, {"criteria": [{"key": "relevance", "band": "부족", "quote": "", "comment": "c"}]})
    assert client.post(f"/practice/answers/{aid}/feedback", headers=h).status_code == 200
    assert "[지원 회사·직무]\n(정보 없음)" in sent[0]["user"] and "보지 않음" in sent[0]["user"]
