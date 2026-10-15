"""The coaching loop must keep the actual source and never fabricate evidence."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from app import llm
from app.config import settings
from app import coaching


def make_session(client, **options):
    headers = {"X-User-Id": f"coach-{uuid.uuid4()}"}
    app = client.post("/track/applications", headers=headers, json={
        "company": "테스트회사", "position": "백엔드 개발자", "job_category": "개발",
    }).json()
    item = client.post(f"/track/applications/{app['id']}/essays", headers=headers, json={
        "question_text": "성과 경험", "content": "프로젝트에서 캐시를 도입하여 응답 시간을 40% 개선했습니다.",
    }).json()
    submitted = item["versions"][0]
    client.post(f"/track/essays/{item['id']}/versions", headers=headers,
                json={"content": submitted["content"], "is_submitted": True})
    client.post(f"/track/essays/{item['id']}/versions", headers=headers,
                json={"content": "새로운 프로젝트에서 검색 기능을 담당하고 70% 개선했습니다."})
    q = client.post("/practice/questions", headers=headers, json={
        "category": "직무", "text": "성과를 어떻게 측정하셨나요?",
    }).json()
    response = client.post("/practice/sessions", headers=headers, json={
        "mode": "free", "application_id": app["id"], "question_ids": [q["id"]],
        "followups_enabled": True, "job_description": "API 성능 측정과 캐시 운영 경험", **options,
    })
    assert response.status_code == 201, response.text
    return headers, response.json(), app, item, submitted


def answer(client, headers, session, transcript="프로젝트에서 제가 개선했습니다."):
    aid = session["answers"][0]["id"]
    r = client.patch(f"/practice/answers/{aid}", headers=headers, json={"transcript": transcript})
    assert r.status_code == 200, r.text
    return aid


def test_session_freezes_submitted_version_and_survives_source_edits(client):
    h, s, app, item, submitted = make_session(client)
    snapshot = s.get("context_snapshot")
    assert snapshot is not None, "session must retain a source snapshot"
    assert snapshot["essays"][0]["version_id"] == submitted["id"]
    assert snapshot["essays"][0]["selection"] == "submitted"
    assert snapshot["job_description"] == "API 성능 측정과 캐시 운영 경험"
    client.post(f"/track/essays/{item['id']}/versions", headers=h, json={"content": "이후 수정", "is_submitted": True})
    client.patch(f"/track/applications/{app['id']}", headers=h, json={"company": "수정된회사"})
    later = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert later["context_snapshot"] == snapshot


def test_latest_version_can_be_chosen_explicitly(client):
    _, s, _, _, _ = make_session(client, essay_basis="latest")
    snapshot = s.get("context_snapshot")
    assert snapshot is not None
    assert snapshot["essays"][0]["selection"] == "latest"
    assert "70%" in snapshot["essays"][0]["content"]


def test_session_checks_application_ownership_even_with_explicit_questions(client):
    h, _, app, _, _ = make_session(client)
    stranger = {"X-User-Id": "stranger-coach"}
    bank = client.get("/practice/questions", headers=stranger).json()[0]
    r = client.post("/practice/sessions", headers=stranger, json={
        "mode": "free", "application_id": app["id"], "question_ids": [bank["id"]],
    })
    assert r.status_code == 404


def test_basic_coaching_works_without_key_and_is_not_labeled_ai(client):
    h, s, _, _, submitted = make_session(client)
    aid = answer(client, h, s)
    r = client.post(f"/practice/answers/{aid}/coach", headers=h)
    assert r.status_code == 200, r.text
    report = r.json()["coaching_report"]
    assert report["method"] == "basic"
    assert {c["key"] for c in report["criteria"]} == {"specificity", "relevance", "consistency"}
    assert any(c["status"] == "보완" for c in report["criteria"])
    assert report["followup"]["answer_quote"] in "프로젝트에서 제가 개선했습니다."
    assert report["followup"]["source_quote"] in submitted["content"]


def test_followup_is_answer_dependent_idempotent_and_limited_to_one_level(client):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    url = f"/practice/answers/{aid}/followup"
    first = client.post(url, headers=h)
    assert first.status_code == 201, first.text
    again = client.post(url, headers=h)
    assert again.status_code == 201
    assert len(again.json()["answers"]) == 2
    child = first.json()["answers"][1]
    assert child["parent_answer_id"] == aid
    assert child["id"] == again.json()["answers"][1]["id"]
    assert "측정" in child["question"]["text"]
    assert child["followup_reason"]
    client.patch(f"/practice/answers/{child['id']}", headers=h, json={"transcript": "후속 답변"})
    assert client.post(f"/practice/answers/{child['id']}/followup", headers=h).status_code == 409
    assert client.post(url, headers={"X-User-Id": "other-coach"}).status_code == 404


def test_empty_answer_disabled_and_finished_session_do_not_start_followup(client):
    h, s, _, _, _ = make_session(client)
    aid = s["answers"][0]["id"]
    assert client.post(f"/practice/answers/{aid}/coach", headers=h).status_code == 422
    assert client.post(f"/practice/answers/{aid}/followup", headers=h).status_code == 422
    answer(client, h, s)
    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    assert client.post(f"/practice/answers/{aid}/followup", headers=h).status_code == 409
    h2, s2, _, _, _ = make_session(client, followups_enabled=False)
    aid2 = answer(client, h2, s2)
    assert client.post(f"/practice/answers/{aid2}/followup", headers=h2).status_code == 409


def test_transcript_edit_invalidates_old_coaching(client):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    r = client.post(f"/practice/answers/{aid}/coach", headers=h)
    assert r.status_code == 200, r.text
    changed = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "새 답변입니다."}).json()
    assert changed["coaching_report"] is None


def test_redrill_uses_weak_answers_and_the_same_frozen_context(client):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    assert client.post(f"/practice/answers/{aid}/coach", headers=h).status_code == 200
    r = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert r.status_code == 201, r.text
    drill = r.json()
    assert drill["id"] != s["id"]
    assert drill["answers"][0]["question"]["id"] == s["answers"][0]["question"]["id"]
    assert drill["answers"][0]["transcript"] is None
    assert drill["context_snapshot"]["essays"] == s["context_snapshot"]["essays"]
    assert drill["context_snapshot"]["drill_targets"][0]["answer_id"] == aid
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]["transcript"]
    assert client.post(f"/practice/sessions/{s['id']}/redrill", headers={"X-User-Id": "outsider"}).status_code == 404


def test_model_fabricated_quotes_fall_back_to_basic_report(client, monkeypatch):
    h, s, _, _, submitted = make_session(client)
    aid = answer(client, h, s)
    monkeypatch.setattr(settings, "openai_api_key", "test-only")
    forged = {
        "summary": "검증되지 않은 결론", "next_action": "다시 연습하세요",
        "criteria": [{"key": key, "label": key, "status": "충분", "reason": "근거",
                      "answer_quote": "사용자가 말하지 않은 내용", "source_quote": "",
                      "source_version_id": None} for key in ["specificity", "relevance", "consistency"]],
        "followup": {"text": "어떻게 측정했나요?", "focus": "specificity", "reason": "근거",
                     "answer_quote": "가짜 인용", "source_quote": "가짜 자소서", "source_version_id": submitted["id"]},
    }
    monkeypatch.setattr(llm, "_chat", lambda *args, **kwargs: json.dumps(forged))
    r = client.post(f"/practice/answers/{aid}/coach", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["coaching_report"]["method"] == "basic"
    assert "가짜" not in json.dumps(r.json(), ensure_ascii=False)


def test_model_valid_evidence_is_kept_and_external_failure_is_recoverable(client, monkeypatch):
    import httpx
    h, s, _, _, submitted = make_session(client)
    text = "제가 캐시를 설계했습니다."
    aid = answer(client, h, s, text)
    raw = {
        "summary": "측정 조건을 더 설명해 보세요.", "next_action": "전후 비교 조건을 정리하세요.",
        "criteria": [{"key": key, "label": key, "status": "보완", "reason": "측정 조건 설명이 부족합니다.",
                      "answer_quote": text, "source_quote": submitted["content"],
                      "source_version_id": submitted["id"]} for key in ["specificity", "relevance", "consistency"]],
        "followup": {"text": "측정 조건은 무엇인가요?", "focus": "specificity", "reason": "비교 기준을 확인합니다.",
                     "answer_quote": text, "source_quote": submitted["content"], "source_version_id": submitted["id"]},
    }
    monkeypatch.setattr(settings, "openai_api_key", "test-only")
    monkeypatch.setattr(llm, "_chat", lambda *args, **kwargs: json.dumps(raw))
    r = client.post(f"/practice/answers/{aid}/coach", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["coaching_report"]["method"] == "ai"
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(llm, "_chat", offline)
    r = client.post(f"/practice/answers/{aid}/coach", headers=h)
    assert r.status_code == 200 and r.json()["coaching_report"]["method"] == "basic"


def test_followup_questions_are_not_recycled_into_the_question_bank(client):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    made = client.post(f"/practice/answers/{aid}/followup", headers=h)
    assert made.status_code == 201, made.text
    child_id = made.json()["answers"][1]["question"]["id"]
    bank = client.get("/practice/questions", headers=h).json()
    assert child_id not in {q["id"] for q in bank}
    later = client.post("/practice/sessions", headers=h, json={"mode": "free", "count": 20}).json()
    assert child_id not in {a["question"]["id"] for a in later["answers"]}


def test_inflight_coaching_cannot_restore_feedback_for_an_old_transcript(client, monkeypatch):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    entered, resume = Event(), Event()
    original = coaching.build_report
    def delayed(*args, **kwargs):
        report = original(*args, **kwargs)
        entered.set()
        assert resume.wait(5)
        return report
    monkeypatch.setattr(coaching, "build_report", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f"/practice/answers/{aid}/coach", headers=h)
        assert entered.wait(5)
        try:
            changed = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "새 답변입니다."})
            assert changed.status_code == 200
        finally:
            resume.set()
        assert pending.result(timeout=5).status_code == 409
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert saved["transcript"] == "새 답변입니다." and saved["coaching_report"] is None


def test_concurrent_followups_keep_a_total_order(client, monkeypatch):
    h, s, _, _, _ = make_session(client)
    qs = [client.post("/practice/questions", headers=h, json={"category": "직무", "text": f"측정 경험 {i}을 설명해 주세요."}).json()["id"] for i in range(3)]
    s = client.post("/practice/sessions", headers=h, json={"mode": "free", "question_ids": qs, "followups_enabled": True}).json()
    ids = [a["id"] for a in s["answers"][:2]]
    for aid in ids:
        client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "제가 개선했습니다."})
    barrier = Barrier(2)
    original = coaching.build_report
    def together(*args, **kwargs):
        report = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return report
    monkeypatch.setattr(coaching, "build_report", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda aid: client.post(f"/practice/answers/{aid}/followup", headers=h), ids))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"]
    assert [a["order_no"] for a in saved] == [1, 2, 3, 4, 5]
    assert saved[1]["parent_answer_id"] == ids[0]
    assert saved[3]["parent_answer_id"] == ids[1]


def test_followup_stays_private_after_its_original_session_is_deleted(client):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    made = client.post(f"/practice/answers/{aid}/followup", headers=h).json()
    child_qid = made["answers"][1]["question"]["id"]
    assert client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code == 204
    bank = client.get("/practice/questions", headers=h).json()
    assert child_qid not in {q["id"] for q in bank}


def test_submitted_preference_falls_back_explicitly_when_no_submission_exists(client):
    h = {"X-User-Id": f"no-submitted-{uuid.uuid4()}"}
    app = client.post("/track/applications", headers=h, json={"company": "A", "position": "개발"}).json()
    client.post(f"/track/applications/{app['id']}/essays", headers=h,
                json={"question_text": "경험", "content": "작성 중인 자소서"})
    s = client.post("/practice/sessions", headers=h, json={"mode": "free", "application_id": app["id"], "count": 1}).json()
    assert s["context_snapshot"]["essay_basis"] == "submitted"
    assert s["context_snapshot"]["essays"][0]["selection"] == "latest"


def test_new_tables_can_be_added_to_an_existing_sqlite_database():
    from sqlalchemy import create_engine, inspect, text
    from app.db import Base
    engine = create_engine("sqlite://")
    original_tables = [table for name, table in Base.metadata.tables.items()
                       if name not in {"practice_contexts", "answer_coaching", "practice_private_questions"}]
    Base.metadata.create_all(engine, tables=original_tables)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO questions (id,category,text,source,created_at) VALUES ('legacy','인성','기존 질문','bank',CURRENT_TIMESTAMP)"))
    Base.metadata.create_all(engine)
    assert {"practice_contexts", "answer_coaching"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT text FROM questions WHERE id='legacy'")).scalar_one() == "기존 질문"


def test_concurrent_duplicate_followup_returns_one_child(client, monkeypatch):
    h, s, _, _, _ = make_session(client)
    aid = answer(client, h, s)
    barrier = Barrier(2)
    original = coaching.build_report
    def together(*args, **kwargs):
        report = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return report
    monkeypatch.setattr(coaching, "build_report", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"/practice/answers/{aid}/followup", headers=h), range(2)))
    assert all(r.status_code == 201 for r in results)
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert len(saved["answers"]) == 2


def test_selected_generated_questions_cannot_silently_use_another_applications_context(client):
    h, _, app, _, _ = make_session(client)
    generated = client.post("/practice/questions/generate", headers=h, json={"application_id": app["id"], "count": 1}).json()
    other = client.post("/track/applications", headers=h, json={"company": "다른회사", "position": "기획"}).json()
    r = client.post("/practice/sessions", headers=h, json={"mode": "free", "application_id": other["id"], "question_ids": [generated[0]["id"]]})
    assert r.status_code == 422
