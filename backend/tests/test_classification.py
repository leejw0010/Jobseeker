import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest

def owner():
    return {'X-User-Id': f'classify-{uuid.uuid4()}'}

def question(client, h, **kw):
    r = client.post('/practice/questions', headers=h, json={'category': '직무', 'text': '문제를 해결한 경험을 설명하세요.', 'question_type': 'behavioral', 'competency_keys': ['problem_solving', 'communication'], **kw})
    assert r.status_code == 201, r.text
    return r.json()

def session(client, h, q, **kw):
    r = client.post('/practice/sessions', headers=h, json={'mode': 'free', 'question_ids': [q['id']], **kw})
    assert r.status_code == 201, r.text
    return r.json()

def test_taxonomy(client):
    r = client.get('/practice/taxonomy')
    assert r.status_code == 200
    b = r.json()
    assert b['enabled'] and b['taxonomy_version'] == 'interview-v1' and (b['max_competencies'] == 3)
    assert len(b['question_types']) == 6 and len(b['competencies']) == 7
    assert all((x['label'] and x['definition'] for k in ('question_types', 'competencies') for x in b[k]))

def test_legacy_debrief_is_preserved_as_unverified_history(client):
    from app.db import SessionLocal
    from app.models import PracticeSession
    h = owner()
    s = session(client, h, question(client, h))
    with SessionLocal() as db:
        stored = db.get(PracticeSession, s['id'])
        stored.debrief = {'lesson': '이전 버전에서 만든 교훈', 'next_action': '이전 행동', 'moments': []}
        stored.debrief_status = 'done'
        db.commit()
    response = client.get(f'/practice/sessions/{s["id"]}', headers=h).json()
    assert response['debrief']['lesson'] == '이전 버전에서 만든 교훈'
    assert response['debrief']['input_status'] == 'legacy_unverified'
    assert response['debrief_status'] == 'done'

def test_schema_rollback_preserves_core_coaching_without_optional_evidence():
    code = '''from app import coaching
from app.models import PracticeAnswer, AnswerCoaching, transcript_hash
from app.taxonomy import classification_hash
text = "제가 오류를 분석하고 수정했습니다."
a = PracticeAnswer(transcript=text)
a.coaching = AnswerCoaching(report={**coaching._basic(text, {}), "transcript_sha256": transcript_hash(text), "question_classification_sha256": classification_hash({"competencies": ["problem_solving"]}), "competency_evidence": {"observations": []}})
assert a.coaching_report is not None
assert len(a.coaching_report["criteria"]) == 3
assert a.coaching_report.get("competency_evidence") is None
'''
    r = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PRACTICE_INSIGHTS_ENABLED': 'false'}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

@pytest.mark.parametrize('extra', [{'question_type': 'bad'}, {'competency_keys': ['bad']}, {'competency_keys': ['communication', 'communication']}, {'competency_keys': ['communication', 'problem_solving', 'leadership', 'collaboration']}])
def test_invalid_classification(client, extra):
    assert client.post('/practice/questions', headers=owner(), json={'category': '인성', 'text': '질문입니다', **extra}).status_code == 422

def test_filters_owner_and_snapshot(client):
    h, other = (owner(), owner())
    q = question(client, h)
    s = session(client, h, q)
    snap = s['answers'][0]['question_classification']
    assert snap['question_type'] == 'behavioral'
    assert snap['competencies'][0]['definition'] and snap['question_type_label'] and snap['captured_at']
    edit = {'question_type': 'situational', 'competency_keys': ['leadership']}
    path = f'/practice/questions/{q['id']}/classification'
    assert client.put(path, headers=other, json=edit).status_code == 404
    bank = next((x for x in client.get('/practice/questions', headers=h).json() if x['source'] == 'bank'))
    assert client.put(f'/practice/questions/{bank['id']}/classification', headers=h, json=edit).status_code == 404
    assert client.put(path, headers=h, json=edit).status_code == 200
    assert client.get(f'/practice/sessions/{s['id']}', headers=h).json()['answers'][0]['question_classification'] == snap
    for match, want in [('any', True), ('all', False)]:
        got = client.get('/practice/questions', headers=h, params=[('question_type', 'situational'), ('competency_key', 'communication'), ('competency_key', 'leadership'), ('competency_match', match)]).json()
        assert (q['id'] in [x['id'] for x in got]) is want
    assert client.get('/practice/questions', params={'competency_key': 'bad'}).status_code == 422
    assert client.get('/practice/questions', params={'competency_match': 'bad'}).status_code == 422
    assert session(client, h, q, question_types=['knowledge'])['answers'][0]['question']['id'] == q['id']
    summary = next((x for x in client.get('/practice/sessions', headers=h).json() if x['id'] == s['id']))
    assert summary['competency_keys'] == ['communication', 'problem_solving'] and summary['classification_missing_count'] == 0

