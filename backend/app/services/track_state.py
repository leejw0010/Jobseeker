"""Current application state has explicit provenance; history never guesses manual intent."""
from datetime import timezone

from ..models import Application, ApplicationState, STAGES


def initialize(app: Application) -> None:
    app.state_control = ApplicationState(baseline_stage=app.stage, baseline_status=app.status, revision=0)


def control(app: Application) -> ApplicationState:
    if app.state_control is None:
        app.state_control = ApplicationState(override_stage=app.stage, override_status=app.status,
                                             override_origin="legacy", revision=0)
    return app.state_control


def manual(app: Application) -> None:
    state = control(app)
    state.override_stage, state.override_status = app.stage, app.status
    state.override_origin = "manual"
    state.revision += 1


def project(app: Application) -> None:
    state = control(app)
    state.revision += 1
    if state.override_origin:
        app.stage, app.status = state.override_stage, state.override_status
        return
    stage, status = state.baseline_stage, state.baseline_status
    for ev in sorted(app.events, key=lambda e: (e.event_date, e.created_at.replace(tzinfo=timezone.utc).timestamp(), e.id)):
        stage = ev.stage
        if ev.result == "합격":
            index = STAGES.index(stage)
            stage, status = (STAGES[index + 1], "진행중") if index + 1 < len(STAGES) else (stage, "합격")
        else:
            status = "불합격" if ev.result == "불합격" else "진행중"
    app.stage, app.status = stage, status


def use_events(app: Application, baseline_stage: str | None, baseline_status: str | None) -> None:
    state = control(app)
    if state.baseline_stage is None and (baseline_stage is None or baseline_status is None):
        raise ValueError("이전 기록의 시작 단계와 상태를 선택해 주세요")
    if (baseline_stage is None) != (baseline_status is None):
        raise ValueError("시작 단계와 상태는 함께 선택해 주세요")
    if baseline_stage is not None:
        state.baseline_stage, state.baseline_status = baseline_stage, baseline_status
    state.override_origin = state.override_stage = state.override_status = None
    project(app)
