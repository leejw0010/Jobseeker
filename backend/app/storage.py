"""녹음 파일 저장. SUPABASE_URL과 서비스 키가 있으면 Supabase Storage, 없으면 로컬 폴더."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import settings

log = logging.getLogger(__name__)

_SB_LIST_LIMIT = 100  # Supabase Storage 목록 API 한 번에 받는 개수


@dataclass(frozen=True)
class StoredObject:
    path: str  # 버킷(로컬 녹음 폴더) 안의 경로
    modified: datetime | None  # 마지막으로 저장한 시각(UTC). 모르면 None


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


def _sb_time(entry: dict) -> datetime | None:
    value = entry.get("updated_at") or entry.get("created_at")
    try:
        t = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _sb_list(prefix: str) -> list[StoredObject]:
    """Supabase Storage 목록 API는 한 단계(폴더)씩, 페이지로 나눠 돌려준다. 폴더는 id가 없다."""
    out: list[StoredObject] = []
    folders: list[str] = []
    offset = 0
    while True:
        r = httpx.post(f"{settings.supabase_url}/storage/v1/object/list/{settings.storage_bucket}", headers=_sb_headers(),
                       json={"prefix": prefix, "limit": _SB_LIST_LIMIT, "offset": offset,
                             "sortBy": {"column": "name", "order": "asc"}}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        for entry in rows:
            if entry.get("id") is None:
                folders.append(f"{prefix}{entry['name']}/")
            else:
                out.append(StoredObject(f"{prefix}{entry['name']}", _sb_time(entry)))
        if len(rows) < _SB_LIST_LIMIT:
            break
        offset += _SB_LIST_LIMIT
    for folder in folders:
        out.extend(_sb_list(folder))
    return out


def list(prefix: str = "") -> list[StoredObject]:  # 내장 list를 가리지만 save·load·delete와 같은 꼴(storage.list)로 쓴다
    """prefix('{user_id}/' 같은 폴더, 빈 문자열이면 전체) 아래의 파일을 하위 폴더까지 모두 돌려준다.

    답변 행이 가리키지 않는 파일(고아 파일)을 찾아 지우는 데 쓴다. 저장소 오류는 예외로 알린다.
    """
    if _use_supabase():
        return _sb_list(prefix)
    root = settings.local_recordings_dir
    base = root / prefix
    if not base.is_dir():
        return []
    return [StoredObject(f.relative_to(root).as_posix(), datetime.fromtimestamp(f.stat().st_mtime, timezone.utc))
            for f in sorted(base.rglob("*")) if f.is_file()]