def test_followup_redrill_and_null(client):
    h = owner()
    q = question(client, h)
    s = session(client, h, q, followups_enabled=True)
    a = s['answers'][0]
    client.patch(f'/practice/answers/{a['id']}', headers=h, json={'transcript': '제가 문제를 찾아 해결했습니다.', 'self_rating': 1})
    child = client.post(f'/practice/answers/{a['id']}/followup', headers=h).json()['answers'][1]
    assert child['question_classification']['question_role'] == 'followup'
    assert child['question_classification']['competencies'] == a['question_classification']['competencies']
    client.put(f'/practice/questions/{q['id']}/classification', headers=h, json={'question_type': 'knowledge', 'competency_keys': ['technical_expertise']})
    drill = client.post(f'/practice/sessions/{s['id']}/redrill', headers=h).json()['answers'][0]['question_classification']
    assert drill['competencies'] == a['question_classification']['competencies'] and drill['question_role'] == 'primary'
    legacy = client.post('/practice/questions', headers=h, json={'category': '직무', 'text': '예전 질문입니다.'}).json()
    ls = session(client, h, legacy)
    la = ls['answers'][0]
    assert la['question_classification'] is None
    client.patch(f'/practice/answers/{la['id']}', headers=h, json={'self_rating': 1})
    client.put(f'/practice/questions/{legacy['id']}/classification', headers=h, json={'question_type': 'knowledge', 'competency_keys': ['technical_expertise']})
    assert client.post(f'/practice/sessions/{ls['id']}/redrill', headers=h).json()['answers'][0]['question_classification'] is None

def test_concurrent_atomic_classification(client):
    h = owner()
    q = question(client, h)
    values = [{'question_type': 'knowledge', 'competency_keys': ['technical_expertise']}, {'question_type': 'situational', 'competency_keys': ['leadership']}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda v: client.put(f'/practice/questions/{q['id']}/classification', headers=h, json=v), values))
    assert all((r.status_code == 200 for r in results))
    got = next((x for x in client.get('/practice/questions', headers=h).json() if x['id'] == q['id']))
    assert {'question_type': got['question_type'], 'competency_keys': got['competency_keys']} in values

def test_disabled_schema_omits_new_columns():
    code = 'from app.models import Question, PracticeAnswer; from sqlalchemy import select; from sqlalchemy.dialects import postgresql; sql=str(select(Question,PracticeAnswer).compile(dialect=postgresql.dialect())); assert "question_type" not in sql and "question_classification" not in sql and "recording_transcript_sha256" not in sql; assert "question_competencies" not in Question.metadata.tables'
    r = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PRACTICE_INSIGHTS_ENABLED': 'false'}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_bank_exact_backfill_and_generation(client, isolated_db):
    from app.models import Question
    from app.seed import BANK, seed_question_bank
    from sqlalchemy import select
    with isolated_db() as db:
        bank = list(db.scalars(select(Question).where(Question.user_id.is_(None))))
        assert len(bank) == len(BANK) == 30
        assert all((q.question_type and q.taxonomy_version == 'interview-v1' and (q.tagging_source == 'curated') for q in bank))
        changed = bank[0]
        changed.text += ' 수정됨'
        changed.question_type = None
        changed.taxonomy_version = None
        changed.tagging_source = None
        changed.competency_tags = []
        clone = Question(user_id=str(uuid.uuid4()), category=BANK[1][0], job_category=BANK[1][1], text=BANK[1][2], source='bank')
        db.add(clone)
        db.commit()
        seed_question_bank(db)
        assert changed.question_type is None and clone.question_type is None
    h = owner()
    r = client.post('/practice/questions/generate', headers=h, json={'company': '테스트', 'count': 3, 'question_type': 'situational', 'competency_keys': ['problem_solving']})
    assert r.status_code == 201
    assert [q['question_type'] for q in r.json()] == ['motivation', 'self_description', 'behavioral']
    assert all((q['tagging_source'] == 'rule' for q in r.json()))
    r = client.post('/practice/questions/generate', headers=h, json={'company': '다른회사', 'position': '다른직무', 'count': 5})
    assert r.status_code == 201 and all((q['question_type'] and q['tagging_source'] == 'rule' for q in r.json()))

