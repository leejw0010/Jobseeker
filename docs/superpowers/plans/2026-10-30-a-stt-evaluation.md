# A. 로컬 STT 정확도 평가 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `base`와 `small`(및 beam·VAD·프롬프트·hotwords)을 운영과 같은 전사 경로로 재현 가능하게 비교하는 평가 도구를 만들고, 공개 낭독 세트(P)로 실측한다.

**Architecture:** 운영 `stt.py`에서 Whisper 호출·텍스트 결합을 `run_whisper`로 꺼내 평가와 운영이 같은 함수를 쓴다. 평가 도구는 `backend/evals/stt/`의 순수 채점(`score`), 설정(`configs`), 데이터 준비(`data`), 하위 프로세스 실행·메모리 감시(`run`), 보고서(`report`)로 나눈다. 데이터·원본 출력은 저장소 밖 `--data-dir`에 둔다.

**Tech Stack:** Python 3.12, faster-whisper 1.2.1, PyAV 19, numpy, httpx, pytest.

**Spec:** [docs/superpowers/specs/2026-10-30-a-stt-evaluation-design.md](../specs/2026-10-30-a-stt-evaluation-design.md)

## Global Constraints

- commit·push·merge·reset·stash·브랜치 전환 금지. 계획의 "Commit" 단계는 `git status --short`로 바뀐 파일 확인으로 대신한다.
- 새 의존성 금지(표준 라이브러리, `numpy`, `av`, `faster_whisper`, `httpx`만).
- 기본 STT 설정(`config.py`의 `LOCAL_STT_*` 기본값, `run_whisper` 기본 인자)은 운영값과 같게 유지: `language="ko"`, `task="transcribe"`, `beam_size=settings.local_stt_beam_size`, `vad_filter=True`, `condition_on_previous_text=False`.
- `backend/.env`, `backend/jobseeker.db`, `backend/recordings/`는 읽거나 출력하지 않는다. 환경 기록에는 평가가 설정한 `LOCAL_STT_*`만 쓰고 프로세스는 이름(comm)·RSS만 쓴다(명령줄 인자 기록 금지).
- 데이터·결과는 `--data-dir`(저장소 밖). 이번 실행은 `/tmp/claude-1000/-home-user-projects-Jobseeker/832070b4-75af-4f3c-a749-7b160637f4a9/scratchpad/stt-eval`.
- 메모리 중단 조건: `MemAvailable` < 200MB, 시작 대비 스왑 사용 증가 > 256MB, PSI `full` avg10 > 10 중 하나가 2초 넘게 지속 → 평가 하위 프로세스만 SIGTERM, 5초 뒤 SIGKILL. 다른 프로세스·시스템 설정은 건드리지 않음.
- 구간 길이: 빠뜨린 말·지어낸 말은 연속 5글자 이상을 세고, 10글자 이상은 "심각"으로 따로 센다. 문장 지어 붙이기는 `//` 뒤 삽입 2글자 이상.
- 데이터셋 리비전: Zeroth `bd173fe2c8ed0dccd47acb4eda77542593651622`, FLEURS `70bb2e84b976b7e960aa89f1c648e09c59f894dd`.
- 미끼 용어 5개(고정): `쿠버네티스`, `그라파나`, `카산드라`, `테라폼`, `엘라스틱서치`.
- 인코딩: WebM/Opus 48kHz 모노 32kbps.
- 녹음·정답을 지어내지 않는다. S 녹음이 없으면 S 단계는 실행하지 않는다.

## Review Focus

1. 가설이 빈 문자열(VAD가 전부 잘라냄)이거나 공백·문장부호뿐 → CER 1.0, 정답 전체가 빠뜨린 말로 잡히고 오류 없이 끝나야 함.
2. 정답의 `{a|b}`에서 출력이 어느 쪽도 포함하지 않음 → 첫 번째 표기로 채점, 둘 다 포함하면 더 긴 쪽.
3. 하위 프로세스가 비정상 종료(모델 없음, 커널 OOM) → 부모가 멈추지 않고 실패를 기록하며 그때까지 쓴 JSONL 줄은 남음.
4. 정답이 NFD(macOS 입력)로 저장되거나 영문·한자가 섞임 → NFC·소문자화 뒤 같은 글자로 비교.
5. S 정답에 미끼 용어가 들어 있음 → 데이터 검사에서 거부(미끼가 "거짓 용어"로 잘못 세어지지 않게).

