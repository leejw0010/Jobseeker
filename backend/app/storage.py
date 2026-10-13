"""녹음 파일 저장. SUPABASE_URL과 서비스 키가 있으면 Supabase Storage, 없으면 로컬 폴더."""
import httpx

from .config import settings


def _use_supabase() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _sb_headers() -> dict[str, str]:
    key = settings.supabase_service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def save(path: str, data: bytes, content_type: str) -> None:
    if _use_supabase():
        r = httpx.post(
            f"{settings.supabase_url}/storage/v1/object/{settings.storage_bucket}/{path}",
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
        r = httpx.get(
            f"{settings.supabase_url}/storage/v1/object/{settings.storage_bucket}/{path}",
            headers=_sb_headers(),
            timeout=60,
        )
        return r.content if r.status_code == 200 else None
    f = settings.local_recordings_dir / path
    return f.read_bytes() if f.exists() else None