def test_enabled_schema_validation_readonly(tmp_path):
    from app.db import make_engine, validate_insights_schema, upgrade_sqlite
    from sqlalchemy import event
    engine = make_engine(f'sqlite:///{tmp_path / 'schema.db'}')
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt))
    with pytest.raises(RuntimeError, match='20261104_practice_insights.sql'):
        validate_insights_schema(engine)
    assert not any((x.lstrip().upper().startswith(('CREATE', 'ALTER', 'INSERT', 'UPDATE', 'DELETE')) for x in statements))
    upgrade_sqlite(engine)
    validate_insights_schema(engine)
    assert upgrade_sqlite(engine) == []

def test_evidence_extension_invalid_isolated_and_server_owned(monkeypatch):
    import json
    from app import coaching, llm
    from app.config import settings
    from app.taxonomy import capture, classification_hash
    from app.models import Question
    from app.taxonomy import assign
    q = Question(category='직무', text='질문')
    assign(q, 'behavioral', ['problem_solving'])
    snap = capture(q)
    text = '제가 오류를 분석하고 캐시를 수정했습니다.'
    base = coaching._basic(text, {})
    monkeypatch.setattr(llm, 'available', lambda: True)
    monkeypatch.setattr(settings, 'practice_competency_evidence_enabled', True)
    calls = []

    def reply(*a, **kw):
        calls.append(a)
        return json.dumps({**base, 'competency_evidence': {'observations': [{'competency_key': 'problem_solving', 'basis': 'past_action', 'quote': '제가 오류를 분석하고', 'reason': '원인 분석을 설명함'}], 'transcript_sha256': 'forged'}})
    monkeypatch.setattr(llm, '_chat', reply)
    report = coaching.build_report('질문', text, {}, [], classification=snap)
    ev = report['competency_evidence']
    assert ev['transcript_sha256'] != 'forged'
    assert ev['question_classification_sha256'] == classification_hash(snap) and ev['status'] == 'analyzed'
    assert ev['observations'][0]['quote'] in text and len(calls) == 1
    for invalid in [None, [], {'observations': [{'competency_key': 'unknown_key', 'basis': 'past_action', 'quote': '제가 오류를 분석하고', 'reason': '설명'}]}, {'observations': [{'competency_key': 'problem_solving', 'basis': 'past_action', 'quote': '없는 인용문입니다', 'reason': '설명'}]}]:
        monkeypatch.setattr(llm, '_chat', lambda *a, **k: json.dumps({**base, 'competency_evidence': invalid}))
        report = coaching.build_report('질문', text, {}, [], classification=snap)
        assert report['method'] == 'ai' and report.get('competency_evidence') is None and ('fallback_reason' not in report)
    monkeypatch.setattr(settings, 'practice_competency_evidence_enabled', False)
    monkeypatch.setattr(llm, '_chat', reply)
    assert coaching.build_report('질문', text, {}, [], classification=snap).get('competency_evidence') is None

def test_nonrequired_dictionary_competency_evidence_is_valid_but_not_unknown_keys():
    from app import coaching, taxonomy
    from app.models import Question
    q = Question(category='직무', text='문제 해결 경험')
    taxonomy.assign(q, 'behavioral', ['problem_solving'])
    snap = taxonomy.capture(q)
    transcript = '제가 방향을 제시하고 업무 책임을 나눴습니다.'
    raw = {'observations':[{'competency_key':'leadership', 'basis':'past_action', 'quote':'제가 방향을 제시하고', 'reason':'방향 설정을 서술함'}]}
    evidence = coaching._evidence(raw, transcript, snap)
    assert evidence is not None
    assert taxonomy.current_evidence(evidence, transcript, snap)['observations'][0]['competency_key'] == 'leadership'
    raw['observations'][0]['competency_key'] = 'unknown_key'
    assert coaching._evidence(raw, transcript, snap) is None

@pytest.mark.parametrize('field,value', [('transcript', '새로 작성한 답변입니다.'), ('self_rating', 2), ('reflection_note', '다음에는 검증 과정을 말하겠습니다.')])
def test_debrief_hidden_after_any_input_edit(client, monkeypatch, field, value):
    from app import llm
    from app.config import settings
    monkeypatch.setattr(settings, 'openai_api_key', 'test-placeholder')
    monkeypatch.setattr(llm, 'debrief_summary', lambda *a, **k: {'lesson': '기존 답변의 교훈', 'next_action': '기존 행동', 'moments': []})
    monkeypatch.setattr(llm, '_chat', lambda *a, **k: 'invalid')
    h = owner()
    s = session(client, h, question(client, h))
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    client.post(f'/practice/sessions/{s['id']}/debrief', headers=h)
    before = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    assert before['debrief'] and before['debrief']['input_sha256']
    client.patch(f'/practice/answers/{aid}', headers=h, json={field: value})
    after = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    assert after['debrief'] is None and after['debrief_status'] != 'done'