---

### Task 1: `run_whisper` 추출 (운영 동작 동일)

**Files:**
- Modify: `backend/app/stt.py` (`_Local.transcribe`의 `model.transcribe(...)` 블록)
- Test: `backend/tests/test_stt_eval.py` (새 파일)

**Interfaces:**
- Produces: `stt.run_whisper(model, samples, **overrides) -> tuple[str, list, object]` — (운영과 같은 `" ".join` 텍스트, 세그먼트 리스트, info). 기본 인자는 Global Constraints의 운영값, `overrides`가 덮어씀. 예외는 그대로 올림(`_Local.transcribe`가 기존처럼 `STTError("provider_error")`로 감쌈).

- [ ] **Step 1: 실패 테스트**

```python
def test_run_whisper_uses_production_defaults_and_join():
    fake = FakeModel(["  안녕하세요. ", "", "저는"])
    text, segs, info = stt.run_whisper(fake, "AUDIO")
    assert text == "안녕하세요. 저는"
    assert fake.kwargs == {"language": "ko", "task": "transcribe", "beam_size": settings.local_stt_beam_size,
                           "vad_filter": True, "condition_on_previous_text": False}
    assert [s.text for s in segs] == ["  안녕하세요. ", "", "저는"]

def test_run_whisper_overrides():
    fake = FakeModel(["a"])
    stt.run_whisper(fake, "AUDIO", beam_size=1, vad_filter=False, hotwords="x")
    assert fake.kwargs["beam_size"] == 1 and fake.kwargs["vad_filter"] is False and fake.kwargs["hotwords"] == "x"
```

`FakeModel.transcribe(audio, **kw)`는 `kw`를 저장하고 `(iter(SimpleNamespace(text=t) ...), SimpleNamespace(language_probability=1.0, duration_after_vad=1.0))`를 돌려준다(생성기를 넘겨 소비를 강제).

