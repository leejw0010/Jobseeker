"""STT 평가 도구(backend/evals/stt). 실제 모델 없이 채점·설정·데이터 준비·실행 기록·보고서를 검사한다.

실제 모델로 잰 결과는 docs/research/stt-eval-2026-10-30.md.
"""
from types import SimpleNamespace

from app import stt
from app.config import settings


class FakeModel:
    """faster-whisper WhisperModel 흉내. 받은 인자를 기록하고 세그먼트를 생성기로 돌려준다(끝까지 소비해야 함)."""

    def __init__(self, texts):
        self.texts = texts
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        segs = (SimpleNamespace(text=t, start=i * 2.0, end=i * 2.0 + 1.5, avg_logprob=-0.2, no_speech_prob=0.01,
                                compression_ratio=1.1, temperature=0.0) for i, t in enumerate(self.texts))
        return segs, SimpleNamespace(language_probability=0.99, duration_after_vad=3.0)


# ───────── run_whisper (운영 경로 공유) ─────────

def test_run_whisper_uses_production_defaults_and_join():
    fake = FakeModel(["  안녕하세요. ", "", "저는"])
    text, segs, info = stt.run_whisper(fake, "AUDIO")
    assert text == "안녕하세요. 저는"
    assert fake.kwargs == {"language": "ko", "task": "transcribe", "beam_size": settings.local_stt_beam_size,
                           "vad_filter": True, "condition_on_previous_text": False}
    assert [s.text for s in segs] == ["  안녕하세요. ", "", "저는"]
    assert info.duration_after_vad == 3.0


def test_run_whisper_overrides():
    fake = FakeModel(["a"])
    stt.run_whisper(fake, "AUDIO", beam_size=1, vad_filter=False, hotwords="x")
    assert fake.kwargs["beam_size"] == 1 and fake.kwargs["vad_filter"] is False and fake.kwargs["hotwords"] == "x"
    assert fake.kwargs["language"] == "ko" and fake.kwargs["condition_on_previous_text"] is False


# ───────── 채점 score.py ─────────

import unicodedata  # noqa: E402

from evals.stt.score import (bootstrap_diff, count_terms, false_terms, normalize, score_clip,  # noqa: E402
                             silence_hallucinations, sino_korean)


def test_normalize_nfc_case_punct():
    assert normalize(unicodedata.normalize("NFD", "AWS에, 올렸다!")) == "aws에올렸다"


def test_sino_korean():
    assert sino_korean("2011년 8월 15미터 3.5 0 10000 120000000") == "이천십일년 팔월 십오미터 삼점오 영 만 일억이천만"
    assert sino_korean("1,200원 101 1000") == "천이백원 백일 천"


def test_cer_hand_example():
    s = score_clip("저는 백엔드를 맡았다", "저는 벡엔드 맡았다")  # 정답 9자, 치환 1 + 삭제 1
    assert (s.n_content, s.e_content) == (9, 2)


def test_fillers_excluded_from_content_but_not_verbatim():
    s = score_clip("(음) 저는 (어) 맡았다", "저는 맡았다")
    assert (s.n_content, s.e_content) == (5, 0) and (s.n_verbatim, s.e_verbatim) == (7, 2)
    assert (s.fillers, s.fillers_kept) == (2, 0)
    kept = score_clip("(음) 저는 맡았다", "음 저는 맡았다")
    assert (kept.fillers_kept, kept.e_content, kept.e_verbatim) == (1, 0, 0)


def test_invented_filler_counts_as_error():
    assert score_clip("저는 맡았다", "음 저는 맡았다").e_content == 1


def test_demonstrative_not_removed():
    assert score_clip("그 프로젝트", "프로젝트").e_content == 1


def test_alternatives_pick_matching_then_first():
    assert score_clip("{3월|삼 월}에", "3월에").e_content == 0
    assert score_clip("{3월|삼 월}에", "삼 월에").e_content == 0
    assert score_clip("{3월|삼 월}에", "사월에").n_content == 3  # 어느 쪽도 없으면 첫 표기 "3월에"


def test_fragment_and_cut():
    s = score_clip("프론트- 백엔드를 // 결과는", "백엔드를 했습니다 결과는")
    assert (s.fragment_chars, s.fragment_kept) == (3, 0)
    assert s.cuts == 1 and s.completions == ["했습니다"]
    assert score_clip("백엔드를 // 결과는", "백엔드를 결과는").completions == []


def test_omitted_and_invented_spans():
    s = score_clip("가나다라마바사아자차", "가나다")
    assert s.omitted == ["라마바사아자차"]
    assert score_clip("가나", "가나 하하하하하하").invented == ["하하하하하하"]
    assert score_clip("가나다라", "가나").omitted == []  # 5글자 미만은 목록에 넣지 않음


