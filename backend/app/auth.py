import jwt
from fastapi import Header, HTTPException

from .config import settings
from .models import valid_id

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


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
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"유효하지 않은 토큰: {e}") from e
    return payload["sub"]
