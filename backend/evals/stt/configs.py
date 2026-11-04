"""평가 설정 12개(설계 6절). 결과를 본 뒤 바꾸지 않는다. 기준 B0은 운영 설정과 같다."""
from dataclasses import dataclass

# 말하지 않을 용어. 프롬프트·hotwords에 섞어 넣고, 출력에 나오면 "지어낸 용어"로 센다
DECOYS = ["쿠버네티스", "그라파나", "카산드라", "테라폼", "엘라스틱서치"]
# 간투사·말 고침이 든 예시 문장(용어 없음). 모델이 말버릇을 지우지 않고 적도록 유도하는지 본다
VERBATIM_PROMPT = "음, 그러니까 제가 어, 그 프로젝트에서- 그 프로젝트에서 맡은 건요."


@dataclass(frozen=True)
class Config:
    id: str
    model: str
    beam_size: int = 5
    vad_filter: bool = True
    hotwords: bool = False
    prompt: str | None = None  # None | "terms" | "verbatim"


CONFIGS = [
    c
    for m in ("base", "small")
    for c in (
        Config(f"{m}-default", m),
        Config(f"{m}-beam1", m, beam_size=1),
        Config(f"{m}-vadoff", m, vad_filter=False),
        Config(f"{m}-hot", m, hotwords=True),
        Config(f"{m}-prompt-terms", m, prompt="terms"),
        Config(f"{m}-prompt-verbatim", m, prompt="verbatim"),
    )
]
_BY_ID = {c.id: c for c in CONFIGS}


def config(config_id: str) -> Config:
    return _BY_ID[config_id]


def overrides(cfg: Config, prompt_terms: list[str]) -> dict:
    """stt.run_whisper에 넘길 인자. language·task·condition_on_previous_text는 운영 기본값을 그대로 쓴다."""
    out = {"beam_size": cfg.beam_size, "vad_filter": cfg.vad_filter}
    terms = ", ".join(sorted(set(prompt_terms) | set(DECOYS)))
    if cfg.hotwords:
        out["hotwords"] = terms
    if cfg.prompt == "terms":
        out["initial_prompt"] = f"다음 용어가 나올 수 있습니다: {terms}."
    elif cfg.prompt == "verbatim":
        out["initial_prompt"] = VERBATIM_PROMPT
    return out
