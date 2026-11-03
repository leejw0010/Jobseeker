"""단계·상태·분류 같은 열거값은 models.py, schemas.py, supabase/schema.sql, web/src/types.ts에 따로 적혀 있다.
한 곳만 바꾸면 화면·API·DB 중 하나가 값을 거부하므로 네 곳이 같은지 검사한다."""
import re
from pathlib import Path
from typing import get_args

import pytest

from app import models, schemas

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
TS = (ROOT / "web" / "src" / "types.ts").read_text(encoding="utf-8")


def sql_check(column: str) -> list[list[str]]:
    """schema.sql에서 `column in (...)` check 목록(같은 이름의 컬럼이 여러 테이블에 있으면 모두)."""
    return [re.findall(r"'([^']*)'", m) for m in re.findall(rf"check \({column} in \(([^)]*)\)\)", SQL)]


def ts_array(name: str) -> list[str]:
    m = re.search(rf"export const {name} = \[([^\]]*)\]", TS)
    assert m, name
    return re.findall(r'"([^"]*)"', m.group(1))


def ts_union(name: str) -> list[str]:
    m = re.search(rf"export type {name} = ([^;]*);", TS)
    assert m, name
    return re.findall(r'"([^"]*)"', m.group(1))


@pytest.mark.parametrize("values, literal, ts, sql", [
    (models.STAGES, schemas.Stage, ts_array("STAGES"), "stage"),
    (models.STATUSES, schemas.Status, ts_array("STATUSES"), "status"),
    (models.QUESTION_CATEGORIES, schemas.Category, ts_array("CATEGORIES"), "category"),
])
def test_enum_lists_match_everywhere(values, literal, ts, sql):
    assert list(get_args(literal)) == values
    assert ts == values
    checks = sql_check(sql)
    assert checks and all(c == values for c in checks), checks


def test_debrief_statuses_match():
    assert ts_union("DebriefStatus") == models.DEBRIEF_STATUSES
    assert sql_check("debrief_status") == [models.DEBRIEF_STATUSES]


def test_stats_counts_every_status(client):
    """통계의 상태별 개수는 STATUSES를 그대로 쓴다(새 상태를 더하면 함께 센다)."""
    assert list(client.get("/track/stats", headers={"X-User-Id": "user-enum"}).json()["status"]) == models.STATUSES
