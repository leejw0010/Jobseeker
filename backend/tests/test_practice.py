U1 = {"X-User-Id": "user-practice-1"}
U2 = {"X-User-Id": "user-practice-2"}


def test_question_bank_seeded(client):
    r = client.get("/practice/questions", headers=U1)
    assert r.status_code == 200
    assert len(r.json()) >= 25
    dev = client.get("/practice/questions", params={"job_category": "개발", "category": "직무"}, headers=U1).json()
    assert dev and all(q["job_category"] == "개발" for q in dev)


def test_generate_without_api_key_uses_essay(client):
    essay = "대학 시절 캡스톤 프로젝트에서 백엔드를 담당해 API 응답 속도를 40% 개선했습니다. 팀원과 협업하며 일정을 지켰습니다."
    r = client.post("/practice/questions/generate",
                    json={"company": "네이버", "position": "백엔드 개발자", "job_category": "개발",
                          "essay_text": essay, "count": 4}, headers=U1)
    assert r.status_code == 201, r.text
    qs = r.json()
    assert len(qs) == 4
    assert all(q["source"] == "generated" for q in qs)
    assert any("캡스톤" in q["text"] for q in qs)
    # 다른 사용자에게는 보이지 않는다
    other = client.get("/practice/questions", params={"source": "generated"}, headers=U2).json()
    assert other == []


def test_mock_session_flow(client):
    r = client.post("/practice/sessions", json={"mode": "mock", "count": 3, "answer_sec": 60}, headers=U1)
    assert r.status_code == 201, r.text
    s = r.json()
    assert len(s["answers"]) == 3 and s["answer_sec"] == 60
    ans = s["answers"][0]

    up = client.post(f"/practice/answers/{ans['id']}/audio",
                     files={"file": ("a.webm", b"\x1aE\xdf\xa3fakewebm", "audio/webm")},
                     data={"duration_sec": "42.5"}, headers=U1)
    assert up.status_code == 200, up.text
    assert up.json()["stt_status"] == "unavailable"
    assert up.json()["duration_sec"] == 42.5

    audio = client.get(f"/practice/answers/{ans['id']}/audio", headers=U1)
    assert audio.status_code == 200 and audio.content.startswith(b"\x1aE")

    p = client.patch(f"/practice/answers/{ans['id']}",
                     json={"self_rating": 4, "reflection_note": "결론을 먼저 말하자", "transcript": "수동 입력"}, headers=U1)
    assert p.json()["self_rating"] == 4 and p.json()["transcript"] == "수동 입력"

    fb = client.post(f"/practice/answers/{ans['id']}/feedback", headers=U1)
    assert fb.status_code == 503  # API 키 없음

    client.post(f"/practice/sessions/{s['id']}/finish", headers=U1)
    summary = client.get("/practice/sessions", headers=U1).json()
    me = next(x for x in summary if x["id"] == s["id"])
    assert me["recorded_count"] == 1 and me["avg_rating"] == 4 and me["finished_at"]

    # 다른 사용자는 접근 불가
    assert client.get(f"/practice/sessions/{s['id']}", headers=U2).status_code == 404
    assert client.get(f"/practice/answers/{ans['id']}/audio", headers=U2).status_code == 404


def test_custom_question_and_delete(client):
    q = client.post("/practice/questions", json={"category": "인성", "text": "좌우명이 무엇인가요?"}, headers=U1).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=U1).json()
    assert s["answers"][0]["question"]["text"] == "좌우명이 무엇인가요?"
    bank_id = client.get("/practice/questions", params={"source": "bank"}, headers=U1).json()[0]["id"]
    assert client.delete(f"/practice/questions/{bank_id}", headers=U1).status_code == 404


def test_generate_skips_duplicates(client):
    h = {"X-User-Id": "user-dup"}
    body = {"company": "A사", "position": "기획자", "count": 3}
    first = client.post("/practice/questions/generate", json=body, headers=h).json()
    again = client.post("/practice/questions/generate", json=body, headers=h).json()
    assert len(first) == 3 and again == []
