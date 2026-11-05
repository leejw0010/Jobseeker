"""Real PG16 SQL, signed JWT API ownership, and non-owner PostgREST RLS.

Run separately: cd backend && .venv/bin/python -m pytest -q integration
"""
from concurrent.futures import ThreadPoolExecutor
import time
import uuid

import psycopg
import pytest

from conftest import A, B, ROOT


def uid():
    return str(uuid.uuid4())


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def create_application(client, headers, **extra):
    return ok(client.post("/track/applications", headers=headers,
                          json={"company": "로컬 검증 회사", "position": "개발", **extra}), 201)


def create_question(client, headers):
    return ok(client.post("/practice/questions", headers=headers, json={"category": "직무", "text": "프로젝트 문제 해결 경험은?",
              "question_type": "behavioral", "competency_keys": ["problem_solving", "communication"]}), 201)


def catalog(database):
    with database.connect() as conn:
        columns = conn.execute("""select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns
         where table_schema='public' order by table_name,ordinal_position""").fetchall()
        constraints = conn.execute("""select c.relname,pg_get_constraintdef(k.oid) from pg_constraint k
          join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace
          where n.nspname='public' order by 1,2""").fetchall()
        policies = conn.execute("select tablename,policyname,cmd,qual,with_check from pg_policies where schemaname='public' order by 1,2").fetchall()
    return columns, constraints, policies


def test_fresh_full_sql_and_all_migrations_repeat_without_data_loss(cluster):
    database = cluster.database()
    app, item, version = uid(), uid(), uid()
    with database.connect() as conn:
        conn.execute("insert into applications(id,user_id,company,position) values (%s,%s,'preserved','dev')", (app, A))
        conn.execute("insert into essay_items(id,application_id,question_text) values (%s,%s,'question')", (item, app))
        conn.execute("insert into answer_versions(id,essay_item_id,version_no,content,char_count,is_submitted) values (%s,%s,1,'unchanged',9,true)", (version, item))
    database.migrations()
    before = catalog(database)
    database.migrations()
    assert catalog(database) == before
    with database.connect() as conn:
        assert conn.execute("select content,is_submitted from answer_versions where id=%s", (version,)).fetchone() == ("unchanged", True)
        assert conn.execute("select count(*) from essay_submissions where essay_item_id=%s", (item,)).fetchone()[0] == 0
        assert conn.execute("show fsync").fetchone()[0] == "on"
        assert conn.execute("show synchronous_commit").fetchone()[0] == "on"
        assert conn.execute("show full_page_writes").fetchone()[0] == "on"
        assert conn.execute("show listen_addresses").fetchone()[0] == ""


def test_historical_upgrade_backfills_only_exact_bank_and_keeps_legacy_snapshots_null(cluster):
    database = cluster.database("historical")
    bank, custom, generated, tagged, session, answer = [uid() for _ in range(6)]
    with database.connect() as conn:
        for id_, owner, source, text in [(bank, None, "bank", "스트레스를 받을 때 어떻게 해소하나요?"),
                (custom, A, "custom", "스트레스를 받을 때 어떻게 해소하나요?"),
                (generated, None, "generated", "스트레스를 받을 때 어떻게 해소하나요?")]:
            conn.execute("insert into questions(id,user_id,category,text,source) values (%s,%s,'인성',%s,%s)", (id_, owner, text, source))
        conn.execute("insert into practice_sessions(id,user_id,mode,title) values (%s,%s,'free','legacy')", (session, A))
        conn.execute("insert into practice_answers(id,session_id,question_id,order_no,transcript,audio_path) values (%s,%s,%s,1,'legacy transcript','fixture/no-real-audio')", (answer, session, bank))
    database.migrations()
    with database.connect() as conn:
        assert conn.execute("select question_type,tagging_source from questions where id=%s", (bank,)).fetchone() == ("self_description", "curated")
        assert conn.execute("select competency_key,position from question_competencies where question_id=%s", (bank,)).fetchall() == [("adaptability", 0)]
        assert conn.execute("select count(*) from questions where id in (%s,%s) and question_type is null", (custom, generated)).fetchone()[0] == 2
        assert conn.execute("select transcript,question_classification,recording_transcript_sha256,recorded_at=created_at,audio_expires_at=created_at+interval '30 days' from practice_answers where id=%s", (answer,)).fetchone() == ("legacy transcript", None, None, True, True)
        # Existing manual classification remains unchanged on rerun.
        conn.execute("update questions set question_type='knowledge',tagging_source='manual' where id=%s", (bank,))
    before = catalog(database)
    database.migrations()
    assert catalog(database) == before
    with database.connect() as conn:
        assert conn.execute("select question_type,tagging_source from questions where id=%s", (bank,)).fetchone() == ("knowledge", "manual")
    fresh = cluster.database()
    fresh.migrations()
    # Column order differs naturally after ALTER TABLE; compare semantic metadata.
    assert sorted(catalog(fresh)[0]) == sorted(catalog(database)[0])
    assert catalog(fresh)[1:] == catalog(database)[1:]


