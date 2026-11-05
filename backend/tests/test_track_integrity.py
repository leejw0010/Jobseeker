"""Track history is append-only; current state and statistics have one meaning."""
import uuid


def owner():
    return {"X-User-Id": str(uuid.uuid4())}


def create(client, h, **kw):
    r = client.post('/track/applications', headers=h, json={"company": "검증 회사", "position": "개발", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def event(client, h, app, result, day, stage='서류'):
    r = client.post(f'/track/applications/{app}/events', headers=h,
                    json={"stage": stage, "result": result, "event_date": day})
    assert r.status_code == 201, r.text
    return r.json()


def test_delete_event_recomputes_state_and_late_history_does_not_replace_current(client):
    h = owner(); a = create(client, h)
    a = event(client, h, a['id'], '불합격', '2026-11-04', '인적성')
    a = event(client, h, a['id'], '합격', '2026-11-01')
    assert (a['stage'], a['status']) == ('인적성', '불합격')
    failed = next(e for e in a['events'] if e['result'] == '불합격')
    assert client.delete(f"/track/events/{failed['id']}", headers=h).status_code == 204
    a = client.get(f"/track/applications/{a['id']}", headers=h).json()
    assert (a['stage'], a['status']) == ('인적성', '진행중')


def test_manual_override_survives_event_edits_until_explicit_reset(client):
    h = owner(); a = create(client, h)
    a = event(client, h, a['id'], '합격', '2026-11-01')
    a = client.patch(f"/track/applications/{a['id']}", headers=h, json={"status": "보류"}).json()
    e = a['events'][0]
    r = client.patch(f"/track/events/{e['id']}", headers=h, json={"result": "불합격"})
    assert r.status_code == 200, r.text
    assert (r.json()['stage'], r.json()['status'], r.json()['state_source']) == ('인적성', '보류', 'manual')
    r = client.post(f"/track/applications/{a['id']}/state-from-events", headers=h, json={})
    assert r.status_code == 200, r.text
    assert (r.json()['stage'], r.json()['status']) == ('서류', '불합격')


def test_funnel_is_exclusive_and_applied_month_does_not_invent_a_date(client):
    h = owner(); a = create(client, h)
    event(client, h, a['id'], '합격', '2026-11-01')
    event(client, h, a['id'], '불합격', '2026-11-02')
    create(client, h, applied_at='2026-09-12')
    s = client.get('/track/stats', headers=h).json()
    for row in s['funnel']:
        assert row['pending'] >= 0
        assert row['reached'] == row['passed'] + row['failed'] + row['pending']
    assert s['funnel'][0]['pass_rate'] == 0
    assert s['applied_monthly'] == [{"month": "2026-09", "count": 1}]
    assert s['undated_count'] == 1


def test_restore_always_appends_and_selected_submission_freezes_practice(client):
    h = owner(); a = create(client, h)
    item = client.post(f"/track/applications/{a['id']}/essays", headers=h,
                       json={"question_text": "경험", "content": "처음 제출할 내용"}).json()
    v1 = item['versions'][0]
    r = client.post(f"/track/versions/{v1['id']}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert [v['version_no'] for v in r.json()['versions']] == [1, 2]
    client.post(f"/track/essays/{item['id']}/versions", headers=h, json={"content": "새 수정본"})
    r = client.post(f"/track/versions/{v1['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()['submitted_version_id'] == v1['id']
    assert r.json()['submission_confirmation'] == 'confirmed'
    qs = client.get('/practice/questions', headers=h).json()
    session = client.post('/practice/sessions', headers=h, json={"mode": "free", "application_id": a['id'],
                        "question_ids": [qs[0]['id']], "essay_basis": "submitted"})
    assert session.status_code == 201, session.text
    before = session.json()['context_snapshot']
    assert before['essays'][0]['version_id'] == v1['id']
    client.post(f"/track/essays/{item['id']}/versions", headers=h, json={"content": "제출 이후 수정", "is_submitted": True})
    got = client.get(f"/practice/sessions/{session.json()['id']}", headers=h).json()
    assert got['context_snapshot'] == before


def test_legacy_sync_omission_does_not_claim_explicit_confirmation(client):
    h = owner()
    body = {"company": "회사", "position": "직무", "url": "https://example.test/job/1",
            "essays": [{"question_text": "문항", "content": "내용"}]}
    a = client.post('/track/sync', headers=h, json=body).json()
    detail = client.get(f"/track/applications/{a['application_id']}", headers=h).json()
    item = detail['essay_items'][0]
    assert item['versions'][0]['is_submitted'] is True
    assert item['submission_confirmation'] == 'legacy_unverified'
    client.post('/track/sync', headers=h, json={**body, "submitted": True})
    detail = client.get(f"/track/applications/{a['application_id']}", headers=h).json()
    assert detail['essay_items'][0]['submission_confirmation'] == 'confirmed'


def test_classification_tag_order_can_swap_without_partial_bundles(client):
    h = owner()
    r = client.post('/practice/questions', headers=h, json={"category": "직무", "text": "선택 이유는?"})
    assert r.status_code == 201, r.text
    path = f"/practice/questions/{r.json()['id']}/classification"
    keys = ['problem_solving', 'collaboration']
    for ordered in [keys, list(reversed(keys)), keys]:
        r = client.put(path, headers=h, json={"question_type": "behavioral", "competency_keys": ordered})
        assert r.status_code == 200, r.text
        assert r.json()['competency_keys'] == ordered


def test_explicit_submission_is_idempotent_and_all_new_resources_are_owned(client):
    h, other = owner(), owner(); a = create(client, h)
    item = client.post(f"/track/applications/{a['id']}/essays", headers=h,
                       json={"question_text": "제출", "content": "확인한 본문"}).json()
    v = item['versions'][0]
    for _ in range(2):
        r = client.post(f"/track/versions/{v['id']}/submit", headers=h)
        assert r.status_code == 200
        assert len(r.json()['versions']) == 1
        assert r.json()['submission_revision'] == 1
        assert r.json()['versions'][0]['content'] == v['content']
    from app.db import SessionLocal
    from app.models import EssaySubmission
    from sqlalchemy import select
    with SessionLocal() as db:
        records = db.scalars(select(EssaySubmission).where(EssaySubmission.essay_item_id == item['id'])).all()
        assert len(records) == 1 and records[0].sequence == 1
    assert client.post(f"/track/versions/{v['id']}/submit", headers=other).status_code == 404
    ev = event(client, h, a['id'], '대기', '2026-11-01')['events'][0]
    assert client.patch(f"/track/events/{ev['id']}", headers=other, json={"memo":"no"}).status_code == 404
    assert client.post(f"/track/applications/{a['id']}/state-from-events", headers=other, json={}).status_code == 404


def test_legacy_manual_state_requires_baseline_and_is_never_inferred(client):
    h = owner(); a = create(client, h, status='보류')
    from app.db import SessionLocal
    from app.models import ApplicationState
    with SessionLocal() as db:
        db.delete(db.get(ApplicationState, a['id']))
        db.commit()
    a = event(client, h, a['id'], '합격', '2026-11-01')
    assert (a['stage'], a['status'], a['state_source']) == ('서류', '보류', 'legacy')
    a = client.patch(f"/track/applications/{a['id']}", headers=h, json={'status':'보류'}).json()
    assert a['state_source'] == 'manual' and a['state_requires_baseline'] is True
    path = f"/track/applications/{a['id']}/state-from-events"
    assert client.post(path, headers=h, json={}).status_code == 422
    r = client.post(path, headers=h, json={"baseline_stage":"서류", "baseline_status":"진행중"})
    assert r.status_code == 200
    assert (r.json()['stage'],r.json()['status'],r.json()['state_source']) == ('인적성','진행중','events')


def test_duplicate_legacy_tag_positions_refuse_activation_without_deleting_rows(tmp_path):
    import pytest
    from sqlalchemy import text
    from app.db import make_engine, upgrade_sqlite
    engine = make_engine(f'sqlite:///{tmp_path / "legacy.db"}')
    upgrade_sqlite(engine)
    q = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text('DROP INDEX question_competencies_position_uq'))
        c.execute(text("INSERT INTO questions (id,category,text,source,created_at) VALUES (:id,'직무','기존질문','custom',CURRENT_TIMESTAMP)"), {'id':q})
        for key in ['collaboration','problem_solving']:
            c.execute(text('INSERT INTO question_competencies VALUES (:id,:key,0)'), {'id':q,'key':key})
    with pytest.raises(RuntimeError, match='question_competencies_position_uq'):
        upgrade_sqlite(engine)
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM question_competencies')).scalar_one() == 2
    engine.dispose()


def test_version_rows_cannot_be_rewritten_or_erased_except_by_parent_deletion(client):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.db import SessionLocal
    h = owner(); a = create(client, h)
    item = client.post(f"/track/applications/{a['id']}/essays", headers=h,
                       json={"question_text":"보존", "content":"제출 원문"}).json()
    vid = item['versions'][0]['id']
    client.post(f'/track/versions/{vid}/submit', headers=h)
    for sql in ("UPDATE answer_versions SET content='덮어쓰기' WHERE id=:id",
                "UPDATE answer_versions SET is_submitted=0 WHERE id=:id",
                "DELETE FROM answer_versions WHERE id=:id"):
        with SessionLocal() as db, pytest.raises(IntegrityError):
            db.execute(text(sql), {'id':vid}); db.commit()
    assert client.delete(f"/track/applications/{a['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        assert db.execute(text('SELECT count(*) FROM answer_versions WHERE id=:id'), {'id':vid}).scalar_one() == 0