- [ ] **Step 2:** `cd backend && .venv/bin/python -m pytest tests/test_stt_eval.py -q` → FAIL (`run_whisper` 없음)
- [ ] **Step 3:** `run_whisper` 구현, `_Local.transcribe`가 이를 호출하도록 바꾼다(세그먼트 리스트화는 함수 안에서).
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_stt_eval.py tests/test_local_stt.py -q` → 모두 PASS(기존 25개 포함)
- [ ] **Step 5:** `git status --short -- backend/` 로 바뀐 파일 확인

### Task 2: 채점 `score.py`

**Files:**
- Create: `backend/evals/__init__.py`, `backend/evals/stt/__init__.py`, `backend/evals/stt/score.py`
- Test: `backend/tests/test_stt_eval.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str` — NFC, 소문자, 유니코드 범주 P·Z·S·C 글자 제거.
  - `sino_korean(text: str) -> str` — 숫자열(쉼표·소수점 포함)을 한자어 읽기로(`2011`→`이천십일`, `15`→`십오`, `0`→`영`, `3.5`→`삼점오`, `10000`→`만`, `100000000`→`일억`). 10·100·1000 앞의 1은 읽지 않음(`십`, `백`, `천`), 만 이상 앞의 1은 `만`만 예외.
  - `parse_reference(text: str, hyp_norm: str = "") -> Reference` — `Reference(chars: str, kinds: list[str], cuts: list[int])`; `chars`는 정규화된 정답, `kinds[i]` ∈ `word|filler|fragment`, `cuts`는 `//` 직전 글자 수(그 위치 뒤에 끊김). `{a|b}`는 `hyp_norm`에 정규화형이 들어 있는 것 중 가장 긴 것, 없으면 첫 번째. `(x)`는 filler, `단어-`의 단어는 fragment.
  - `align(ref: str, hyp: str) -> list[tuple[str, int | None, int | None]]` — op ∈ `= S D I`, 동점이면 `=`/`S` > `D` > `I`.
  - `score_clip(reference: str, hyp_text: str, numnorm: bool = False) -> ClipScore` — dataclass: `n_content, e_content, n_verbatim, e_verbatim, omitted: list[str], invented: list[str], fillers: int, fillers_kept: int, fragment_chars: int, fragment_kept: int, cuts: int, completions: list[str]`. CER_content 규칙은 스펙 5절. 구간은 5글자 이상만 목록에 넣는다.
  - `count_terms(terms: list[list[str]], hyp_text: str) -> tuple[int, int]` — (찾은 수, 전체 등장 수). 항목 하나가 한 번 등장, 같은 용어가 여러 번이면 같은 항목 반복. 찾은 수 = 용어별 min(나열 횟수, 출력 등장 횟수) 합.
  - `false_terms(prompt_terms: list[str], reference: str, hyp_text: str) -> list[str]` — 정답에 없고 출력에 있는 프롬프트 용어(정규화 비교).
  - `silence_hallucinations(segments: list[dict], silences: list[list[float]]) -> list[str]` — 길이의 절반 넘게 무음 구간과 겹치는 세그먼트의 텍스트.
  - `bootstrap_diff(clips: list[tuple[int, int, int]], iters: int = 10000, seed: int = 0) -> tuple[float, float, float]` — 입력 (정답 글자 수, A 편집 수, B 편집 수). micro CER(A) − CER(B)와 95% 구간. `random.Random(seed)`.

- [ ] **Step 1: 실패 테스트** (모두 `test_stt_eval.py`)

```python
def test_normalize_nfc_case_punct():
    assert normalize(unicodedata.normalize("NFD", "AWS에, 올렸다!")) == "aws에올렸다"

def test_sino_korean():
    assert sino_korean("2011년 8월 15미터 3.5 0 10000 120000000") == "이천십일년 팔월 십오미터 삼점오 영 만 일억이천만"

def test_cer_hand_example():
    s = score_clip("저는 백엔드를 맡았다", "저는 벡엔드 맡았다")   # 정답 9자, 치환1 + 삭제1
    assert (s.n_content, s.e_content) == (9, 2)

def test_fillers_excluded_from_content_but_not_verbatim():
    s = score_clip("(음) 저는 (어) 맡았다", "저는 맡았다")
    assert (s.n_content, s.e_content) == (5, 0) and (s.n_verbatim, s.e_verbatim) == (7, 2)
    assert (s.fillers, s.fillers_kept) == (2, 0)

def test_invented_filler_counts_as_error():
    assert score_clip("저는 맡았다", "음 저는 맡았다").e_content == 1

def test_demonstrative_not_removed():
    assert score_clip("그 프로젝트", "프로젝트").e_content == 1

def test_alternatives_pick_matching_then_first():
    assert score_clip("{3월|삼 월}에", "3월에").e_content == 0
    assert score_clip("{3월|삼 월}에", "사월에").n_content == 3   # 첫 표기 "3월에"

def test_fragment_and_cut():
    s = score_clip("프론트- 백엔드를 // 결과는", "백엔드를 했습니다 결과는")
    assert (s.fragment_chars, s.fragment_kept) == (3, 0)
    assert s.cuts == 1 and s.completions == ["했습니다"]

def test_omitted_and_invented_spans():
    s = score_clip("가나다라마바사아자차", "가나다", )
    assert s.omitted == ["라마바사아자차"]
    assert score_clip("가나", "가나 하하하하하하").invented == ["하하하하하하"]

def test_empty_hypothesis():
    s = score_clip("저는 맡았다", "  ")
    assert s.e_content == s.n_content == 5 and s.omitted == ["저는맡았다"]

def test_numnorm_symmetric():
    assert score_clip("이천십일년", "2011년", numnorm=True).e_content == 0
    assert score_clip("2011년", "이천십일년", numnorm=True).e_content == 0

def test_terms_and_false_terms():
    assert count_terms([["AWS", "에이더블유에스"], ["AWS", "에이더블유에스"], ["레디스"]], "aws에 올리고 레디스") == (2, 3)
    assert false_terms(["레디스", "테라폼"], "레디스를 썼다", "레디스 테라폼") == ["테라폼"]

def test_silence_hallucinations():
    segs = [{"start": 0, "end": 2, "text": "a"}, {"start": 10, "end": 14, "text": "b"}]
    assert silence_hallucinations(segs, [[9.0, 14.0]]) == ["b"]

def test_bootstrap_reproducible():
    clips = [(100, 10, 5), (80, 8, 8), (120, 20, 10)]
    a, b = bootstrap_diff(clips, iters=500), bootstrap_diff(clips, iters=500)
    assert a == b and a[1] <= a[0] <= a[2] and abs(a[0] - (38/300 - 23/300)) < 1e-9
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_stt_eval.py -q` → 새 테스트 FAIL(모듈 없음)
- [ ] **Step 3:** `score.py` 구현. CER_content: 간투사 포함 정답(`chars`)에 정렬, `kinds[ref_i] == "filler"`인 `S`/`D`와 간투사 글자 사이(앞뒤 글자가 모두 filler인 위치)에 끼인 `I`는 세지 않음. 문장 지어 붙이기: `cuts`의 위치 바로 다음에 이어지는 `I` 연속 구간이 2글자 이상이면 그 글자들을 원문(출력 정규화형)으로 기록.
- [ ] **Step 4:** 같은 명령 → PASS
- [ ] **Step 5:** `git status --short -- backend/`