def test_debrief_edit_during_summary_discards_entire_narrative(client, monkeypatch):
    from app import llm
    from app.config import settings
    from threading import Event
    entered, resume = (Event(), Event())
    monkeypatch.setattr(settings, 'openai_api_key', 'test-placeholder')
    monkeypatch.setattr(llm, '_chat', lambda *a, **k: 'invalid')

    def summary(*a, **k):
        entered.set()
        assert resume.wait(5)
        return {'lesson': '예전 해석', 'next_action': '예전 행동', 'moments': []}
    monkeypatch.setattr(llm, 'debrief_summary', summary)
    h = owner()
    s = session(client, h, question(client, h))
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(client.post, f'/practice/sessions/{s['id']}/debrief', headers=h)
        assert entered.wait(5)
        try:
            client.patch(f'/practice/answers/{aid}', headers=h, json={'reflection_note': '수정한 메모'})
        finally:
            resume.set()
        assert job.result(timeout=10).status_code == 200
    got = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    assert got['debrief'] is None and got['debrief_status'] != 'done'

def test_tag_only_and_explicit_empty_bundle_are_distinct_from_legacy_null(client):
    h = owner()
    for keys in [['communication'], []]:
        q = question(client, h, question_type=None, competency_keys=keys)
        assert q['taxonomy_version'] == 'interview-v1' and q['tagging_source'] == 'manual'
        snap = session(client, h, q)['answers'][0]['question_classification']
        assert snap is not None and snap['question_type'] is None
        assert snap['question_type_label'] is None and snap['question_type_definition'] is None
        assert snap['competency_keys'] == keys
    legacy = client.post('/practice/questions', headers=h, json={'category': '직무', 'text': '기존 무분류 질문'}).json()
    assert session(client, h, legacy)['answers'][0]['question_classification'] is None

def test_optional_evidence_is_validated_on_read_without_hiding_core(client):
    from app.db import SessionLocal
    from app.models import PracticeAnswer
    h = owner()
    s = session(client, h, question(client, h))
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    assert client.post(f'/practice/answers/{aid}/coach', headers=h).status_code == 200
    for invalid in [{'observations': None}, {'observations': 'bad'}, {'transcript_sha256': 'bad', 'question_classification_sha256': 'bad', 'observations': []}]:
        with SessionLocal() as db:
            a = db.get(PracticeAnswer, aid)
            a.coaching.report = {**a.coaching.report, 'competency_evidence': invalid}
            db.commit()
        r = client.get(f'/practice/sessions/{s['id']}', headers=h)
        assert r.status_code == 200, r.text
        assert r.json()['answers'][0]['coaching_report']['competency_evidence'] is None

def test_feature_off_legacy_insert_select_returning(tmp_path):
    code = 'from app.models import Question, PracticeAnswer\nfrom app.db import Base, make_engine\nfrom sqlalchemy import select, insert\nfrom sqlalchemy.dialects import postgresql\nfrom sqlalchemy.orm import Session\nengine=make_engine("sqlite:///:memory:")\nBase.metadata.create_all(engine)\nwith Session(engine) as db:\n q=Question(category="인성",text="legacy",source="custom"); db.add(q); db.commit()\n assert db.scalars(select(Question)).one().text=="legacy"\nfor cls in (Question,PracticeAnswer):\n for stmt in (select(cls),insert(cls).returning(cls)):\n  sql=str(stmt.compile(dialect=postgresql.dialect()))\n  assert not any(x in sql for x in ("question_type","taxonomy_version","tagging_source","question_classification","question_competencies","recording_transcript_sha256")),sql\n'
    r = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PRACTICE_INSIGHTS_ENABLED': 'false'}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_malformed_evidence_with_valid_fingerprints_does_not_break_read(client):
    from app.db import SessionLocal
    from app.models import PracticeAnswer, transcript_hash
    from app.taxonomy import classification_hash
    h = owner()
    s = session(client, h, question(client, h))
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    client.post(f'/practice/answers/{aid}/coach', headers=h)
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, aid)
        a.coaching.report = {**a.coaching.report, 'competency_evidence': {'transcript_sha256': transcript_hash(a.transcript), 'question_classification_sha256': classification_hash(a.question_classification), 'observations': None}}
        db.commit()
    r = client.get(f'/practice/sessions/{s['id']}', headers=h)
    assert r.status_code == 200
    assert r.json()['answers'][0]['coaching_report']['competency_evidence'] is None

