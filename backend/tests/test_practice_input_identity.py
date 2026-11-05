"""Core coaching depends on the complete frozen conversation, independently of tags."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import uuid

from app import coaching


def conversation(client):
    h = {"X-User-Id": f"history-{uuid.uuid4()}"}
    qs = [client.post('/practice/questions', headers=h, json={"category": "직무", "text": f"경험 질문 {i}"}).json()['id'] for i in range(2)]
    s = client.post('/practice/sessions', headers=h, json={"mode": "free", "question_ids": qs, "followups_enabled": True}).json()
    for a in s['answers']:
        assert client.patch(f"/practice/answers/{a['id']}", headers=h, json={"transcript": f"상황을 분석하고 방법 {a['order_no']}을 선택했습니다."}).status_code == 200
    return h, s


def test_previous_answer_edit_invalidates_later_core_coaching(client):
    h, s = conversation(client)
    earlier, later = s['answers']
    response = client.post(f"/practice/answers/{later['id']}/coach", headers=h)
    assert response.status_code == 200, response.text
    assert response.json()['coaching_report']
    client.patch(f"/practice/answers/{earlier['id']}", headers=h, json={"transcript": "앞선 설명을 정정합니다."})
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert saved['answers'][1]['coaching_report'] is None


def test_inflight_previous_answer_edit_discards_later_report(client, monkeypatch):
    h, s = conversation(client)
    earlier, later = s['answers']
    entered, resume = Event(), Event()
    build = coaching.build_report
    def delayed(*args, **kwargs):
        report = build(*args, **kwargs)
        entered.set()
        assert resume.wait(5)
        return report
    monkeypatch.setattr(coaching, 'build_report', delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f"/practice/answers/{later['id']}/coach", headers=h)
        assert entered.wait(5)
        try:
            edit = client.patch(f"/practice/answers/{earlier['id']}", headers=h, json={"transcript": "앞선 설명을 정정합니다."})
            assert edit.status_code == 200, edit.text
        finally:
            resume.set()
        assert pending.result(timeout=5).status_code == 409
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert saved['answers'][1]['coaching_report'] is None


def test_core_input_fingerprint_covers_order_context_question_and_rubric(monkeypatch):
    args = ['질문', '답변', {'essays': [], 'company': 'A'}, [{'question': '이전', 'answer': '설명'}]]
    fingerprint = getattr(coaching, 'input_fingerprint', None)
    assert callable(fingerprint), 'core input fingerprint is required'
    before = fingerprint(*args)
    assert before == fingerprint(*args)
    assert before != fingerprint('다른 질문', *args[1:])
    assert before != fingerprint(args[0], '수정 답변', *args[2:])
    assert before != fingerprint(*args[:2], {'essays': [], 'company': 'B'}, args[3])
    assert before != fingerprint(*args[:3], [{'question': '새 질문', 'answer': None}, *args[3]])
    monkeypatch.setattr(coaching, 'RUBRIC_VERSION', 'next-rubric')
    assert before != fingerprint(*args)


def test_basic_role_guidance_does_not_grade_by_personal_pronouns():
    plain = coaching._basic('장애 로그를 분류하고 배포 점검표를 작성했습니다.', {})
    pronoun = coaching._basic('제가 장애 로그를 분류하고 배포 점검표를 작성했습니다.', {})
    assert plain['next_action'] == pronoun['next_action']
    assert [c['status'] for c in plain['criteria']] == [c['status'] for c in pronoun['criteria']]


def test_legacy_core_remains_readable_but_is_not_a_current_redrill_reason(client):
    from app.db import SessionLocal
    from app.models import PracticeAnswer
    h, s = conversation(client)
    aid = s['answers'][0]['id']
    assert client.post(f'/practice/answers/{aid}/coach', headers=h).status_code == 200
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, aid)
        report = dict(a.coaching.report)
        report.pop('input_sha256')
        report['criteria'][0]['status'] = '보완'
        a.coaching.report = report
        db.commit()
    saved = client.get(f"/practice/sessions/{s['id']}", headers=h).json()
    assert saved['answers'][0]['coaching_report']['input_status'] == 'legacy_unverified'
    assert saved['redrill'] == []


def test_rating_redrill_does_not_reuse_legacy_next_action(client):
    from app.db import SessionLocal
    from app.models import PracticeAnswer
    h, s = conversation(client)
    aid = s['answers'][0]['id']
    client.post(f'/practice/answers/{aid}/coach', headers=h)
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, aid)
        report = dict(a.coaching.report)
        report.pop('input_sha256')
        report['next_action'] = '과거 코칭 전용 행동'
        a.coaching.report = report
        a.self_rating = 1
        db.commit()
    drill = client.post(f"/practice/sessions/{s['id']}/redrill", headers=h)
    assert drill.status_code == 201, drill.text
    assert drill.json()['context_snapshot']['drill_targets'][0]['next_action'] != '과거 코칭 전용 행동'


def test_twelve_synthetic_cases_keep_verbatim_evidence_and_core_identity():
    import json
    from pathlib import Path
    cases = json.loads((Path(__file__).parents[1] / 'evals/coaching/cases.json').read_text())['cases']
    assert len(cases) == 12
    assert {case['question_type'] for case in cases} == {'self_description', 'motivation', 'behavioral', 'situational', 'project_deep_dive', 'knowledge'}
    for case in cases:
        assert case['synthetic'] and case['human_review_status'] == 'not_evaluated'
        report = coaching.build_report(case['question'], case['answer'], case['context'], case['history'])
        assert report['method'] == 'basic'
        assert report['input_sha256'] == coaching.input_fingerprint(case['question'], case['answer'], case['context'], case['history'])
        assert report['input_status'] == 'current'
        for entry in [*report['criteria'], report['followup']]:
            assert not entry['answer_quote'] or entry['answer_quote'] in case['answer']
            assert entry['source_quote'] == ''


def test_unanswered_history_is_fingerprinted_without_expanding_model_payload(client, monkeypatch):
    h, s = conversation(client)
    earlier, later = s['answers']
    client.patch(f"/practice/answers/{earlier['id']}", headers=h, json={'transcript': None})
    history_sent = []
    original = coaching.build_report
    def capture(question, transcript, context, history, **kwargs):
        history_sent.extend(history)
        return original(question, transcript, context, history, **kwargs)
    monkeypatch.setattr(coaching, 'build_report', capture)
    response = client.post(f"/practice/answers/{later['id']}/coach", headers=h)
    assert response.status_code == 200, response.text
    assert history_sent == []
    assert response.json()['coaching_report']['input_status'] == 'current'
