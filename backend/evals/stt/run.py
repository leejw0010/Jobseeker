"""평가 실행(설계 6·7절). 설정 하나를 새 하위 프로세스에서 돌려 모델 로딩·추론·메모리를 따로 재고, 원본 출력을 JSONL로 남긴다.

  python -m evals.stt.run config --data-dir D --set P --config base-default --run-id R [--threads 4] [--repeat 1] [--clips a,b]
  python -m evals.stt.run probe  --data-dir D --clip long-120-4 --model base     # initial_prompt·hotwords가 창마다 들어가는지
  python -m evals.stt.run env    --data-dir D --run-id R                         # 환경 기록

메모리 압박이 이어지면 평가 하위 프로세스만 멈춘다(다른 프로세스·시스템 설정은 건드리지 않음).
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .configs import config, overrides

BACKEND_DIR = Path(__file__).resolve().parents[2]
WARMUP_SEC = 5
STT_RATE = 16000


# ───────── 메모리 감시 ─────────

class Guard:
    """조건 하나라도 hold_sec 넘게 이어지면 중단 이유를 돌려준다. 스왑 증가는 첫 표본을 기준으로 잰다."""

    def __init__(self, min_available_kb=200 * 1024, max_swap_growth_kb=256 * 1024, max_psi_full=10.0, hold_sec=2.0):
        self.min_available_kb, self.max_swap_growth_kb = min_available_kb, max_swap_growth_kb
        self.max_psi_full, self.hold_sec = max_psi_full, hold_sec
        self._swap0: int | None = None
        self._since: float | None = None

    def check(self, sample: dict) -> str | None:
        if self._swap0 is None:
            self._swap0 = sample["swap_used_kb"]
        if sample["available_kb"] < self.min_available_kb:
            reason = "mem_available"
        elif sample["swap_used_kb"] - self._swap0 > self.max_swap_growth_kb:
            reason = "swap_growth"
        elif sample["psi_full_avg10"] > self.max_psi_full:
            reason = "psi_full"
        else:
            self._since = None
            return None
        if self._since is None:
            self._since = sample["t"]
        return reason if sample["t"] - self._since > self.hold_sec else None


def _kv(path: str) -> dict[str, int]:
    out = {}
    for line in Path(path).read_text().splitlines():
        k, _, v = line.partition(":")
        if v.split():
            try:
                out[k] = int(v.split()[0])
            except ValueError:
                pass
    return out


def read_memory() -> dict:
    m = _kv("/proc/meminfo")
    psi = {"some": 0.0, "full": 0.0}
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            kind, *fields = line.split()
            psi[kind] = float(dict(f.split("=") for f in fields)["avg10"])
    except (OSError, KeyError, ValueError):
        pass  # PSI가 없는 커널
    return {"t": time.monotonic(), "available_kb": m.get("MemAvailable", 0),
            "swap_used_kb": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
            "psi_some_avg10": psi["some"], "psi_full_avg10": psi["full"]}


def wait_for_recovery(read_mem: Callable[[], dict] = read_memory, sleep: Callable[[float], None] = time.sleep,
                      max_psi_full: float = 1.0, min_available_kb: int = 500 * 1024, settle_sec: float = 10.0,
                      timeout_sec: float = 600.0, poll: float = 1.0) -> dict:
    """앞 실행이 남긴 메모리 압박이 가라앉을 때까지 기다린다(PSI full 10초 평균 ≤ 1, 여유 메모리 ≥ 500MB가 settle_sec 이어짐).
    중단 기준(Guard)은 그대로이고, 다음 실행이 앞 실행의 압박을 물려받아 바로 멈추는 일만 막는다.
    timeout_sec 안에 회복하지 않으면 recovered=False(그 실행은 시작하지 않는다)."""
    first = read_mem()
    sample, calm_since = first, None
    while True:
        calm = sample["psi_full_avg10"] <= max_psi_full and sample["available_kb"] >= min_available_kb
        calm_since = (calm_since if calm_since is not None else sample["t"]) if calm else None
        waited = round((sample["t"] - first["t"]) * 1000)
        if calm and sample["t"] - calm_since >= settle_sec:
            return {"recovered": True, "waited_ms": waited, "start": sample}
        if sample["t"] - first["t"] >= timeout_sec:
            return {"recovered": False, "waited_ms": waited, "last": sample}
        sleep(poll)
        sample = read_mem()


def proc_memory(pid: int | str = "self") -> dict:
    """VmRSS·VmHWM(kB). 프로세스가 끝났으면 빈 dict."""
    try:
        s = _kv(f"/proc/{pid}/status")
    except OSError:
        return {}
    return {"rss_kb": s.get("VmRSS"), "hwm_kb": s.get("VmHWM")}


# ───────── 전사 (하위 프로세스 안) ─────────

def transcribe_clips(model, clips: list[dict], data_dir: Path, opts_for: Callable[[dict], dict], out: Path,
                     run_meta: dict) -> None:
    """클립마다 운영 경로(stt.decode → 무음 검사 → stt.run_whisper)로 전사해 원본을 한 줄씩 남긴다. 이미 있는 결과는 덮어쓰지 않는다."""
    from app import stt
    from app.config import settings

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:  # "x": 파일이 있으면 FileExistsError
        for clip in clips:
            data = (data_dir / "clips" / f"{clip['clip_id']}.webm").read_bytes()
            t = time.perf_counter()
            samples = stt.decode(data, settings.local_stt_max_audio_sec)
            decode_ms = (time.perf_counter() - t) * 1000
            row = {**run_meta, "clip_id": clip["clip_id"], "set": clip["set"],
                   "audio_sec": round(samples.size / STT_RATE, 3), "decode_ms": round(decode_ms, 1)}
            if float(abs(samples).max()) < stt.SILENCE_PEAK:  # 운영과 같이 무음은 모델에 넣지 않는다
                row |= {"transcribe_ms": 0.0, "text": "", "segments": [], "info": None, "no_speech": True}
            else:
                t = time.perf_counter()
                text, segments, info = stt.run_whisper(model, samples, **opts_for(clip))
                row |= {
                    "transcribe_ms": round((time.perf_counter() - t) * 1000, 1), "text": text, "no_speech": False,
                    "segments": [{k: getattr(s, k, None) for k in ("start", "end", "text", "avg_logprob", "no_speech_prob",
                                                                   "compression_ratio", "temperature")} for s in segments],
                    "info": {k: getattr(info, k, None) for k in ("language_probability", "duration_after_vad")},
                }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def _load_clips(data_dir: Path, set_name: str, clip_ids: list[str] | None) -> list[dict]:
    clips = json.loads((data_dir / f"manifest-{set_name}.json").read_text(encoding="utf-8"))
    if clip_ids:
        by_id = {c["clip_id"]: c for c in clips}
        clips = [by_id[i] for i in clip_ids]
    return clips


def child_main(args) -> None:
    started = time.perf_counter()
    from app import stt  # 환경 변수(LOCAL_STT_*)는 부모가 정해 두었다
    from app.config import settings

    import_ms = (time.perf_counter() - started) * 1000
    t = time.perf_counter()
    model = stt._PROVIDERS["local"].model()  # 운영과 같은 캐시 조회·로딩
    load_ms = (time.perf_counter() - t) * 1000
    rss_after_load = proc_memory().get("rss_kb")
    cfg = config(args.config)
    clips = _load_clips(args.data_dir, args.set, args.clips.split(",") if args.clips else None)
    opts_for = lambda clip: overrides(cfg, clip.get("prompt_terms") or [])  # noqa: E731
    warm = stt.decode((args.data_dir / "clips" / f"{clips[0]['clip_id']}.webm").read_bytes(), 3600)
    t = time.perf_counter()
    stt.run_whisper(model, warm[: WARMUP_SEC * STT_RATE], **opts_for(clips[0]))
    warmup_ms = (time.perf_counter() - t) * 1000
    meta = {"run_id": args.run_id, "config": cfg.id, "model": cfg.model, "threads": args.threads, "repeat": args.repeat}
    transcribe_clips(model, clips, args.data_dir, opts_for, args.out, meta)
    summary = {"import_ms": round(import_ms, 1), "load_ms": round(load_ms, 1), "warmup_ms": round(warmup_ms, 1),
               "rss_after_load_kb": rss_after_load, **proc_memory(),
               # 실제로 쓴 STT 설정(.env가 부모가 정하지 않은 값을 바꿀 수 있어 남긴다. 비밀값 아님)
               "settings": {k: getattr(settings, k) for k in ("local_stt_model", "local_stt_device",
                                                             "local_stt_compute_type", "local_stt_cpu_threads",
                                                             "local_stt_beam_size", "local_stt_model_dir")}}
    args.out.with_name(args.out.stem + ".child.json").write_text(json.dumps(summary), encoding="utf-8")


# ───────── 부모: 하위 프로세스 실행과 감시 ─────────

def run_config(cfg_id: str, set_name: str, data_dir: Path, run_id: str, threads: int = 4, repeat: int = 1,
               clip_ids: list[str] | None = None, guard: Guard | None = None, popen=subprocess.Popen,
               read_mem: Callable[[], dict] = read_memory, poll: float = 0.5,
               recover: Callable[[], dict] | None = None) -> dict:
    """status: ok | aborted(자원 보호로 중단, reason은 Guard 이유) | not_started(자원 미회복으로 시작 안 함)
    | failed(하위 프로세스가 오류로 끝남: 모델 로딩·디코딩·추론 오류 등, .log 확인)."""
    cfg = config(cfg_id)
    out = Path(data_dir) / "results" / run_id / f"{cfg_id}-{set_name}-t{threads}-r{repeat}.jsonl"
    if out.exists():
        raise FileExistsError(out)
    other = {"P": "S", "S": "P"}.get(set_name)
    if other and any(out.parent.glob(f"*-{other}-t*-r*.parent.json")):
        raise ValueError(f"run-id {run_id}에 이미 {other} 세트 결과가 있어요. P와 S는 다른 run-id로 돌려 주세요")
    out.parent.mkdir(parents=True, exist_ok=True)
    stt_env = {"STT_PROVIDER": "local", "LOCAL_STT_MODEL": cfg.model, "LOCAL_STT_CPU_THREADS": str(threads),
               "LOCAL_STT_ALLOW_DOWNLOAD": "false", "HF_HUB_OFFLINE": "1"}
    expected = len(clip_ids) if clip_ids else len(_load_clips(Path(data_dir), set_name, None))
    base = {"config": cfg_id, "set": set_name, "threads": threads, "repeat": repeat, "env": stt_env,
            "clips_expected": expected}
    recovery = (recover or (lambda: wait_for_recovery(read_mem)))()
    if not recovery["recovered"]:
        result = {"status": "not_started", "reason": "resource_not_recovered", "returncode": None, **base,
                  "recovery": recovery, "wall_ms": 0}
        out.with_name(out.stem + ".parent.json").write_text(json.dumps(result), encoding="utf-8")
        return result
    cmd = [sys.executable, "-m", "evals.stt.run", "child", "--data-dir", str(data_dir), "--set", set_name,
           "--config", cfg_id, "--out", str(out), "--run-id", run_id, "--threads", str(threads), "--repeat", str(repeat)]
    if clip_ids:
        cmd += ["--clips", ",".join(clip_ids)]
    guard = guard or Guard()
    started = time.monotonic()
    first = read_mem()
    stats = {"min_available_kb": first["available_kb"], "swap_growth_kb": 0, "max_psi_some": first["psi_some_avg10"],
             "max_psi_full": first["psi_full_avg10"], "child_max_rss_kb": 0}
    status, reason = None, None
    with out.with_name(out.stem + ".log").open("w") as log:
        proc = popen(cmd, cwd=BACKEND_DIR, env={**os.environ, **stt_env}, stdout=log, stderr=subprocess.STDOUT)
        sample = first
        while True:
            stats["min_available_kb"] = min(stats["min_available_kb"], sample["available_kb"])
            stats["swap_growth_kb"] = max(stats["swap_growth_kb"], sample["swap_used_kb"] - first["swap_used_kb"])
            stats["max_psi_some"] = max(stats["max_psi_some"], sample["psi_some_avg10"])
            stats["max_psi_full"] = max(stats["max_psi_full"], sample["psi_full_avg10"])
            stats["child_max_rss_kb"] = max(stats["child_max_rss_kb"], proc_memory(proc.pid).get("rss_kb") or 0)
            reason = guard.check(sample)
            if reason:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                status = "aborted"
                break
            if proc.poll() is not None:
                break
            time.sleep(poll)
            sample = read_mem()
    if status is None:
        status = "ok" if proc.returncode == 0 else "failed"
    result = {"status": status, "reason": reason, "returncode": proc.returncode, **base, "recovery": recovery,
              "wall_ms": round((time.monotonic() - started) * 1000), **stats}
    out.with_name(out.stem + ".parent.json").write_text(json.dumps(result), encoding="utf-8")
    return result


# ───────── 환경 기록 ─────────

def _version(pkg: str) -> str | None:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def model_info(name: str) -> dict:
    """캐시에 있는 모델의 리비전(스냅샷 이름)과 model.bin sha256. 내려받지 않는다."""
    try:
        from faster_whisper.utils import download_model
        path = Path(download_model(name, local_files_only=True))
    except Exception:
        return {"name": name, "cached": False}
    h = hashlib.sha256()
    with (path / "model.bin").open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"name": name, "cached": True, "revision": path.name, "model_bin_sha256": h.hexdigest(),
            "model_bin_mb": round((path / "model.bin").stat().st_size / 2 ** 20, 1)}


def heavy_processes(n: int = 5) -> list[dict]:
    """RSS 상위 프로세스의 이름과 RSS만(명령줄 인자는 비밀값이 섞일 수 있어 기록하지 않음)."""
    procs = []
    for d in Path("/proc").glob("[0-9]*"):
        try:
            s = (d / "status").read_text()
        except OSError:
            continue
        fields = dict(line.split(":", 1) for line in s.splitlines() if ":" in line)
        rss = fields.get("VmRSS", "0 kB").split()[0]
        procs.append({"name": fields.get("Name", "").strip(), "rss_mb": round(int(rss) / 1024)})
    return sorted(procs, key=lambda p: -p["rss_mb"])[:n]


def environment(models: list[str]) -> dict:
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    mem = _kv("/proc/meminfo")
    return {
        "cpu": cpu, "cpu_count": os.cpu_count(), "mem_total_mb": mem.get("MemTotal", 0) // 1024,
        "swap_total_mb": mem.get("SwapTotal", 0) // 1024, "mem_available_mb": mem.get("MemAvailable", 0) // 1024,
        "swap_free_mb": mem.get("SwapFree", 0) // 1024, "loadavg": os.getloadavg(), "kernel": platform.release(),
        "os": platform.platform(), "python": platform.python_version(),
        "packages": {p: _version(p) for p in ("faster-whisper", "ctranslate2", "av", "numpy", "onnxruntime")},
        "git_commit": _git("rev-parse", "HEAD"), "git_uncommitted_files": len(_git("status", "--porcelain").splitlines()),
        "models": [model_info(m) for m in models], "heavy_processes": heavy_processes(),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ───────── 프롬프트 점검 ─────────

def probe_prompts(model, samples, **opts) -> list[dict]:
    """faster-whisper가 창(30초 디코딩 단위)마다 get_prompt에 넘기는 이전 토큰 수와 hotwords 유무를 기록한다."""
    from app import stt

    calls = []
    original = model.get_prompt

    def recording(tokenizer, previous_tokens, without_timestamps=False, prefix=None, hotwords=None):
        calls.append({"window": len(calls) + 1, "prev_tokens": len(previous_tokens), "hotwords": bool(hotwords)})
        return original(tokenizer, previous_tokens, without_timestamps=without_timestamps, prefix=prefix,
                        hotwords=hotwords)

    model.get_prompt = recording
    try:
        stt.run_whisper(model, samples, **opts)
    finally:
        del model.get_prompt
    return calls


def probe_main(args) -> None:
    os.environ.update({"STT_PROVIDER": "local", "LOCAL_STT_MODEL": args.model, "LOCAL_STT_ALLOW_DOWNLOAD": "false",
                       "HF_HUB_OFFLINE": "1"})
    from app import stt

    model = stt._PROVIDERS["local"].model()
    samples = stt.decode((args.data_dir / "clips" / f"{args.clip}.webm").read_bytes(), 3600)
    result = {"clip": args.clip, "model": args.model, "audio_sec": samples.size / STT_RATE,
              "faster_whisper": _version("faster-whisper")}
    for name, opts in (("none", {}), ("initial_prompt", {"initial_prompt": "다음 용어가 나올 수 있습니다: 테스트."}),
                       ("hotwords", {"hotwords": "테스트"})):
        result[name] = probe_prompts(model, samples, **opts)
    out = args.data_dir / "results" / f"probe-{args.model}-{args.clip}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m evals.stt.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("config", "child"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", type=Path, required=True)
        p.add_argument("--set", required=True)
        p.add_argument("--config", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--threads", type=int, default=4)
        p.add_argument("--repeat", type=int, default=1)
        p.add_argument("--clips", default="")
        if name == "child":
            p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("probe")
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--clip", required=True)
    p.add_argument("--model", default="base")
    p = sub.add_parser("env")
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--models", default="base,small")
    args = ap.parse_args(argv)
    if args.cmd == "child":
        child_main(args)
    elif args.cmd == "config":
        r = run_config(args.config, args.set, args.data_dir, args.run_id, args.threads, args.repeat,
                       args.clips.split(",") if args.clips else None)
        print(json.dumps(r))
        sys.exit({"ok": 0, "not_started": 3}.get(r["status"], 1))  # 3: 자원 미회복(배치를 멈춤)
    elif args.cmd == "probe":
        probe_main(args)
    else:
        out = args.data_dir / "results" / args.run_id / "environment.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(environment(args.models.split(",")), indent=1, ensure_ascii=False), encoding="utf-8")
        print(out)


if __name__ == "__main__":
    main()