def test_empty_hypothesis():
    s = score_clip("저는 맡았다", "  ")
    assert s.e_content == s.n_content == 5 and s.omitted == ["저는맡았다"]
    assert score_clip("저는 맡았다", "…?!").e_content == 5


def test_numnorm_symmetric():
    assert score_clip("이천십일년", "2011년", numnorm=True).e_content == 0
    assert score_clip("2011년", "이천십일년", numnorm=True).e_content == 0
    assert score_clip("이천십일년", "2011년").e_content > 0


def test_mixed_scripts_and_nfd_reference():
    ref = unicodedata.normalize("NFD", "API를 漢字로")
    assert score_clip(ref, "api를 漢字로").e_content == 0


def test_terms_and_false_terms():
    assert count_terms([["AWS", "에이더블유에스"], ["AWS", "에이더블유에스"], ["레디스"]], "aws에 올리고 레디스") == (2, 3)
    assert count_terms([], "아무거나") == (0, 0)
    assert false_terms(["레디스", "테라폼"], "레디스를 썼다", "레디스 테라폼") == ["테라폼"]


def test_silence_hallucinations():
    segs = [{"start": 0, "end": 2, "text": "a"}, {"start": 10, "end": 14, "text": "b"}, {"start": 8, "end": 10, "text": "c"}]
    assert silence_hallucinations(segs, [[9.0, 14.0]]) == ["b"]


def test_bootstrap_reproducible():
    clips = [(100, 10, 5), (80, 8, 8), (120, 20, 10)]
    a, b = bootstrap_diff(clips, iters=500), bootstrap_diff(clips, iters=500)
    assert a == b and a[1] <= a[0] <= a[2] and abs(a[0] - (38 / 300 - 23 / 300)) < 1e-9


def test_cut_marker_attached_to_word_and_slash_in_word():
    assert score_clip("백엔드를// 결과는", "백엔드를 했습니다 결과는").completions == ["했습니다"]
    assert score_clip("TCP/IP를", "tcp ip를").e_content == 0


# ───────── 설정 configs.py · 데이터 data.py ─────────

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from evals.stt.configs import CONFIGS, DECOYS, config, overrides  # noqa: E402
from evals.stt.data import build_long, check_revision, encode_webm, validate_spont  # noqa: E402


def test_configs_match_spec():
    assert [c.id for c in CONFIGS] == [f"{m}-{v}" for m in ("base", "small") for v in
                                       ("default", "beam1", "vadoff", "hot", "prompt-terms", "prompt-verbatim")]
    d = config("base-default")
    assert (d.model, d.beam_size, d.vad_filter, d.hotwords, d.prompt) == ("base", 5, True, False, None)
    assert overrides(d, ["레디스"]) == {"beam_size": 5, "vad_filter": True}
    assert overrides(config("small-beam1"), [])["beam_size"] == 1
    assert overrides(config("base-vadoff"), [])["vad_filter"] is False
    h = overrides(config("small-hot"), ["레디스"])
    assert all(t in h["hotwords"] for t in DECOYS + ["레디스"]) and "initial_prompt" not in h
    p = overrides(config("base-prompt-terms"), ["레디스"])
    assert all(t in p["initial_prompt"] for t in DECOYS + ["레디스"]) and "hotwords" not in p
    v = overrides(config("base-prompt-verbatim"), ["레디스"])
    assert "레디스" not in v["initial_prompt"] and "음" in v["initial_prompt"]


def test_check_revision():
    check_revision("https://x/cached-assets/a/b/--/abc/--/default/test/0/audio/audio.wav", "abc")
    with pytest.raises(ValueError):
        check_revision("https://x/--/zzz/--/default", "abc")
    with pytest.raises(ValueError):
        check_revision("https://x/no-revision.wav", "abc")


def test_build_long_exact_length_and_silences():
    utt = (np.ones(48000 * 7, dtype=np.int16), "가나")
    pcm, text, sil = build_long([utt] * 10, 60)
    assert pcm.size == 48000 * 60 and text.count("가나") == 6
    assert sil[0] == [0.0, 2.0] and sil[1][1] - sil[1][0] == pytest.approx(5.0) and sil[2][1] == 60.0
    assert pcm[: 48000 * 2].max() == 0 and pcm[48000 * 2] == 1   # 앞 2초 무음 뒤 발화
    s, e = (int(x * 48000) for x in sil[1])
    assert pcm[s:e].max() == 0


def test_encode_webm_decodes_in_production_path():
    pcm = (np.sin(np.arange(48000) / 10) * 8000).astype(np.int16)
    assert abs(stt.decode(encode_webm(pcm), 60).size - 16000) < 1600


