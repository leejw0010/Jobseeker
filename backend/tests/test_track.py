import pytest

U = {"X-User-Id": "user-track-1"}
U2 = {"X-User-Id": "user-track-2"}


def _new(client, company, cat="개발"):
    r = client.post("/track/applications", json={"company": company, "position": "백엔드", "job_category": cat}, headers=U)
    assert r.status_code == 201, r.text
    return r.json()


def test_stage_events_update_status(client):
    a = _new(client, "카카오")
    r = client.post(f"/track/applications/{a['id']}/events", json={"stage": "서류", "result": "합격"}, headers=U).json()
    assert r["stage"] == "인적성" and r["status"] == "진행중"
    r = client.post(f"/track/applications/{a['id']}/events", json={"stage": "인적성", "result": "불합격"}, headers=U).json()
    assert r["stage"] == "인적성" and r["status"] == "불합격"
    assert len(r["events"]) == 2
    assert client.get(f"/track/applications/{a['id']}", headers=U2).status_code == 404


def test_versions_dedupe_and_restore(client):
    a = _new(client, "라인")
    item = client.post(f"/track/applications/{a['id']}/essays",
                       json={"question_text": "지원 동기", "char_limit": 500, "content": "v1 내용"}, headers=U).json()
    assert [v["version_no"] for v in item["versions"]] == [1]
    item = client.post(f"/track/essays/{item['id']}/versions", json={"content": "v2 내용"}, headers=U).json()
    item = client.post(f"/track/essays/{item['id']}/versions", json={"content": "v2 내용"}, headers=U).json()
    assert [v["version_no"] for v in item["versions"]] == [1, 2]  # 같은 내용은 새 버전 X
    v1 = item["versions"][0]["id"]
    item = client.post(f"/track/versions/{v1}/restore", headers=U).json()
    assert item["versions"][-1]["content"] == "v1 내용" and item["versions"][-1]["version_no"] == 3
    hits = client.get("/track/answers/search", params={"q": "v2"}, headers=U).json()
    assert hits and hits[0]["company"] == "라인"


def test_extension_sync_upsert(client):
    body = {"company": "토스", "position": "서버 개발자", "job_category": "개발", "url": "https://toss.im/career/123",
            "essays": [{"question_text": "자기소개", "content": "첫 제출"}]}
    r1 = client.post("/track/sync", json=body, headers=U).json()
    assert r1["created"] and r1["new_versions"] == 1
    r2 = client.post("/track/sync", json=body, headers=U).json()
    assert not r2["created"] and r2["new_versions"] == 0 and r2["application_id"] == r1["application_id"]
    body["essays"][0]["content"] = "수정 제출"
    body["essays"].append({"question_text": "직무 역량", "content": "새 문항"})
    r3 = client.post("/track/sync", json=body, headers=U).json()
    assert r3["new_versions"] == 2
    detail = client.get(f"/track/applications/{r1['application_id']}", headers=U).json()
    assert detail["source"] == "extension" and detail["applied_at"]
    assert all(v["is_submitted"] for i in detail["essay_items"] for v in i["versions"])


def test_stats_funnel(client):
    h = {"X-User-Id": "user-stats"}
    ids = []
    for c, cat in [("A", "개발"), ("B", "개발"), ("C", "기획")]:
        ids.append(client.post("/track/applications", json={"company": c, "position": "p", "job_category": cat},
                               headers=h).json()["id"])
    client.post(f"/track/applications/{ids[0]}/events", json={"stage": "서류", "result": "합격"}, headers=h)
    client.post(f"/track/applications/{ids[1]}/events", json={"stage": "서류", "result": "불합격"}, headers=h)
    s = client.get("/track/stats", headers=h).json()
    assert s["total"] == 3
    doc = s["funnel"][0]
    # 서류: 3건 도달, 1 통과, 1 탈락, 1 대기 → 확정 2건 중 1건 통과
    assert (doc["reached"], doc["passed"], doc["failed"], doc["pending"], doc["pass_rate"]) == (3, 1, 1, 1, 0.5)
    dev = next(c for c in s["by_job_category"] if c["job_category"] == "개발")
    assert dev["total"] == 2


def test_posting_saved_from_popup_then_found_by_url(client):
    """확장 팝업: 공고만 저장(submitted=false)하면 지원일은 비워 두고, URL로 다시 찾을 수 있다."""
    h = {"X-User-Id": "user-popup"}
    url = "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1"
    r = client.post("/track/sync", json={"company": "당근", "position": "iOS 개발자", "job_category": "개발",
                                         "url": url, "essays": [], "submitted": False}, headers=h).json()
    assert r["created"] and r["new_versions"] == 0
    found = client.get("/track/applications", params={"url": url}, headers=h).json()
    assert len(found) == 1 and found[0]["applied_at"] is None and found[0]["source"] == "extension"
    assert client.get("/track/applications", params={"url": url + "&x=1"}, headers=h).json() == []


# ───────── DB 제약·동시성 (Supabase schema.sql과 같은 규칙) ─────────

def test_duplicate_url_is_409_on_create_and_patch(client):
    """같은 사용자의 같은 공고 URL은 한 건이다(schema.sql의 applications_user_url_uq와 같다). 다른 사용자는 상관없다."""
    url = "https://example.com/jobs/dup-1"
    body = {"company": "중복사", "position": "백엔드", "url": url}
    assert client.post("/track/applications", json=body, headers=U).status_code == 201
    r = client.post("/track/applications", json=body, headers=U)
    assert r.status_code == 409 and "URL" in r.json()["detail"]
    assert client.post("/track/applications", json=body, headers=U2).status_code == 201
    other = _new(client, "다른사")
    r = client.patch(f"/track/applications/{other['id']}", json={"url": url}, headers=U)
    assert r.status_code == 409
    assert client.get(f"/track/applications/{other['id']}", headers=U).json()["url"] is None