def test_generation_preferences_are_goals_and_invalid_metadata_stays_unclassified(client, monkeypatch):
    from app import llm
    h = owner()
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return [{'category': '직무', 'text': '유효한 질문 문장 A', 'question_type': 'bad', 'competency_keys': ['communication']}, {'category': '직무', 'text': '유효한 질문 문장 B'}, {'category': '직무', 'text': '유효한 질문 문장 C', 'question_type': 'knowledge', 'competency_keys': ['analytical_thinking'], 'tagging_source': 'manual'}]
    monkeypatch.setattr(llm, 'generate_questions', generate)
    r = client.post('/practice/questions/generate', headers=h, json={'company': '회사', 'competency_keys': ['problem_solving']})
    assert r.status_code == 201, r.text
    assert calls[0]['classification_preferences']['competency_keys'] == ['problem_solving']
    assert len(r.json()) == 3
    assert all((q['taxonomy_version'] is None and (not q['competency_keys']) for q in r.json()[:2]))
    assert r.json()[2]['competency_keys'] == ['analytical_thinking']
    assert r.json()[2]['tagging_source'] in ('ai', 'rule')

def test_automatic_selection_rechecks_classification_after_lock(client, monkeypatch):
    from app.routers import practice
    h = owner()
    q = question(client, h)
    original = practice.random.shuffle
    changed = False

    def shuffle(pool):
        nonlocal changed
        if not changed:
            changed = True
            response = client.put(f'/practice/questions/{q['id']}/classification', headers=h, json={'question_type': 'knowledge', 'competency_keys': ['technical_expertise']})
            assert response.status_code == 200
        original(pool)
    monkeypatch.setattr(practice.random, 'shuffle', shuffle)
    before = client.get('/practice/sessions', headers=h).json()
    r = client.post('/practice/sessions', headers=h, json={'mode': 'free', 'count': 1, 'question_types': ['behavioral'], 'competency_keys': ['problem_solving'], 'competency_match': 'all'})
    assert r.status_code == 409, r.text
    assert client.get('/practice/sessions', headers=h).json() == before

def test_session_list_filters_frozen_tags_not_current_question(client):
    h = owner()
    q = question(client, h)
    old = session(client, h, q)
    client.put(f'/practice/questions/{q['id']}/classification', headers=h, json={'question_type': 'knowledge', 'competency_keys': ['technical_expertise']})
    new = session(client, h, q)
    got = client.get('/practice/sessions', headers=h, params={'competency_key': 'problem_solving'}).json()
    assert [x['id'] for x in got] == [old['id']]
    got = client.get('/practice/sessions', headers=h, params={'competency_key': 'technical_expertise'}).json()
    assert [x['id'] for x in got] == [new['id']]
    assert client.get('/practice/sessions', headers=h, params={'competency_key': 'invalid'}).status_code == 422

@pytest.mark.parametrize('change', ['question', 'order', 'report', 'snapshot', 'context', 'recording'])
def test_debrief_fingerprint_covers_all_interpretation_inputs(client, monkeypatch, change):
    from app import llm
    from app.config import settings
    from app.db import SessionLocal
    from app.models import PracticeAnswer
    from datetime import datetime, timezone
    monkeypatch.setattr(settings, 'openai_api_key', 'test-placeholder')
    monkeypatch.setattr(llm, '_chat', lambda *a, **k: 'invalid')
    monkeypatch.setattr(llm, 'debrief_summary', lambda *a, **k: {'lesson': '검증된 이전 교훈', 'next_action': '이전 행동', 'moments': []})
    h = owner()
    s = session(client, h, question(client, h))
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    client.post(f'/practice/sessions/{s['id']}/debrief', headers=h)
    assert client.get(f'/practice/sessions/{s['id']}', headers=h).json()['debrief']
    with SessionLocal() as db:
        a = db.get(PracticeAnswer, aid)
        if change == 'question':
            a.question.text = '다른 질문 문장'
        elif change == 'order':
            a.order_no = 9
        elif change == 'report':
            a.coaching.report = {**a.coaching.report, 'summary': '수정된 해석'}
        elif change == 'snapshot':
            a.question_classification = {**a.question_classification, 'question_type_definition': '새 정의'}
        elif change == 'context':
            a.session.context.snapshot = {**a.session.context.snapshot, 'job_description': '새 공고'}
        else:
            a.recorded_at = datetime.now(timezone.utc)
        db.commit()
    result = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    assert result['debrief'] is None and result['debrief_status'] == 'none'