def test_validate_spont(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    ok = {"clip_id": "s1", "speaker": "A", "audio": "a.wav", "reference": "저는 (음) 맡았다", "terms": [], "prompt_terms": []}
    assert validate_spont([ok], tmp_path) == []
    bad = [dict(ok, clip_id="s2", audio="없음.wav"), dict(ok, clip_id="s3", reference="테라폼을 썼다"), dict(ok),
           {"clip_id": "s4"}, dict(ok, clip_id="s5", reference="(음 저는"), dict(ok, clip_id="s6", reference="  (음) ")]
    errs = validate_spont([ok] + bad, tmp_path)
    assert len(errs) == 6, errs  # 파일 없음, 미끼 포함, 중복 id, 키 없음, 괄호 짝, 내용 없음


# ───────── 실행 run.py ─────────

import json  # noqa: E402

from evals.stt.run import Guard, probe_prompts, run_config, transcribe_clips  # noqa: E402


def test_guard_holds_before_abort():
    g = Guard()
    base = {"available_kb": 900_000, "swap_used_kb": 800_000, "psi_full_avg10": 0.0}
    assert g.check({**base, "t": 0}) is None
    assert g.check({**base, "t": 0.5, "available_kb": 100_000}) is None
    assert g.check({**base, "t": 2.0, "available_kb": 100_000}) is None
    assert g.check({**base, "t": 2.6, "available_kb": 100_000}) == "mem_available"


def test_guard_swap_growth_psi_and_recovery():
    g = Guard()
    ok = {"available_kb": 900_000, "swap_used_kb": 100_000, "psi_full_avg10": 0.0}
    g.check({**ok, "t": 0})
    g.check({**ok, "t": 1, "swap_used_kb": 400_000})
    g.check({**ok, "t": 2})  # 회복 → 처음부터 다시 셈
    assert g.check({**ok, "t": 3.5, "swap_used_kb": 400_000}) is None
    assert g.check({**ok, "t": 5.6, "swap_used_kb": 400_000}) == "swap_growth"
    p = Guard()
    p.check({**ok, "t": 0, "psi_full_avg10": 30.0})
    assert p.check({**ok, "t": 2.5, "psi_full_avg10": 30.0}) == "psi_full"


def _clip_dir(tmp_path):
    from evals.stt.data import encode_webm
    (tmp_path / "clips").mkdir()
    pcm = (np.sin(np.arange(48000) / 10) * 8000).astype(np.int16)
    (tmp_path / "clips" / "c1.webm").write_bytes(encode_webm(pcm))
    (tmp_path / "clips" / "quiet.webm").write_bytes(encode_webm(np.zeros(48000, np.int16)))
    clips = [{"clip_id": "c1", "set": "P-zeroth", "prompt_terms": []}, {"clip_id": "quiet", "set": "P-zeroth", "prompt_terms": []}]
    (tmp_path / "manifest-P.json").write_text(json.dumps(clips), encoding="utf-8")
    return clips


def test_transcribe_clips_writes_raw_text_untouched(tmp_path):
    clips = _clip_dir(tmp_path)
    out = tmp_path / "r" / "x.jsonl"
    fake = FakeModel(["  안녕하세요. ", "음… 저는"])
    transcribe_clips(fake, clips, tmp_path, lambda c: {"beam_size": 1}, out, {"run_id": "r", "config": "base-beam1"})
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["text"] == "안녕하세요. 음… 저는" and rows[0]["segments"][0]["text"] == "  안녕하세요. "
    assert set(rows[0]) >= {"run_id", "config", "clip_id", "set", "audio_sec", "decode_ms", "transcribe_ms", "segments", "info"}
    assert fake.kwargs["beam_size"] == 1 and fake.kwargs["language"] == "ko"
    assert rows[1]["clip_id"] == "quiet" and rows[1]["text"] == "" and rows[1]["no_speech"] is True


def test_transcribe_clips_refuses_existing(tmp_path):
    clips = _clip_dir(tmp_path)
    out = tmp_path / "x.jsonl"
    out.write_text("old\n")
    with pytest.raises(FileExistsError):
        transcribe_clips(FakeModel(["a"]), clips, tmp_path, lambda c: {}, out, {})
    assert out.read_text() == "old\n"


class FakeProc:
    def __init__(self, returncode_after=None, on_start=None):
        self.pid, self.returncode, self._rc, self.signals = 999999, None, returncode_after, []
        if on_start:
            on_start()

    def poll(self):
        if self._rc is not None:
            self.returncode = self._rc
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise __import__("subprocess").TimeoutExpired("x", timeout)
        return self.returncode

    def terminate(self):
        self.signals.append("TERM")

    def kill(self):
        self.signals.append("KILL")
        self.returncode = -9


def _mem(avail_kb):
    t = iter(range(10_000))
    return lambda: {"t": float(next(t)), "available_kb": avail_kb, "swap_used_kb": 0, "psi_some_avg10": 0.0,
                    "psi_full_avg10": 0.0}


CALM = lambda: {"recovered": True, "waited_ms": 0}  # noqa: E731  (실행 전 회복 대기를 건너뛰는 테스트용)


def test_run_config_child_crash_recorded(tmp_path):
    _clip_dir(tmp_path)
    out = tmp_path / "results" / "r1" / "base-default-P-t4-r1.jsonl"
    started = []

    def popen(cmd, **kw):
        started.append((cmd, kw["env"]))
        out.write_text('{"clip_id": "c1"}\n')  # 죽기 전에 쓴 줄은 남아야 한다
        return FakeProc(returncode_after=1)

    r = run_config("base-default", "P", tmp_path, "r1", popen=popen, read_mem=_mem(900_000), poll=0, recover=CALM)
    assert r["status"] == "failed" and r["returncode"] == 1 and out.read_text().count("\n") == 1
    cmd, env = started[0]
    assert env["LOCAL_STT_MODEL"] == "base" and env["LOCAL_STT_CPU_THREADS"] == "4"
    assert env["LOCAL_STT_ALLOW_DOWNLOAD"] == "false" and env["HF_HUB_OFFLINE"] == "1" and env["STT_PROVIDER"] == "local"
    assert json.loads(out.with_name("base-default-P-t4-r1.parent.json").read_text())["status"] == "failed"
    with pytest.raises(FileExistsError):
        run_config("base-default", "P", tmp_path, "r1", popen=popen, read_mem=_mem(900_000), poll=0, recover=CALM)


def test_run_config_aborts_on_pressure(tmp_path):
    _clip_dir(tmp_path)
    procs = []

    def popen(cmd, **kw):
        procs.append(FakeProc())  # 스스로 끝나지 않는 프로세스
        return procs[-1]

    r = run_config("small-default", "P", tmp_path, "r2", popen=popen, read_mem=_mem(100_000), poll=0, recover=CALM)
    assert r["status"] == "aborted" and r["reason"] == "mem_available" and procs[0].signals == ["TERM", "KILL"]
    assert r["min_available_kb"] == 100_000


def test_probe_prompts_records_windows_and_restores():
    class ProbeModel(FakeModel):
        def get_prompt(self, tokenizer, previous_tokens, without_timestamps=False, prefix=None, hotwords=None):
            return [0]

        def transcribe(self, audio, **kwargs):
            self.get_prompt(None, [1, 2, 3], hotwords=kwargs.get("hotwords"))
            self.get_prompt(None, [], hotwords=kwargs.get("hotwords"))
            return super().transcribe(audio, **kwargs)

    m = ProbeModel(["a"])
    assert probe_prompts(m, "AUDIO", hotwords="x") == [{"window": 1, "prev_tokens": 3, "hotwords": True},
                                                        {"window": 2, "prev_tokens": 0, "hotwords": True}]
    assert "get_prompt" not in vars(m)


# ───────── 보고서 report.py ─────────

from evals.stt.report import compare, summarize, verdict  # noqa: E402


def _m(cid, ref, sec=300, set_name="P-zeroth", **kw):
    return {"clip_id": cid, "set": set_name, "audio_sec": sec, "reference": ref, "terms": [], "prompt_terms": [],
            "silences": [], **kw}


def _r(cid, text, ms=30000, sec=300, segments=()):
    return {"clip_id": cid, "text": text, "segments": list(segments), "transcribe_ms": ms, "audio_sec": sec}


def test_summarize_micro_cer_and_rates():
    manifest = [_m("a", "가나다라마바사아자차"), _m("b", "가나")]
    s = summarize(manifest, [_r("a", "가나다"), _r("b", "가나")])["P-zeroth"]
    assert s["cer_content"] == pytest.approx(7 / 12) and s["omitted_per10"] == pytest.approx(1.0)
    assert s["omitted_severe_per10"] == 0 and s["rtf_median"] == pytest.approx(0.1) and s["n"] == 2


def test_summarize_numbers_terms_decoys_silence_and_combined_p():
    manifest = [_m("a", "이천십일년 레디스", terms=[["레디스"]], prompt_terms=["레디스"]),
                _m("b", "가나", set_name="P-long", silences=[[0, 2]])]
    rows = [_r("a", "2011년 레디스 테라폼"), _r("b", "가나 감사합니다", segments=[{"start": 0, "end": 1.5, "text": "감사합니다"}])]
    out = summarize(manifest, rows)
    a = out["P-zeroth"]
    assert a["cer_num"] < a["cer_content"] and a["term_recall"] == 1.0 and a["decoys"] == 1
    assert out["P-long"]["silence_halluc"] == 1 and out["P"]["n"] == 2
    assert a["filler_recall"] is None  # 낭독 세트는 N/A


def test_compare_paired_and_speakers():
    manifest = [_m("a", "가나다라", set_name="S", speaker="A"), _m("b", "가나다라", set_name="S", speaker="B")]
    c = compare(manifest, [_r("a", "가나"), _r("b", "가나다라")], [_r("a", "가나다라"), _r("b", "가나다라")])["S"]
    assert c["diff"] == pytest.approx(2 / 8) and c["speakers"]["A"] == (0.5, 0.0) and c["speakers"]["B"] == (0.0, 0.0)


GOOD_SMALL = {"cer_content": 0.10, "invented_severe_per10": 0.0, "omitted_severe_per10": 0.0, "completions": 0,
              "silence_halluc": 0, "decoys": 0}
BASE = dict(GOOD_SMALL, cer_content=0.14)
OK_RES = {"small_status": "ok", "sec_per_60_t4": 10.0, "sec_per_60_t2": 20.0, "hwm_mb": 1000, "load_s": 5.0}


def test_verdict_replace_when_all_met():
    assert verdict(GOOD_SMALL, BASE, OK_RES, has_s=True)[0] == "대체 근거 있음"


def test_verdict_provisional_without_s():
    label, _ = verdict(GOOD_SMALL, BASE, OK_RES, has_s=False)
    assert label.startswith("잠정")


def test_verdict_critical_blocks():
    label, why = verdict(dict(GOOD_SMALL, invented_severe_per10=3.0), BASE, OK_RES, has_s=True)
    assert label == "대체 근거 없음" and any("지어낸 말" in w for w in why)


def test_verdict_accuracy_target_missed():
    label, why = verdict(dict(GOOD_SMALL, cer_content=0.13), BASE, OK_RES, has_s=True)
    assert label == "대체 근거 없음" and any("목표" in w for w in why)


def test_verdict_resource_only_option():
    assert verdict(GOOD_SMALL, BASE, dict(OK_RES, sec_per_60_t4=40.0), has_s=True)[0] == "선택 사항으로만"


def test_verdict_aborted_is_hardware_limit():
    label, why = verdict(None, BASE, {"small_status": "aborted"}, has_s=False)
    assert label.startswith("잠정") and "하드웨어" in " ".join(why)


def test_build_report_end_to_end(tmp_path):
    from evals.stt.report import build_report
    manifest = [_m("zeroth-000", "가나다라마바사"), _m("long-60-0", "가나다라 마바사", sec=60, set_name="P-long", silences=[[0, 2]])]
    (tmp_path / "manifest-P.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "results" / "r"
    run.mkdir(parents=True)
    for cfg, texts, ms in (("base-default", ["가나다라마바", "가나다라 마바사"], 6000), ("small-default", ["가나다라마바사", "가나다라 마바사"], 9000)):
        stem = f"{cfg}-P-t4-r1"
        rows = [dict(_r(c["clip_id"], t, ms=ms, sec=c["audio_sec"]), config=cfg) for c, t in zip(manifest, texts)]
        (run / f"{stem}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        (run / f"{stem}.parent.json").write_text(json.dumps({"status": "ok", "threads": 4, "min_available_kb": 500_000,
                                                             "swap_growth_kb": 0, "max_psi_full": 0.0}))
        (run / f"{stem}.child.json").write_text(json.dumps({"load_ms": 2000, "hwm_kb": 600_000, "rss_after_load_kb": 400_000}))
    text = build_report(tmp_path, "r")
    assert "## 판단" in text and "**잠정:" in text and "small − base" in text
    assert (run / "clips.md").read_text(encoding="utf-8").count("## ") == 2 and (run / "summary.json").exists()


