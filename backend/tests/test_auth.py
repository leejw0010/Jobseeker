"""AUTH_DISABLED=false 경로: Supabase 액세스 토큰(HS256, aud=authenticated)의 sub만 사용자로 쓴다.

다른 테스트는 개발 모드(X-User-Id)로 돈다. 여기서는 같은 앱의 설정만 잠시 바꿔 실제 JWT 검증 경로를 지난다.
비밀값은 테스트 전용 문자열이다(실제 프로젝트 값 아님).
"""
import time
import uuid

import jwt
import pytest

from app.config import settings

SECRET = "test-only-jwt-secret-not-a-real-project-key"


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
    monkeypatch.setattr(settings, "jwt_mode", "hs256", raising=False)


def token(claims: dict | None = None, secret: str = SECRET, drop: tuple[str, ...] = ()) -> str:
    body = {"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": "https://test.supabase.co/auth/v1", "exp": int(time.time()) + 300, **(claims or {})}
    for key in drop:
        body.pop(key, None)
    return jwt.encode(body, secret, algorithm="HS256")


def bearer(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def test_missing_header_is_401(client, auth_on):
    assert client.get("/track/applications").status_code == 401


def test_dev_header_is_ignored_when_auth_on(client, auth_on):
    r = client.get("/track/applications", headers={"X-User-Id": str(uuid.uuid4())})
    assert r.status_code == 401


def test_non_bearer_scheme_is_401(client, auth_on):
    assert client.get("/track/applications", headers={"Authorization": f"Basic {token()}"}).status_code == 401


@pytest.mark.parametrize("bad", [
    token({"exp": int(time.time()) - 10}),  # 만료
    token(secret="another-test-only-secret-with-32-bytes+"),  # 서명이 다름
    token({"aud": "anon"}),  # 대상이 다름
    token(drop=("aud",)),
    token(drop=("exp",)),
    token(drop=("iss",)),
    token({"iss": "https://other.supabase.co/auth/v1"}),  # 대상 없음
    "not-a-jwt",
])
def test_invalid_tokens_are_401(client, auth_on, bad):
    assert client.get("/track/applications", headers=bearer(bad)).status_code == 401


@pytest.mark.parametrize("claims, drop", [({}, ("sub",)), ({"sub": "not-a-uuid"}, ()), ({"sub": ""}, ())])
def test_token_without_usable_sub_is_401(client, auth_on, claims, drop):
    """sub가 없거나 uuid가 아니면 사용자 id로 쓸 수 없다(500이 아니라 401)."""
    assert client.get("/track/applications", headers=bearer(token(claims, drop=drop))).status_code == 401


def test_valid_token_scopes_data_to_its_user(client, auth_on):
    alice, bob = bearer(token()), bearer(token())
    r = client.post("/track/applications", json={"company": "A사", "position": "백엔드"}, headers=alice)
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    assert [a["id"] for a in client.get("/track/applications", headers=alice).json()] == [app_id]
    assert client.get("/track/applications", headers=bob).json() == []
    assert client.get(f"/track/applications/{app_id}", headers=bob).status_code == 404
