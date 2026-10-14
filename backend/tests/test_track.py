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