def test_build_report_p_run_ignores_a_prepared_s_manifest(tmp_path):
    """S 세트를 준비해 둔 채 P만 돌린 run-id(P·S는 run-id를 나눈다)도 P 결과로 판단한다(S 요약을 찾지 않는다)."""
    from evals.stt.report import build_report
    manifest = [_m("zeroth-000", "가나다라마바사")]
    (tmp_path / "manifest-P.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "manifest-S.json").write_text(json.dumps([_m("spont-000", "준비만 한 자유 발화", set_name="S")],
                                                         ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "results" / "p-only"
    run.mkdir(parents=True)
    for cfg, text, ms in (("base-default", "가나다라마바", 6000), ("small-default", "가나다라마바사", 9000)):
        stem = f"{cfg}-P-t4-r1"
        rows = [dict(_r("zeroth-000", text, ms=ms, sec=manifest[0]["audio_sec"]), config=cfg)]
        (run / f"{stem}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        (run / f"{stem}.parent.json").write_text(json.dumps({"status": "ok", "threads": 4, "min_available_kb": 500_000,
                                                             "swap_growth_kb": 0, "max_psi_full": 0.0}))
        (run / f"{stem}.child.json").write_text(json.dumps({"load_ms": 2000, "hwm_kb": 600_000, "rss_after_load_kb": 400_000}))
    text = build_report(tmp_path, "p-only")
    assert "## 판단" in text and "**잠정:" in text  # S가 없는 실행의 판단은 잠정