def test_blank_url_is_stored_as_none(client):
    """빈 URL은 '없음'이다. 빈 문자열끼리 고유 제약에 걸리지 않는다."""
    for _ in range(2):
        r = client.post("/track/applications", json={"company": "빈주소", "position": "백엔드", "url": "  "}, headers=U)
        assert r.status_code == 201 and r.json()["url"] is None


def test_sync_race_on_the_same_url_updates_the_row_the_other_request_created(client, monkeypatch):
    """두 동기화가 같은 URL을 동시에 처음 보면 둘 다 '없음'으로 읽는다. 늦게 커밋한 쪽은 고유 제약에 걸리고,
    다시 찾아 그 행을 갱신한다(500이나 중복 행 없이)."""
    from app.routers import track

    body = {"company": "경합사", "position": "백엔드", "url": "https://example.com/jobs/race-1",
            "essays": [{"question_text": "지원 동기", "content": "첫 내용"}]}
    initial = client.post("/track/sync", json=body, headers=U)
    assert initial.status_code == 200, initial.text
    first = initial.json()
    real = track._find_by_url
    lookup_count = 0

    def miss_first_lookup(db, user_id, url):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None  # 다른 요청이 이미 저장한 행을 첫 조회에서는 못 본 상황
        return real(db, user_id, url)

    monkeypatch.setattr(track, "_find_by_url", miss_first_lookup)
    r = client.post("/track/sync", json={**body, "essays": [{"question_text": "지원 동기", "content": "둘째 내용"}]}, headers=U)
    assert r.status_code == 200, r.text
    assert lookup_count == 2  # 실제 고유 제약 충돌 뒤 rollback하고 다시 조회한다
    assert r.json() == {"application_id": first["application_id"], "created": False, "new_versions": 1}
    rows = client.get("/track/applications", params={"url": body["url"]}, headers=U).json()
    assert len(rows) == 1
    detail = client.get(f"/track/applications/{first['application_id']}", headers=U).json()
    assert len(detail["essay_items"]) == 1
    assert [(v["version_no"], v["content"]) for v in detail["essay_items"][0]["versions"]] == [
        (1, "첫 내용"), (2, "둘째 내용"),
    ]


def test_version_number_is_read_after_locking_the_item(client):
    """다른 요청이 그사이 버전을 저장했어도(읽어 둔 목록이 낡음) 번호가 겹치지 않는다."""
    from app.db import SessionLocal
    from app.models import EssayItem
    from app.services.track_versions import add_version

    a = _new(client, "버전경합")
    item = client.post(f"/track/applications/{a['id']}/essays", json={"question_text": "문항", "content": "v1"},
                       headers=U).json()
    with SessionLocal() as db:
        stale = db.get(EssayItem, item["id"])
        assert [v.version_no for v in stale.versions] == [1]
        client.post(f"/track/essays/{item['id']}/versions", json={"content": "v2"}, headers=U)
        add_version(db, stale, "v3", "web", False)
        db.commit()
    got = client.get(f"/track/essays/{item['id']}/versions", headers=U).json()
    assert [(v["version_no"], v["content"]) for v in got] == [(1, "v1"), (2, "v2"), (3, "v3")]


def test_same_content_as_a_concurrently_saved_latest_makes_no_new_version(client):
    from app.db import SessionLocal
    from app.models import EssayItem
    from app.services.track_versions import add_version

    a = _new(client, "버전중복")
    item = client.post(f"/track/applications/{a['id']}/essays", json={"question_text": "문항", "content": "v1"},
                       headers=U).json()
    with SessionLocal() as db:
        stale = db.get(EssayItem, item["id"])
        _ = stale.versions
        client.post(f"/track/essays/{item['id']}/versions", json={"content": "같은 내용"}, headers=U)
        assert add_version(db, stale, "같은 내용", "web", True) is None
        db.commit()
    got = client.get(f"/track/essays/{item['id']}/versions", headers=U).json()
    assert [(v["version_no"], v["is_submitted"]) for v in got] == [(1, False), (2, True)]



@pytest.mark.parametrize("field", ["company", "position", "job_category", "stage", "status"])
def test_patch_null_on_required_field_is_422(client, field):
    """필드를 빼면 그대로 두고, 필수 필드에 null을 보내면 422(예전에는 DB NOT NULL 오류로 500)."""
    a = _new(client, "널검사")
    r = client.patch(f"/track/applications/{a['id']}", json={field: None}, headers=U)
    assert r.status_code == 422, r.text
    assert client.get(f"/track/applications/{a['id']}", headers=U).json()[field] == a[field]


@pytest.mark.parametrize("field", ["url", "applied_at", "notes"])
def test_patch_null_clears_optional_fields(client, field):
    a = client.post("/track/applications", json={"company": "비우기", "position": "백엔드", "notes": "메모",
                                                  "url": f"https://example.com/jobs/clear-{field}",
                                                  "applied_at": "2026-10-01"}, headers=U).json()
    r = client.patch(f"/track/applications/{a['id']}", json={field: None}, headers=U)
    assert r.status_code == 200 and r.json()[field] is None