def test_enabled_flag_rejects_unmigrated_schema_before_app_startup(cluster):
    database = cluster.database("historical")
    # Track now has an independent mandatory migration gate; satisfy it first.
    database.apply(ROOT / "supabase/migrations/20261105_track_integrity.sql")
    with pytest.raises(RuntimeError, match="20261105_version_immutability.sql"):
        with database.api(insights=False):
            pass
    database.apply(ROOT / "supabase/migrations/20261105_version_immutability.sql")
    with pytest.raises(RuntimeError, match="20261104_practice_insights.sql"):
        with database.api(insights=True):
            pass


def test_postgres_catalog_uuid_jsonb_constraints_rls_and_roles(database):
    with database.connect() as conn:
        assert conn.execute("select count(*) from information_schema.columns where table_schema='public' and (column_name='id' or column_name like '%\\_id' escape '\\') and data_type<>'uuid'").fetchone()[0] == 0
        assert conn.execute("select data_type from information_schema.columns where table_name='practice_answers' and column_name='question_classification'").fetchone()[0] == "jsonb"
        tables = conn.execute("select relname,relrowsecurity from pg_class where relnamespace='public'::regnamespace and relkind='r'").fetchall()
        assert tables and all(enabled for _, enabled in tables)
        roles = conn.execute("select rolname,rolsuper,rolbypassrls,rolcreaterole from pg_roles where rolname in ('authenticated','validation_authenticator')").fetchall()
        assert len(roles) == 2 and all(row[1:] == (False, False, False) for row in roles)
        assert conn.execute("select count(*) from pg_tables where schemaname='public' and tableowner in ('authenticated','validation_authenticator')").fetchone()[0] == 0
        question = uid()
        conn.execute("insert into questions(id,user_id,category,text,source) values (%s,%s,'직무','constraints','custom')", (question, A))
        conn.execute("insert into question_competencies values (%s,'problem_solving',0)", (question,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("insert into question_competencies values (%s,'communication',0)", (question,))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("update questions set question_type='invalid' where id=%s", (question,))


def test_real_signed_api_tokens_scope_track_practice_and_nested_children(database, cluster):
    alice, bob = cluster.headers(A), cluster.headers(B)
    with database.api() as client:
        assert client.get('/track/applications').status_code == 401
        assert client.get('/track/applications', headers={'X-User-Id': A}).status_code == 401
        for bad in [cluster.headers(A, secret='a-different-disposable-key-with-at-least-32-bytes'),
                    cluster.headers(A, claims={'exp': int(time.time())-60}), cluster.headers(A, claims={'aud': 'anon'}),
                    cluster.headers('not-a-uuid'), cluster.headers(A, claims={'iss': 'https://wrong.invalid/auth/v1'})]:
            assert client.get('/track/applications', headers=bad).status_code == 401
        application = create_application(client, alice)
        app_id = application['id']
        assert ok(client.get('/track/applications', headers=bob)) == []
        assert client.get(f'/track/applications/{app_id}', headers=bob).status_code == 404
        item = ok(client.post(f'/track/applications/{app_id}/essays', headers=alice, json={'question_text': '경험', 'content': '로컬 제출본'}), 201)
        version_id = item['versions'][0]['id']
        assert client.post(f'/track/essays/{item["id"]}/versions', headers=bob, json={'content': 'forged'}).status_code == 404
        assert client.post(f'/track/versions/{version_id}/submit', headers=bob).status_code == 404
        ok(client.post(f'/track/versions/{version_id}/submit', headers=alice))
        question = create_question(client, alice)
        assert client.put(f'/practice/questions/{question["id"]}/classification', headers=bob, json={'question_type': 'knowledge'}).status_code == 404
        session = ok(client.post('/practice/sessions', headers=alice, json={'mode': 'free', 'question_ids': [question['id']], 'application_id': app_id}), 201)
        assert session['context_snapshot']['essays'][0]['version_id'] == version_id
        assert client.get(f'/practice/sessions/{session["id"]}', headers=bob).status_code == 404
        assert client.patch(f'/practice/answers/{session["answers"][0]["id"]}', headers=bob, json={'transcript': 'forged'}).status_code == 404


def seed_rls(database):
    rows = {name: uid() for name in ['app_a','app_b','item_a','item_b','version_a','version_b','q_a','q_b','q_public','session_a','session_b','answer_a','answer_b']}
    with database.connect() as conn:
        for who, user in [('a', A), ('b', B)]:
            conn.execute("insert into applications(id,user_id,company,position) values (%s,%s,'private','dev')", (rows['app_'+who], user))
            conn.execute("insert into essay_items(id,application_id,question_text) values (%s,%s,'private')", (rows['item_'+who], rows['app_'+who]))
            conn.execute("insert into answer_versions(id,essay_item_id,version_no,content,char_count) values (%s,%s,1,'private',7)", (rows['version_'+who], rows['item_'+who]))
            conn.execute("insert into questions(id,user_id,category,text,source) values (%s,%s,'직무','private','custom')", (rows['q_'+who], user))
            conn.execute("insert into question_competencies values (%s,'problem_solving',0)", (rows['q_'+who],))
            conn.execute("insert into practice_sessions(id,user_id,mode,title) values (%s,%s,'free','private')", (rows['session_'+who], user))
            conn.execute("insert into practice_answers(id,session_id,question_id,order_no) values (%s,%s,%s,1)", (rows['answer_'+who], rows['session_'+who], rows['q_'+who]))
            conn.execute("insert into practice_contexts(session_id,snapshot) values (%s,'{}')", (rows['session_'+who],))
            conn.execute("insert into application_states(application_id,baseline_stage,baseline_status) values (%s,'서류','진행중')", (rows['app_'+who],))
            conn.execute("insert into stage_events(application_id,stage,result) values (%s,'서류','대기')", (rows['app_'+who],))
            conn.execute("insert into user_settings(user_id) values (%s)", (user,))
            conn.execute("insert into practice_private_questions(question_id) values (%s)", (rows['q_'+who],))
            conn.execute("insert into answer_coaching(answer_id,report) values (%s,'{}')", (rows['answer_'+who],))
        conn.execute("insert into questions(id,category,text,source) values (%s,'직무','public','bank')", (rows['q_public'],))
    return rows


def test_nonowner_postgrest_rls_pool_claim_reset_and_bad_tokens(database, cluster):
    rows = seed_rls(database)
    with database.rest() as rest:
        for user, expected in [(A, rows['app_a']), (B, rows['app_b'])] * 4:
            identity = ok(rest.post('/rpc/validation_identity', headers=cluster.headers(user), json={}))
            assert identity == {'current_user': 'authenticated', 'session_user': 'validation_authenticator', 'uid': user}
            assert [a['id'] for a in ok(rest.get('/applications?select=id', headers=cluster.headers(user)))] == [expected]
        for headers in [{}, cluster.headers(A, secret='wrong-disposable-validation-secret-over-32-bytes'),
                        cluster.headers(A, claims={'exp': int(time.time())-60}), cluster.headers(A, claims={'aud': 'anon'}),
                        cluster.headers(A, claims={'role': 'anon'}), cluster.headers(A, claims={'role': 'validation_owner'})]:
            assert rest.get('/applications', headers=headers).status_code in {401,403}
        assert rest.get('/applications', headers=cluster.headers('bad-uuid')).status_code in {400,401,403}
        # A bad token/role request must not poison subsequent pooled claims.
        assert [a['id'] for a in ok(rest.get('/applications?select=id', headers=cluster.headers(A)))] == [rows['app_a']]
        visible = {q['id'] for q in ok(rest.get('/questions?select=id', headers=cluster.headers(A)))}
        assert visible == {rows['q_a'], rows['q_public']}
        for table in ['practice_answers','practice_contexts','question_competencies','essay_items','answer_versions','application_states','stage_events','user_settings','practice_private_questions','answer_coaching']:
            assert len(ok(rest.get('/'+table, headers=cluster.headers(A)))) == 1


def test_rls_blocks_cross_parent_inserts_and_submission_is_append_only(database, cluster):
    rows = seed_rls(database)
    h = cluster.headers(A)
    with database.connect() as conn:
        conn.execute('update answer_versions set is_submitted=true where id=%s', (rows['version_a'],))
    with database.rest() as rest:
        invalid = [
            ('application_states', {'application_id': rows['app_b'], 'baseline_stage':'서류','baseline_status':'진행중'}),
            ('user_settings', {'user_id': B}),
            ('stage_events', {'application_id': rows['app_b'], 'stage': '서류', 'result': '대기'}),
            ('essay_items', {'application_id': rows['app_b'], 'question_text': 'forged'}),
            ('answer_versions', {'essay_item_id': rows['item_b'], 'version_no': 2, 'content': 'forged', 'char_count': 6}),
            ('practice_answers', {'session_id': rows['session_b'], 'question_id': rows['q_a'], 'order_no': 2}),
            ('practice_answers', {'session_id': rows['session_a'], 'question_id': rows['q_b'], 'order_no': 2}),
            ('practice_contexts', {'session_id': rows['session_b'], 'snapshot': {}}),
            ('answer_coaching', {'answer_id': rows['answer_b'], 'report': {}}),
            ('answer_coaching', {'answer_id': rows['answer_a'], 'parent_answer_id': rows['answer_b'], 'report': {}}),
            ('practice_private_questions', {'question_id': rows['q_b']}),
            ('question_competencies', {'question_id': rows['q_b'], 'competency_key': 'communication', 'position': 1}),
            ('essay_submissions', {'essay_item_id': rows['item_a'], 'version_id': rows['version_b'], 'sequence': 1, 'source': 'web'}),
            ('essay_submissions', {'essay_item_id': rows['item_b'], 'version_id': rows['version_b'], 'sequence': 1, 'source': 'web'}),
        ]
        for table, body in invalid:
            response = rest.post('/'+table, headers=h, json=body)
            assert response.status_code in {401,403}, (table, response.status_code, response.text)
        for table, key, row_id, patch in [
            ('practice_answers','id',rows['answer_a'],{'question_id':rows['q_b']}),
            ('practice_answers','id',rows['answer_a'],{'session_id':rows['session_b']}),
            ('answer_coaching','answer_id',rows['answer_a'],{'parent_answer_id':rows['answer_b']}),
            ('essay_items','id',rows['item_a'],{'application_id':rows['app_b']}),
            ('answer_versions','id',rows['version_a'],{'essay_item_id':rows['item_b']})]:
            response=rest.patch('/'+table+'?'+key+'=eq.'+row_id,headers=h,json=patch)
            expected = {400,401,403} if table == 'answer_versions' else {401,403}
            assert response.status_code in expected, (table,response.status_code,response.text)
        submission = ok(rest.post('/essay_submissions', headers={**h,'Prefer':'return=representation'}, json={
            'essay_item_id': rows['item_a'], 'version_id': rows['version_a'], 'sequence': 1, 'source': 'web'}),201)[0]
        assert len(ok(rest.get('/essay_submissions', headers=h))) == 1
        assert ok(rest.get('/essay_submissions', headers=cluster.headers(B))) == []
        ok(rest.patch('/essay_submissions?id=eq.'+submission['id'], headers=h, json={'source':'extension'}),204)
        ok(rest.delete('/essay_submissions?id=eq.'+submission['id'], headers=h),204)
        retained = ok(rest.get('/essay_submissions', headers=h))
        assert len(retained) == 1 and retained[0]['source'] == 'web'


def test_owner_cannot_rewrite_version_or_erase_confirmation_through_fk_cascade(database, cluster):
    h = cluster.headers(A)
    with database.api() as api:
        a = create_application(api, h)
        item = ok(api.post(f"/track/applications/{a['id']}/essays", headers=h,
                          json={'question_text':'보존', 'content':'고정 제출 내용'}), 201)
        other = ok(api.post(f"/track/applications/{a['id']}/essays", headers=h,
                           json={'question_text':'다른 문항'}), 201)
        v = item['versions'][0]
        ok(api.post(f"/track/versions/{v['id']}/submit", headers=h))
        with database.rest() as rest:
            for patch in [{'content':'변경'}, {'essay_item_id':other['id']}, {'is_submitted':False}]:
                assert rest.patch('/answer_versions?id=eq.'+v['id'], headers=h, json=patch).status_code == 400
            assert rest.delete('/answer_versions?id=eq.'+v['id'], headers=h).status_code == 400
            rows = ok(rest.get('/essay_submissions', headers=h))
            assert len(rows) == 1 and rows[0]['version_id'] == v['id']
            assert ok(rest.get('/answer_versions?id=eq.'+v['id'], headers=h))[0]['content'] == v['content']
        ok(api.delete(f"/track/applications/{a['id']}", headers=h), 204)
    with database.connect() as c:
        assert c.execute('select count(*) from essay_submissions where version_id=%s',(v['id'],)).fetchone()[0] == 0


def test_actual_sync_and_version_creation_transactions_serialize(database, cluster):
    h = cluster.headers(A)
    body = {'company':'경쟁검증','position':'개발','url':'https://example.test/isolated-race', 'submitted':True,
            'essays':[{'question_text':'같은 새 문항','content':'같은 제출본'}]}
    with database.api() as client, ThreadPoolExecutor(max_workers=6) as workers:
        responses = list(workers.map(lambda _: client.post('/track/sync', headers=h, json=body), range(6)))
        results = [ok(r) for r in responses]
        assert len({r['application_id'] for r in results}) == 1
        assert sum(r['created'] for r in results) == 1
        assert sum(r['new_versions'] for r in results) == 1
        app_id = results[0]['application_id']
        detail = ok(client.get('/track/applications/'+app_id, headers=h))
        assert len(detail['essay_items']) == 1
        item = detail['essay_items'][0]
        assert len(item['versions']) == 1 and item['submission_confirmation'] == 'confirmed'
        # A second newly seen essay races on an existing application's same URL.
        additional = {**body, 'essays':[{'question_text':'두 번째 새 문항','content':'두 번째 제출본'}]}
        more = [ok(r) for r in workers.map(lambda _: client.post('/track/sync', headers=h, json=additional), range(6))]
        assert sum(r['new_versions'] for r in more) == 1
        detail = ok(client.get('/track/applications/'+app_id, headers=h))
        assert len(detail['essay_items']) == 2
        versions = [ok(r,201) for r in workers.map(lambda n: client.post(f'/track/essays/{item["id"]}/versions', headers=h,
                                 json={'content':f'distinct draft {n}'}), range(6))]
        final = ok(client.get('/track/applications/'+app_id, headers=h))
        retained = next(i for i in final['essay_items'] if i['id'] == item['id'])
        assert [v['version_no'] for v in retained['versions']] == list(range(1,8))
        assert retained['submitted_version_id'] == item['versions'][0]['id']
        assert len({v['id'] for v in retained['versions']}) == 7
        with database.connect() as conn:
            assert conn.execute('select count(*) from essay_submissions where essay_item_id=%s',(item['id'],)).fetchone()[0] == 1


def test_postgres_event_revision_and_restore_transactions_serialize(database, cluster):
    h = cluster.headers(A)
    with database.api() as client, ThreadPoolExecutor(max_workers=4) as workers:
        app = create_application(client,h)
        events = [ok(r,201) for r in workers.map(lambda n: client.post(f'/track/applications/{app["id"]}/events', headers=h,
                    json={'stage':'서류','result':'합격' if n<3 else '불합격','event_date':f'2026-11-0{n+1}'}),range(4))]
        detail = ok(client.get(f'/track/applications/{app["id"]}',headers=h))
        assert detail['status']=='불합격' and detail['state_revision']==4 and len(detail['events'])==4
        item=ok(client.post(f'/track/applications/{app["id"]}/essays',headers=h,json={'question_text':'복원','content':'원본'}),201)
        original=item['versions'][0]['id']
        [ok(r) for r in workers.map(lambda _: client.post(f'/track/versions/{original}/restore',headers=h),range(4))]
        detail=ok(client.get(f'/track/applications/{app["id"]}',headers=h))
        assert [v['version_no'] for v in detail['essay_items'][0]['versions']]==[1,2,3,4,5]


def wait_for_question_lock(database):
    deadline=time.monotonic()+8
    with database.connect() as observer:
        while time.monotonic()<deadline:
            blocked=observer.execute("select count(*) from pg_stat_activity where datname=current_database() and wait_event_type='Lock' and query ilike 'UPDATE questions%'").fetchone()[0]
            if blocked:
                return
            time.sleep(.02)
    pytest.fail('Real API did not wait for the held question row lock')


@pytest.mark.parametrize('filtered',[False,True])
def test_concurrent_reclassification_and_capture_is_atomic(database,cluster,filtered):
    h=cluster.headers(A)
    with database.api() as client,ThreadPoolExecutor(max_workers=1) as worker:
        question=create_question(client,h)
        body={'mode':'free','question_ids':[question['id']]}
        if filtered:
            body={'mode':'free','question_types':['behavioral'],'competency_keys':['problem_solving','communication'],'competency_match':'all','count':1}
        with database.connect() as editor:
            with editor.transaction():
                editor.execute("update questions set question_type='knowledge',tagging_source='manual' where id=%s",(question['id'],))
                editor.execute("delete from question_competencies where question_id=%s",(question['id'],))
                editor.execute("insert into question_competencies values (%s,'technical_expertise',0)",(question['id'],))
                future=worker.submit(client.post,'/practice/sessions',headers=h,json=body)
                wait_for_question_lock(database)
            response=future.result(timeout=15)
        if filtered:
            assert response.status_code==409,response.text
            assert ok(client.get('/practice/sessions',headers=h))==[]
        else:
            session=ok(response,201)
            frozen=session['answers'][0]['question_classification']
            assert frozen['question_type']=='knowledge' and frozen['competency_keys']==['technical_expertise']
            ok(client.put(f'/practice/questions/{question["id"]}/classification',headers=h,json={'question_type':'situational','competency_keys':['collaboration']}))
            fetched=ok(client.get(f'/practice/sessions/{session["id"]}',headers=h))
            assert fetched['answers'][0]['question_classification']==frozen


def test_feature_on_off_on_preserves_historical_classification(database,cluster):
    h=cluster.headers(A)
    with database.api(insights=True) as client:
        question=create_question(client,h)
        session=ok(client.post('/practice/sessions',headers=h,json={'mode':'free','question_ids':[question['id']]}),201)
        frozen=session['answers'][0]['question_classification']
    with database.api(insights=False) as client:
        assert ok(client.get('/practice/taxonomy',headers=h))['enabled'] is False
        assert client.put(f'/practice/questions/{question["id"]}/classification',headers=h,json={'question_type':'knowledge'}).status_code==409
        legacy=ok(client.post('/practice/sessions',headers=h,json={'mode':'free','question_ids':[question['id']]}),201)
    with database.api(insights=True) as client:
        original=ok(client.get(f'/practice/sessions/{session["id"]}',headers=h))
        untouched=ok(client.get(f'/practice/sessions/{legacy["id"]}',headers=h))
        assert original['answers'][0]['question_classification']==frozen
        assert untouched['answers'][0]['question_classification'] is None


@pytest.mark.parametrize('replace_recording',[True,False])
def test_postgres_feature_off_cannot_reuse_recording_or_coaching_identity(database,cluster,replace_recording):
    h=cluster.headers(A)
    text='장애 로그를 분류하고 배포 점검표를 작성했습니다.'
    with database.api(insights=True) as client:
        question=create_question(client,h)
        session=ok(client.post('/practice/sessions',headers=h,json={'mode':'free','question_ids':[question['id']]}),201)
        aid=session['answers'][0]['id']
        ok(client.put('/practice/settings',headers=h,json={'consent':True}))
        ok(client.post(f'/practice/answers/{aid}/audio',headers=h,files={'file':('synthetic.webm',b'synthetic-local-only','audio/webm')}))
        first=ok(client.patch(f'/practice/answers/{aid}',headers=h,json={'transcript':text}))
        assert first['recording_transcript_current'] is True
        assert ok(client.post(f'/practice/answers/{aid}/coach',headers=h))['coaching_report']
    with database.api(insights=False) as client:
        if replace_recording:
            ok(client.post(f'/practice/answers/{aid}/audio',headers=h,files={'file':('replacement.webm',b'synthetic-new-local-only','audio/webm')}))
        ok(client.patch(f'/practice/answers/{aid}',headers=h,json={'transcript':text,**({} if replace_recording else {'input_mode':'text'})}))
    with database.api(insights=True) as client:
        answer=ok(client.get(f'/practice/sessions/{session["id"]}',headers=h))['answers'][0]
        assert answer['recording_transcript_current'] is False
        if replace_recording:
            assert answer['coaching_report'] is None
        else:
            assert answer['coaching_report']['input_status'] == 'current'


def test_ambiguous_legacy_tag_positions_stop_upgrade_without_deleting_rows(cluster):
    database=cluster.database('historical')
    for path in sorted((ROOT/'supabase/migrations').glob('*.sql')):
        if path.name < '20261105':
            database.apply(path)
    question=uid()
    with database.connect() as conn:
        conn.execute("insert into questions(id,user_id,category,text,source) values (%s,%s,'직무','ambiguous','custom')",(question,A))
        conn.execute("insert into question_competencies values (%s,'problem_solving',0),(%s,'communication',0)",(question,question))
    with pytest.raises(psycopg.errors.RaiseException,match='Duplicate competency positions'):
        database.apply(ROOT/'supabase/migrations/20261105_practice_integrity.sql')
    with database.connect() as conn:
        assert conn.execute('select count(*) from question_competencies where question_id=%s',(question,)).fetchone()[0]==2


def test_track_schema_prerequisite_fails_before_startup_even_with_insights_off(cluster):
    database=cluster.database('historical')
    with pytest.raises(RuntimeError,match='20261105_track_integrity.sql'):
        with database.api(insights=False):
            pass