def test_fetch_rows_retries_server_errors_then_pages():
    import httpx
    from evals.stt.data import fetch_rows
    calls = []

    def get(url, params, timeout):
        calls.append(params["offset"])
        req = httpx.Request("GET", url)
        if len(calls) == 1:
            return httpx.Response(502, request=req)
        return httpx.Response(200, json={"rows": [{"row": {"i": params["offset"] + k}} for k in range(params["length"])]},
                              request=req)

    rows = fetch_rows("d", "c", "test", 0, 150, get=get, wait=0)
    assert [r["i"] for r in rows] == list(range(150)) and calls == [0, 0, 100]


def test_public_references_scored_without_markup():
    ref = "깁슨(Gibson)은 1~3마리 // {a|b}"
    plain = score_clip(ref, "깁슨gibson은 1 3마리 ab", markup=False)
    assert plain.e_content == 0 and plain.fillers == 0 and plain.cuts == 0
    assert score_clip(ref, "깁슨은 1 3마리 a").fillers == 1  # S 표기로 읽으면 (Gibson)은 간투사
    manifest = [_m("f", "깁슨(Gibson)은 갔다", set_name="P-fleurs"), _m("s", "(음) 저는", set_name="S")]
    out = summarize(manifest, [_r("f", "깁슨gibson은 갔다"), _r("s", "저는")])
    assert out["P-fleurs"]["cer_content"] == 0 and out["S"]["cer_content"] == 0 and out["S"]["filler_recall"] == 0