def test_question_retagging_does_not_rewrite_past_debrief_inputs(client, monkeypatch):
    from app import llm
    from app.config import settings
    monkeypatch.setattr(settings, 'openai_api_key', 'test-placeholder')
    monkeypatch.setattr(llm, '_chat', lambda *a, **k: 'invalid')
    monkeypatch.setattr(llm, 'debrief_summary', lambda *a, **k: {'lesson': '고정된 분류의 교훈', 'next_action': '다음 행동', 'moments': []})
    h = owner()
    q = question(client, h)
    s = session(client, h, q)
    aid = s['answers'][0]['id']
    client.patch(f'/practice/answers/{aid}', headers=h, json={'transcript': '제가 오류를 분석했습니다.'})
    client.post(f'/practice/sessions/{s['id']}/debrief', headers=h)
    before = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    client.put(f'/practice/questions/{q['id']}/classification', headers=h, json={'question_type': 'knowledge', 'competency_keys': ['technical_expertise']})
    after = client.get(f'/practice/sessions/{s['id']}', headers=h).json()
    assert before['debrief'] == after['debrief'] and before['answers'][0]['question_classification'] == after['answers'][0]['question_classification']

def test_classification_service_enforces_bounds_and_server_sources():
    from app.models import Question
    from app.taxonomy import assign
    q = Question(category='인성', text='분류 질문')
    with pytest.raises(ValueError):
        assign(q, 'behavioral', ['communication', 'problem_solving', 'leadership', 'collaboration'])
    with pytest.raises(ValueError):
        assign(q, 'behavioral', [], source='forged')

def test_schema_flags_default_off_and_enabled_pg_startup_checks_readonly(tmp_path, monkeypatch):
    from app.config import Settings, settings
    from app import db
    from sqlalchemy import event
    assert Settings({}).practice_insights_enabled is False
    assert Settings({}).practice_competency_evidence_enabled is False
    engine = db.make_engine(f'sqlite:///{tmp_path / 'unmigrated.db'}')
    seen = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, stmt, params, ctx, many: seen.append(stmt))
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(db, '_is_sqlite', False)
    monkeypatch.setattr(settings, 'practice_insights_enabled', True)
    with pytest.raises(RuntimeError, match='20261105_track_integrity.sql'):
        db.init_db()
    assert not any(stmt.lstrip().upper().startswith(('CREATE', 'ALTER', 'INSERT', 'UPDATE', 'DELETE')) for stmt in seen)
    # Track is a prerequisite of this release; Stage 2 can still be independently disabled.
    for name in ('application_states', 'essay_submissions'):
        db.Base.metadata.tables[name].create(engine)
    seen.clear()
    with pytest.raises(RuntimeError, match='20261104_practice_insights.sql'):
        db.init_db()
    assert not any((stmt.lstrip().upper().startswith(('CREATE', 'ALTER', 'INSERT', 'UPDATE', 'DELETE')) for stmt in seen))
    monkeypatch.setattr(settings, 'practice_insights_enabled', False)
    seen.clear()
    db.init_db()
    assert not any(stmt.lstrip().upper().startswith(('CREATE', 'ALTER', 'INSERT', 'UPDATE', 'DELETE')) for stmt in seen)

def test_bank_backfill_uses_full_tuple_and_preserves_manual_bundles(client, isolated_db):
    from app.models import Question
    from app.seed import BANK, seed_question_bank
    from app.taxonomy import assign
    from sqlalchemy import select
    with isolated_db() as db:
        c, j, t = BANK[14]
        clones = [Question(category=c, job_category='다른직무', text=t, source='bank'), Question(category='인성', job_category=j, text=t, source='bank'), Question(category=c, job_category=j, text=t, source='custom'), Question(category=c, job_category=j, text=t + '수정', source='bank')]
        db.add_all(clones)
        manual = db.scalar(select(Question).where(Question.text == BANK[0][2]))
        assign(manual, None, [], source='manual')
        db.commit()
        seed_question_bank(db)
        assert all((q.taxonomy_version is None for q in clones))
        assert manual.tagging_source == 'manual' and manual.question_type is None and (manual.competency_keys == [])
