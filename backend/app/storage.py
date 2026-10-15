"""녹음 파일 저장. SUPABASE_URL과 서비스 키가 있으면 Supabase Storage, 없으면 로컬 폴더."""
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)


def _use_supabase() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _sb_headers() -> dict[str, str]:
    key = settings.supabase_service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _sb_object_url(path: str) -> str:
    return f"{settings.supabase_url}/storage/v1/object/{settings.storage_bucket}/{path}"


def save(path: str, data: bytes, content_type: str) -> None:
    if _use_supabase():
        r = httpx.post(
            _sb_object_url(path),
            headers={**_sb_headers(), "Content-Type": content_type, "x-upsert": "true"},
            content=data,
            timeout=60,
        )
        r.raise_for_status()
        return
    dest = settings.local_recordings_dir / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def load(path: str) -> bytes | None:
    if _use_supabase():
        r = httpx.get(_sb_object_url(path), headers=_sb_headers(), timeout=60)
        return r.content if r.status_code == 200 else None
    f = settings.local_recordings_dir / path
    return f.read_bytes() if f.exists() else None


def _sb_not_found(r: httpx.Response) -> bool:
    # Supabase Storage는 없는 객체에 400 + {"statusCode": "404"}를 돌려주기도 한다
    if r.status_code == 404:
        return True
    try:
        return r.status_code == 400 and str(r.json().get("statusCode")) == "404"
    except (ValueError, AttributeError):
        return False


def delete(path: str) -> bool:
    """녹음 파일을 지운다. 이미 없으면 지운 것으로 본다. 실패하면 경고만 남기고 False(예외 없음)."""
    if _use_supabase():
        try:
            r = httpx.delete(_sb_object_url(path), headers=_sb_headers(), timeout=30)
        except httpx.HTTPError as e:
            log.warning("녹음 삭제 요청 실패(%s): %s", path, e)
            return False
        if r.status_code in (200, 204) or _sb_not_found(r):
            return True
        log.warning("녹음 삭제 실패(%s): HTTP %s", path, r.status_code)
        return False
    try:
        (settings.local_recordings_dir / path).unlink(missing_ok=True)
    except OSError as e:
        log.warning("로컬 녹음 삭제 실패(%s): %s", path, e)
        return False
    return True