def test_verdict_missing_small_is_not_called_hardware_limit():
    label, why = verdict(None, BASE, {"small_status": "missing"}, has_s=True)
    assert label == "대체 근거 없음" and "하드웨어" not in " ".join(why) and any("측정하지 않음" in w for w in why)


def test_latency_by_length_buckets_and_percentiles():
    from evals.stt.report import latency_by_length
    rows = [{"audio_sec": 60.0, "decode_ms": 100, "transcribe_ms": ms} for ms in (4900, 5900, 6900, 7900, 8900)]
    rows += [{"audio_sec": 30.0, "decode_ms": 50, "transcribe_ms": 2950}, {"audio_sec": 6.2, "decode_ms": 10, "transcribe_ms": 900}]
    out = latency_by_length(rows)
    assert set(out) == {30, 60}  # 25초 미만 클립은 넣지 않음
    assert out[60]["n"] == 5 and out[60]["median_s"] == pytest.approx(7.0) and out[60]["p95_s"] == pytest.approx(9.0)
    assert out[30]["median_s"] == pytest.approx(3.0)


def test_latency_set_kept_out_of_public_accuracy():
    manifest = [_m("a", "가나", set_name="P-zeroth"), _m("l", "가나", sec=30, set_name="L-30")]
    out = summarize(manifest, [_r("a", "가나"), _r("l", "가")])
    assert out["P"]["n"] == 1 and out["L-30"]["n"] == 1


# ───────── 실행 사이 자원 회복 대기 ─────────

from evals.stt.run import wait_for_recovery  # noqa: E402


def _seq(samples):
    it = iter(samples)
    return lambda: next(it)


def _calm(t, avail=900_000, psi=0.0):
    return {"t": float(t), "available_kb": avail, "swap_used_kb": 0, "psi_some_avg10": psi, "psi_full_avg10": psi}


def test_wait_for_recovery_needs_a_calm_streak():
    # 0~4초는 압박(PSI full 15), 5초부터 잠잠 → 10초 연속 잠잠한 15초에 회복
    samples = [_calm(t, psi=15.0) for t in range(5)] + [_calm(t) for t in range(5, 40)]
    r = wait_for_recovery(read_mem=_seq(samples), sleep=lambda s: None)
    assert r["recovered"] is True and r["waited_ms"] == 15000 and r["start"]["psi_full_avg10"] == 0.0


def test_wait_for_recovery_resets_streak_and_checks_memory():
    samples = [_calm(t) for t in range(8)] + [_calm(8, avail=300_000)] + [_calm(t) for t in range(9, 40)]
    assert wait_for_recovery(read_mem=_seq(samples), sleep=lambda s: None)["waited_ms"] == 19000


