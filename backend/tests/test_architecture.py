"""계층 규칙: HTTP 라우터는 서비스를 부르고, 서비스·백그라운드 작업은 라우터를 가져오지 않는다."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            out.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_only_main_imports_routers():
    offenders = {str(f.relative_to(APP)): sorted(m for m in _imports(f) if "routers" in m)
                 for f in APP.rglob("*.py") if "routers" not in f.parts and f.name != "main.py"}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_services_do_not_raise_http_errors():
    for f in (APP / "services").glob("*.py"):
        assert not any("fastapi" in m for m in _imports(f)), f.name


def test_coaching_service_reports_a_changed_transcript():
    """점검하는 동안 전사문이 바뀌면 보고서를 저장하지 않고 TranscriptChanged를 던진다(라우터는 409로 바꾼다)."""
    import pytest

    from app.services import answer_coaching

    assert issubclass(answer_coaching.TranscriptChanged, Exception)
    assert issubclass(answer_coaching.NoTranscript, Exception)
    with pytest.raises(answer_coaching.NoTranscript):
        answer_coaching.coach(type("A", (), {"transcript": "  "})(), None)