### Task 3: 설정 `configs.py`, 데이터 `data.py`

**Files:**
- Create: `backend/evals/stt/configs.py`, `backend/evals/stt/data.py`
- Test: `backend/tests/test_stt_eval.py`

**Interfaces:**
- Consumes: `score.normalize`.
- Produces:
  - `Config(id: str, model: str, beam_size: int, vad_filter: bool, hotwords: bool, prompt: str | None)` (frozen dataclass), `CONFIGS: list[Config]` 12개(id `"{m}-default"`, `"{m}-beam1"`, `"{m}-vadoff"`, `"{m}-hot"`, `"{m}-prompt-terms"`, `"{m}-prompt-verbatim"`, m은 `base`, `small` 순), `DECOYS`, `VERBATIM_PROMPT = "음, 그러니까 제가 어, 그 프로젝트에서- 그 프로젝트에서 맡은 건요."`, `config(id) -> Config`, `overrides(cfg: Config, prompt_terms: list[str]) -> dict` — `beam_size`, `vad_filter`는 항상, `hotwords`면 `", ".join(sorted(set(prompt_terms) | set(DECOYS)))`, `prompt == "terms"`면 `initial_prompt = "다음 용어가 나올 수 있습니다: " + 같은 목록 + "."`, `"verbatim"`이면 `VERBATIM_PROMPT`.
  - `fetch_rows(dataset: str, config: str, split: str, offset: int, length: int, get=httpx.get) -> list[dict]` — datasets-server `rows`, 한 번에 최대 100.
  - `check_revision(url: str, expected: str) -> None` — 자산 주소의 `/--/<rev>/--/`가 다르면 `ValueError`.
  - `build_long(utts: list[tuple[np.ndarray, str]], target_sec: float, rate: int = 48000) -> tuple[np.ndarray, str, list[list[float]]]` — 앞 2초, 발화 사이 0.5초, 가운데 경계에 5초, 뒤 2초 이상 무음으로 정확히 `target_sec`. 들어갈 수 있는 발화만 순서대로. 반환 (int16 PCM, 정답 이어 붙인 문장, 무음 구간 [시작, 끝]초 목록, 앞·가운데·뒤 3개).
  - `encode_webm(pcm: np.ndarray, rate: int = 48000) -> bytes` — libopus 32kbps 모노.
  - `validate_spont(entries: list[dict], root: Path) -> list[str]` — 오류 문장 목록: wav 없음, `reference` 비었음, `parse_reference` 실패, 미끼 용어 포함, `clip_id` 중복, 필수 키(`clip_id, speaker, wav, reference, terms, prompt_terms`) 없음.
  - CLI `python -m evals.stt.data public --data-dir D` → `D/clips/*.webm`, `D/manifest-P.json` (`[{clip_id, set: "P-zeroth"|"P-fleurs"|"P-long", audio_sec, reference, terms, prompt_terms, silences, source: {dataset, revision, split, index, license, url}}]`), 원본 오디오 캐시 `D/raw/`. `terms`·`prompt_terms`는 `p_terms.json`(Task 6 Step 2에서 작성)이 있으면 채우고 없으면 빈 목록.
  - CLI `python -m evals.stt.data spont --data-dir D` → `D/spont/manifest.json`을 검사하고 통과하면 `D/manifest-S.json`. 실패하면 오류 목록 출력, 종료 코드 1.