def test_wait_for_recovery_times_out():
    samples = [_calm(t, psi=20.0) for t in range(0, 700)]
    r = wait_for_recovery(read_mem=_seq(samples), sleep=lambda s: None, timeout_sec=60)
    assert r["recovered"] is False and r["waited_ms"] >= 60000 and r["last"]["psi_full_avg10"] == 20.0


def test_run_config_not_started_when_resources_do_not_recover(tmp_path):
    _clip_dir(tmp_path)
    started = []
    r = run_config("small-default", "P", tmp_path, "r3", popen=lambda *a, **k: started.append(1),
                   read_mem=_mem(900_000), poll=0, recover=lambda: {"recovered": False, "waited_ms": 600000})
    out = tmp_path / "results" / "r3" / "small-default-P-t4-r1.jsonl"
    assert r["status"] == "not_started" and r["reason"] == "resource_not_recovered" and started == []
    assert not out.exists()  # 결과 줄이 없으니 다시 돌릴 때 이 실행을 건너뛰지 않는다
    assert json.loads(out.with_name("small-default-P-t4-r1.parent.json").read_text())["status"] == "not_started"


def test_run_config_records_recovery_and_expected_clips(tmp_path):
    _clip_dir(tmp_path)
    r = run_config("base-default", "P", tmp_path, "r4", popen=lambda *a, **k: FakeProc(returncode_after=0),
                   read_mem=_mem(900_000), poll=0, recover=lambda: {"recovered": True, "waited_ms": 12000})
    assert r["status"] == "ok" and r["recovery"]["waited_ms"] == 12000 and r["clips_expected"] == 2


# ───────── 30초 지연 클립 구성(L-30) ─────────

from evals.stt.data import L_LAYOUT, build_packed, pack_utterances  # noqa: E402


def test_pack_utterances_skips_what_does_not_fit_without_cutting():
    # 예산 = 30 − 앞 0.5 − 뒤 최소 0.5 = 29초. 12 + 0.5 + 14 = 26.5, 10은 넘침, 5도 넘침(32) → 0, 1만
    assert pack_utterances([12, 14, 10, 5], 30) == [0, 1]
    assert pack_utterances([31, 8, 9], 30) == [1, 2]  # 예산보다 긴 발화는 자르지 않고 건너뜀


def test_build_packed_exact_length_whole_utterances_and_composition():
    rate = 48000
    utts = [(np.full(int(12 * rate), 1, np.int16), "가"), (np.full(int(14 * rate), 2, np.int16), "나"),
            (np.full(int(10 * rate), 3, np.int16), "다")]
    pcm, text, silences, used, comp = build_packed(utts, 30)
    assert pcm.size == 30 * rate and text == "가 나" and used == [0, 1]
    assert (pcm == 1).sum() == 12 * rate and (pcm == 2).sum() == 14 * rate  # 발화는 하나도 잘리지 않음
    assert pcm[: int(0.5 * rate)].max() == 0 and pcm[int(0.5 * rate)] == 1
    assert comp == {"lead_sec": 0.5, "gap_sec": 0.5, "gaps": 1, "trail_sec": 3.0, "speech_sec": 26.0,
                    "silence_sec": 4.0, "utterances": 2}
    assert silences == [[0.0, 0.5], [27.0, 30.0]] and L_LAYOUT == {"lead": 0.5, "gap": 0.5, "trail_min": 0.5}


def test_build_packed_refuses_mostly_silent_clip():
    utts = [(np.ones(48000 * 10, np.int16), "가")]  # 10초 / 30초 < 75%
    with pytest.raises(ValueError):
        build_packed(utts, 30)


# ───────── 보고서: 실행 상태 구분 ─────────

def test_run_category_separates_guard_aborts_from_failures():
    from evals.stt.report import run_category
    assert run_category({"status": "ok", "returncode": 0}) == "ok"
    assert run_category({"status": "aborted", "reason": "psi_full", "returncode": -15}) == "guard_aborted"
    assert run_category({"status": "not_started", "reason": "resource_not_recovered"}) == "not_started"
    assert run_category({"status": "failed", "returncode": 1}) == "failed"
    assert run_category({}) == "missing"


