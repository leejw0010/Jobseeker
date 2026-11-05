from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from .config import settings
from .models import valid_id

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


@lru_cache(maxsize=8)
def _jwks_client(project_url: str) -> jwt.PyJWKClient:
    # Only the configured project determines the endpoint. Never read jku/x5u from a token.
    return jwt.PyJWKClient(project_url + "/auth/v1/.well-known/jwks.json", timeout=5,
                           cache_jwk_set=True, lifespan=300)


def _decode_token(token: str) -> dict:
    if settings.jwt_mode == "jwks":
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in {"RS256", "ES256"} or not isinstance(header.get("kid"), str) or not header["kid"]:
            raise jwt.InvalidTokenError("Unsupported signing key")
        signing_key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        if signing_key.algorithm_name != algorithm:
            raise jwt.InvalidTokenError("Signing key algorithm mismatch")
        key = signing_key.key
        algorithms = [algorithm]
    elif settings.jwt_mode == "hs256" and settings.jwt_secret:
        key = settings.jwt_secret
        algorithms = ["HS256"]
    else:
        raise jwt.InvalidTokenError("Authentication configuration unavailable")
    return jwt.decode(token, key, algorithms=algorithms, audience="authenticated",
                      issuer=settings.supabase_url + "/auth/v1",
                      options={"require": ["exp", "iss", "aud", "sub"]})


def current_user_id(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    """Supabase 액세스 토큰(Bearer)의 sub를 사용자 id로 쓴다.

    AUTH_DISABLED=true(개발 모드)면 X-User-Id 헤더나 고정 dev 사용자를 쓴다.
    """
    if settings.auth_disabled:
        # Supabase(Postgres)의 user_id는 uuid 컬럼이다. 로컬 SQLite는 아무 문자열이나 쓸 수 있다
        if x_user_id and not settings.database_url.startswith("sqlite") and not valid_id(x_user_id):
            raise HTTPException(400, "X-User-Id 헤더는 UUID여야 해요")
        return x_user_id or DEV_USER_ID
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "로그인이 필요합니다")
    token = authorization.split(" ", 1)[1]
    try:
        payload = _decode_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(401, "유효하지 않은 토큰입니다") from e
    # Supabase 사용자 id(uuid)만 받는다. 없거나 형식이 다르면 user_id 컬럼(uuid)에 쓸 수 없다
    sub = payload.get("sub")
    if not isinstance(sub, str) or not valid_id(sub):
        raise HTTPException(401, "유효하지 않은 토큰: 사용자 id(sub)가 없어요")
    return sub