- [ ] **Step 1: 실패 테스트**

```python
def test_configs_match_spec():
    assert [c.id for c in CONFIGS] == [f"{m}-{v}" for m in ("base", "small") for v in
        ("default", "beam1", "vadoff", "hot", "prompt-terms", "prompt-verbatim")]
    d = config("base-default")
    assert (d.beam_size, d.vad_filter, d.hotwords, d.prompt) == (5, True, False, None)
    assert overrides(d, ["레디스"]) == {"beam_size": 5, "vad_filter": True}
    h = overrides(config("small-hot"), ["레디스"])
    assert all(t in h["hotwords"] for t in DECOYS + ["레디스"]) and "initial_prompt" not in h

def test_check_revision():
    check_revision("https://x/cached-assets/a/b/--/abc/--/default/test/0/audio/audio.wav", "abc")
    with pytest.raises(ValueError):
        check_revision("https://x/--/zzz/--/default", "abc")

def test_build_long_exact_length_and_silences():
    utt = (np.ones(48000 * 7, dtype=np.int16), "가나")
    pcm, text, sil = build_long([utt] * 10, 60)
    assert pcm.size == 48000 * 60 and text.count("가나") == 6
    assert sil[0] == [0.0, 2.0] and sil[1][1] - sil[1][0] == pytest.approx(5.0) and sil[2][1] == 60.0

def test_encode_webm_decodes_in_production_path():
    pcm = (np.sin(np.arange(48000) / 10) * 8000).astype(np.int16)
    assert abs(stt.decode(encode_webm(pcm), 60).size - 16000) < 1600

def test_validate_spont(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    ok = {"clip_id": "s1", "speaker": "A", "wav": "a.wav", "reference": "저는 (음) 맡았다", "terms": [], "prompt_terms": []}
    assert validate_spont([ok], tmp_path) == []
    bad = [dict(ok, clip_id="s2", wav="없음.wav"), dict(ok, clip_id="s3", reference="테라폼을 썼다"), dict(ok), {"clip_id": "s4"}]
    errs = validate_spont([ok] + bad, tmp_path)
    assert len(errs) == 4   # wav 없음, 미끼 포함, 중복 id, 키 없음
```

- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현
- [ ] **Step 4:** pytest → PASS
- [ ] **Step 5:** `git status --short -- backend/`

### Task 4: 실행 `run.py`

**Files:**
- Create: `backend/evals/stt/run.py`
- Test: `backend/tests/test_stt_eval.py`