def test_build_report_lists_run_statuses_and_keeps_partial_runs_out_of_main_table(tmp_path):
    from evals.stt.report import build_report
    manifest = [_m("zeroth-000", "가나다라마바사"), _m("zeroth-001", "아자차카타파하")]
    (tmp_path / "manifest-P.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "results" / "r"
    run.mkdir(parents=True)

    def put(stem, parent, rows=None, child=None):
        if rows is not None:
            (run / f"{stem}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        (run / f"{stem}.parent.json").write_text(json.dumps({"threads": 4, "min_available_kb": 500_000, "swap_growth_kb": 0,
                                                             "max_psi_full": 0.0, "wall_ms": 1000, "clips_expected": 2, **parent}))
        if child:
            (run / f"{stem}.child.json").write_text(json.dumps(child))

    put("base-default-P-t4-r1", {"status": "ok", "returncode": 0}, [_r("zeroth-000", "가나다라마바"), _r("zeroth-001", "아자차카타파하")],
        {"load_ms": 1000, "hwm_kb": 400_000})
    put("small-default-P-t4-r1", {"status": "aborted", "reason": "swap_growth", "returncode": -15}, [_r("zeroth-000", "가나다라마바사")])
    put("base-beam1-P-t4-r1", {"status": "failed", "returncode": 1}, [])
    put("small-beam1-P-t4-r1", {"status": "not_started", "reason": "resource_not_recovered", "returncode": None, "wall_ms": 0})
    text = build_report(tmp_path, "r")
    status = text.split("## 실행 상태")[1].split("\n## ")[0]
    assert "완료 1" in status and "자원 보호로 중단 1" in status and "자원 미회복으로 시작 안 함 1" in status
    assert "프로그램·추론 오류 1" in status and "small-default-P-t4-r1 | 자원 보호로 중단 | swap_growth | 1/2" in status
    main = text.split("## 정확도")[1].split("\n## ")[0]
    assert "| base-default |" in main and "| small-default |" not in main
    partial = text.split("## 미완료 실행의 부분 결과")[1].split("\n## ")[0]
    assert "| small-default | 1/2 |" in partial
    assert "같은 클립 1개" in text and "하드웨어 한계" in text


def test_latency_set_runs_never_enter_accuracy_or_verdict(tmp_path):
    from evals.stt.report import build_report
    manifest_p = [_m("zeroth-000", "가나다라마바사")]
    manifest_l = [_m("lat-30-0", "아자차카타파하", sec=30, set_name="L-30")]
    (tmp_path / "manifest-P.json").write_text(json.dumps(manifest_p, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "manifest-L.json").write_text(json.dumps(manifest_l, ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "results" / "r"
    run.mkdir(parents=True)
    for stem, rows in (("base-default-P-t4-r1", [_r("zeroth-000", "가나다라마바사")]),
                       ("base-default-L-t4-r1", [_r("lat-30-0", "엉뚱한 전사", ms=2000, sec=30.0)])):
        (run / f"{stem}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        (run / f"{stem}.parent.json").write_text(json.dumps({"status": "ok", "returncode": 0, "threads": 4, "wall_ms": 1000,
                                                             "min_available_kb": 1, "swap_growth_kb": 0, "max_psi_full": 0.0}))
    text = build_report(tmp_path, "r")
    main = text.split("## 정확도")[1].split("\n## ")[0]
    assert "### P" in main and "L-30" not in main  # L-30은 지연 전용
    assert "| base | 4 | 30초 | 1 |" in text  # 지연 표에는 들어간다


def test_accuracy_runs_ignore_latency_only_set():
    from evals.stt.report import accuracy_runs
    ok = {"status": "ok", "returncode": 0}
    results = {"base-default-L-t4-r1": {"rows": [{"clip_id": "lat-30-0"}], "parent": ok, "child": {}}}
    assert accuracy_runs(results) == ({}, {})  # (끝까지 마친 실행, 미완료 실행) 모두 비어 있음
    results["base-default-P-t4-r1"] = {"rows": [{"clip_id": "z"}], "parent": ok, "child": {}}
    results["small-default-P-t4-r1"] = {"rows": [{"clip_id": "z"}], "parent": {"status": "aborted"}, "child": {}}
    done, partial = accuracy_runs(results)
    assert list(done) == ["base-default"] and list(partial) == ["small-default"]


def test_run_config_refuses_to_mix_p_and_s_in_one_run_id(tmp_path):
    clips = _clip_dir(tmp_path)
    (tmp_path / "manifest-S.json").write_text(json.dumps([dict(c, set="S") for c in clips]), encoding="utf-8")
    proc = lambda *a, **k: FakeProc(returncode_after=0)  # noqa: E731
    run_config("base-default", "P", tmp_path, "r5", popen=proc, read_mem=_mem(900_000), poll=0, recover=CALM)
    with pytest.raises(ValueError):
        run_config("base-default", "S", tmp_path, "r5", popen=proc, read_mem=_mem(900_000), poll=0, recover=CALM)
    run_config("base-default", "S", tmp_path, "r6", popen=proc, read_mem=_mem(900_000), poll=0, recover=CALM)  # 다른 run-id는 됨