**Interfaces:**
- Consumes: `stt.run_whisper`, `stt.decode`, `stt.SILENCE_PEAK`, `stt._PROVIDERS["local"].model()`, `configs.config/overrides`.
- Produces:
  - `Guard(min_available_kb=200*1024, max_swap_growth_kb=256*1024, max_psi_full=10.0, hold_sec=2.0)` with `check(sample: dict) -> str | None` — `sample = {"t": float, "available_kb": int, "swap_used_kb": int, "psi_full_avg10": float}`; 첫 sample의 스왑을 기준으로, 조건이 `hold_sec` 넘게 연속이면 이유(`"mem_available"|"swap_growth"|"psi_full"`)를 돌려줌.
  - `read_memory() -> dict` — `/proc/meminfo`, `/proc/pressure/memory`(없으면 0.0).
  - `transcribe_clips(model, clips: list[dict], data_dir: Path, opts_for: Callable[[dict], dict], out: Path, run_meta: dict) -> None` — 클립마다 `decode`(시간), 무음이면 `text=""`·`no_speech: true`, 아니면 `run_whisper`(시간), 스펙 7절 JSONL 한 줄씩 append·flush. `out`이 이미 있으면 `FileExistsError`(호출 전 확인).
  - `child_main(args)` — 환경 변수로 모델 설정 → import 시간, 모델 로딩 시간, 로딩 직후 `VmRSS`, 5초 예열, `transcribe_clips`, 끝에 `<out>.child.json`(`import_ms, load_ms, rss_after_load_kb, hwm_kb`).
  - `run_config(cfg_id: str, set_name: str, data_dir: Path, run_id: str, threads: int = 4, repeat: int = 1, clip_ids: list[str] | None = None, guard: Guard | None = None, popen=subprocess.Popen) -> dict` — 결과 파일 `D/results/<run_id>/<cfg>-<set>-t<threads>-r<repeat>.jsonl`. 하위 프로세스 env: `STT_PROVIDER=local`, `LOCAL_STT_MODEL`, `LOCAL_STT_CPU_THREADS`, `LOCAL_STT_ALLOW_DOWNLOAD=false`, `HF_HUB_OFFLINE=1`. 0.5초마다 `read_memory`+`guard.check`, 중단 시 SIGTERM→5초→SIGKILL. 반환·`<out>.parent.json`: `{status: "ok"|"aborted"|"failed", reason, returncode, wall_ms, min_available_kb, swap_growth_kb, max_psi_some, max_psi_full}`.
  - `environment(models: list[str]) -> dict` — 스펙 6절 환경 기록(프로세스는 comm·RSS 상위 5개).
  - `probe_prompts(model, samples, **opts) -> list[dict]` — 인스턴스의 `get_prompt`를 감싸 창마다 `{"window": i, "prev_tokens": len(previous_tokens), "hotwords": bool(hotwords)}`.
  - CLI: `python -m evals.stt.run config --data-dir D --set P --config ID --run-id R [--threads N] [--repeat K] [--clips a,b]`, `... probe --data-dir D --clip ID --model base`, `... env --data-dir D --run-id R`, 내부용 `child`.

- [ ] **Step 1: 실패 테스트**

```python
def test_guard_holds_before_abort():
    g = Guard()
    base = {"available_kb": 900_000, "swap_used_kb": 800_000, "psi_full_avg10": 0.0}
    assert g.check({**base, "t": 0}) is None
    assert g.check({**base, "t": 0.5, "available_kb": 100_000}) is None
    assert g.check({**base, "t": 2.0, "available_kb": 100_000}) is None
    assert g.check({**base, "t": 2.6, "available_kb": 100_000}) == "mem_available"

def test_guard_swap_growth_and_recovery():
    g = Guard()
    g.check({"t": 0, "available_kb": 900_000, "swap_used_kb": 100_000, "psi_full_avg10": 0})
    g.check({"t": 1, "available_kb": 900_000, "swap_used_kb": 400_000, "psi_full_avg10": 0})
    g.check({"t": 2, "available_kb": 900_000, "swap_used_kb": 100_000, "psi_full_avg10": 0})   # 회복 → 다시 셈
    assert g.check({"t": 3.5, "available_kb": 900_000, "swap_used_kb": 400_000, "psi_full_avg10": 0}) is None

def test_transcribe_clips_writes_raw_text_untouched(tmp_path):
    # 실제 WebM 클립, FakeModel 세그먼트 ["  안녕하세요. ", "음… 저는"]
    ...
    row = json.loads(out.read_text().splitlines()[0])
    assert row["text"] == "안녕하세요. 음… 저는" and row["segments"][0]["text"] == "  안녕하세요. "
    assert set(row) >= {"run_id", "config", "clip_id", "set", "audio_sec", "decode_ms", "transcribe_ms", "segments", "info"}

def test_transcribe_clips_refuses_existing(tmp_path):
    out.write_text("old\n")
    with pytest.raises(FileExistsError): transcribe_clips(...)
    assert out.read_text() == "old\n"

def test_run_config_child_crash_recorded(tmp_path):
    # popen 대신 즉시 returncode 1로 끝나는 가짜 프로세스(파일에 한 줄 써 둠)
    r = run_config("base-default", "P", data_dir, "r1", popen=crashing_popen)
    assert r["status"] == "failed" and r["returncode"] == 1 and out.read_text().count("\n") == 1

def test_run_config_aborts_on_pressure(tmp_path, monkeypatch):
    # read_memory를 MemAvailable 100MB로 고정, 끝나지 않는 가짜 프로세스 → terminate 호출, status aborted, reason mem_available
```

- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현(테스트의 `...`는 Task 3 `encode_webm`으로 만든 1초 클립과 manifest 한 줄로 채운다)
- [ ] **Step 4:** pytest → PASS
- [ ] **Step 5:** `git status --short -- backend/`

### Task 5: 보고서 `report.py`, 문서, `.gitignore`

**Files:**
- Create: `backend/evals/stt/report.py`, `docs/stt-eval.md`
- Modify: `.gitignore`, `README.md`(STT 절에 평가 문서 링크 한 줄)
- Test: `backend/tests/test_stt_eval.py`

**Interfaces:**
- Consumes: `score.*`, 결과 JSONL·`.parent.json`·`.child.json`, `manifest-*.json`.
- Produces:
  - `summarize(manifest: list[dict], rows: list[dict]) -> dict` — 세트별: `n, cer_content, cer_verbatim, cer_num, cer_strict, omitted_per10, omitted_severe_per10, invented_per10, invented_severe_per10, silence_halluc, term_recall, false_terms, decoys, filler_recall, fragment_kept, completions, rtf_median, rtf_p90, sec_per_60`(P-long·S에서만), `audio_min`. 시간 정의는 스펙 5절.
  - `compare(manifest, rows_a, rows_b) -> dict` — 짝 차이, `bootstrap_diff`, 화자별(S) CER, 심각 구간 목록(사람 검토용).
  - `verdict(summary_small, summary_base, resources, has_s: bool) -> tuple[str, list[str]]` — 스펙 8절 넷 중 하나(`"대체 근거 있음"|"대체 근거 없음"|"선택 사항으로만"|"잠정"`)와 이유 목록. `has_s=False`면 항상 `"잠정"`이 앞에 붙는다(예: `"잠정: 선택 사항으로만"`).
  - CLI `python -m evals.stt.report --data-dir D --run-id R` → `D/results/R/report.md`(집계·판단), `D/results/R/clips.md`(클립별 정답·출력 대조, 로컬 전용).

- [ ] **Step 1: 실패 테스트**

```python
def test_summarize_micro_cer_and_rates():
    manifest = [{"clip_id": "a", "set": "P-zeroth", "audio_sec": 300, "reference": "가나다라마바사아자차", "terms": [], "prompt_terms": [], "silences": []},
                {"clip_id": "b", "set": "P-zeroth", "audio_sec": 300, "reference": "가나", "terms": [], "prompt_terms": [], "silences": []}]
    rows = [{"clip_id": "a", "text": "가나다", "segments": [], "transcribe_ms": 30000, "audio_sec": 300},
            {"clip_id": "b", "text": "가나", "segments": [], "transcribe_ms": 30000, "audio_sec": 300}]
    s = summarize(manifest, rows)["P-zeroth"]
    assert s["cer_content"] == pytest.approx(7 / 12) and s["omitted_per10"] == pytest.approx(1.0)
    assert s["rtf_median"] == pytest.approx(0.1)

def test_verdict_provisional_without_s():
    label, _ = verdict(good_small, base, ok_resources, has_s=False)
    assert label.startswith("잠정")

def test_verdict_critical_blocks():
    label, why = verdict(dict(good_small, invented_severe_per10=3.0), dict(base, invented_severe_per10=0.0), ok_resources, has_s=True)
    assert label == "대체 근거 없음" and any("지어낸 말" in w for w in why)

def test_verdict_resource_only_option():
    label, _ = verdict(good_small, base, dict(ok_resources, sec_per_60_t4=40.0), has_s=True)
    assert label == "선택 사항으로만"

def test_verdict_aborted_is_hardware_limit():
    label, why = verdict(None, base, {"small_status": "aborted"}, has_s=False)
    assert "하드웨어" in " ".join(why)
```

`good_small`, `base`, `ok_resources`는 테스트 안의 고정 dict(CER 0.10 vs 0.14, 심각 구간 0, 4스레드 60초 10초, 2스레드 20초, HWM 1GB, 로딩 5초).

- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현. 문서 `docs/stt-eval.md`: 준비(`data public`, `python -m app.stt download` with `LOCAL_STT_MODEL=small`), 단계 0~3 명령, 메모리 중단 의미, S 녹음·동의서 항목·정답 표기(스펙 4절 표)·`spont/manifest.json` 예시, 결과 공개 범위. `.gitignore`에 `backend/evals/stt/data/`.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → 전체 PASS(161 + 새 테스트)
- [ ] **Step 5:** `git status --short`

### Task 6: 실측 0~2단계와 기록

**Files:**
- Create: `backend/evals/stt/p_terms.json`, `docs/research/stt-eval-2026-10-30.md`
- Modify: `docs/progress.md`, `docs/decisions.md`(D-20은 "검토 대기"로만), `README.md`(필요 시 측정 요약 링크)

- [ ] **Step 1:** `data public --data-dir $D` → Expected: `manifest-P.json` 208개(zeroth 100, fleurs 100, long 8), 리비전 일치.
- [ ] **Step 2:** 정답 208개를 읽고 클립별 고유명사·전문용어를 `p_terms.json`에 적은 뒤 `data public` 재실행(캐시 사용)으로 manifest에 반영. 미끼 용어가 정답에 없는지 확인.
- [ ] **Step 3 (0단계):** `run config --set P --config base-default --run-id smoke --clips <zeroth 앞 10개>`를 `--repeat 1`, `2`로 → `report` → 두 실행 출력 동일 여부, 보고서 생성 확인.
- [ ] **Step 4 (1단계 a):** `run probe --clip <120초 P-long> --model base` → `initial_prompt`는 창 1에서만 `prev_tokens > 0`, `hotwords`는 모든 창에서 true인지 기록.
- [ ] **Step 5 (1단계 b):** `LOCAL_STT_MODEL=small .venv/bin/python -m app.stt download` → `run config --config small-default --clips <10개>` → status `ok`면 계속, `aborted`면 이유·측정값 기록하고 `small` 전체 생략.
- [ ] **Step 6 (2단계):** 백그라운드로 12개 설정 × P(정확도 1회), P-long 8개로 `base/small-default`·`-beam1` 4스레드 3회, `-default` 2스레드 3회 → `report`.
- [ ] **Step 7:** 결과를 `docs/research/stt-eval-2026-10-30.md`(P 집계·예시·출처·라이선스, 판단 "잠정", S 미실행)와 `docs/progress.md`에 쓰고, `docs/decisions.md`에 D-20 "검토 대기"를 짧게 남김. 기본값 변경 없음(`git diff -- backend/app/config.py` 비어 있음).
- [ ] **Step 8:** `pytest -q`, `cd web && npm run build` → 통과 확인, `git status --short`.
