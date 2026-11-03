"""원본 결과(JSONL)를 채점해 보고서를 만든다(설계 5·8절). 원본은 읽기만 한다.

  python -m evals.stt.report --data-dir D --run-id R
  → D/results/R/report.md(집계·자원·판단), D/results/R/clips.md(클립별 정답·출력 대조, 로컬 전용), D/results/R/summary.json
"""
import argparse
import json
import re
import statistics
from pathlib import Path

from .configs import DECOYS
from .score import bootstrap_diff, count_terms, false_terms, score_clip, silence_hallucinations

SEVERE = 10  # 이보다 긴 빠뜨린 말·지어낸 말은 치명적 위험 후보(사람이 원문과 대조해 확인)
TARGET_ABS, TARGET_REL = 0.02, 0.15
RES_T4_SEC, RES_T2_SEC, RES_HWM_MB, RES_LOAD_S = 15.0, 30.0, 1536, 30.0
LONG_SETS = ("P-long", "S")  # 60초 답변 기준 시간을 내는 세트(운영 답변 길이)


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(q * len(s) + 0.5) - 1))]  # 최근순위(nearest-rank)


def _ratio(a: int, b: int):
    return a / b if b else None


def score_rows(manifest: list[dict], rows: list[dict]) -> list[dict]:
    """클립마다 채점 결과(정답이 manifest에 있는 줄만)."""
    by_id = {c["clip_id"]: c for c in manifest}
    out = []
    for row in rows:
        clip = by_id.get(row["clip_id"])
        if clip is None:
            continue
        ref, text = clip["reference"], row["text"]
        markup = clip.get("markup", clip["set"] == "S")  # 정답 표기(간투사 등)는 사람이 쓴 S 정답에만 있다
        sc, scn = score_clip(ref, text, markup=markup), score_clip(ref, text, numnorm=True, markup=markup)
        found, total = count_terms(clip.get("terms") or [], text)
        out.append({
            "clip": clip, "row": row, "sc": sc, "scn": scn, "terms": (found, total),
            "false_terms": false_terms(clip.get("prompt_terms") or [], ref, text),
            "decoys": false_terms(DECOYS, ref, text),
            "silence": silence_hallucinations(row.get("segments") or [], clip.get("silences") or []),
            "rtf": row["transcribe_ms"] / 1000 / row["audio_sec"] if row.get("audio_sec") else None,
        })
    return out


def _summary(scored: list[dict]) -> dict:
    sc = [s["sc"] for s in scored]
    minutes = sum(s["clip"]["audio_sec"] for s in scored) / 60
    per10 = lambda n: n / (minutes / 10) if minutes else None  # noqa: E731
    spans = lambda key, lo: sum(len(x) >= lo for c in sc for x in getattr(c, key))  # noqa: E731
    n_content = sum(c.n_content for c in sc)
    rtf = [s["rtf"] for s in scored if s["rtf"] is not None and not s["row"].get("no_speech")]
    long_rtf = [s["rtf"] for s in scored if s["clip"]["set"] in LONG_SETS and s["rtf"] is not None]
    fillers = sum(c.fillers for c in sc)
    frag = sum(c.fragment_chars for c in sc)
    return {
        "n": len(scored), "audio_min": round(minutes, 2),
        "cer_content": _ratio(sum(c.e_content for c in sc), n_content),
        "cer_verbatim": _ratio(sum(c.e_verbatim for c in sc), sum(c.n_verbatim for c in sc)),
        "cer_num": _ratio(sum(s["scn"].e_content for s in scored), sum(s["scn"].n_content for s in scored)),
        "omitted_per10": per10(spans("omitted", 5)), "omitted_severe_per10": per10(spans("omitted", SEVERE)),
        "invented_per10": per10(spans("invented", 5)), "invented_severe_per10": per10(spans("invented", SEVERE)),
        "silence_halluc": sum(len(s["silence"]) for s in scored),
        "term_recall": _ratio(sum(s["terms"][0] for s in scored), sum(s["terms"][1] for s in scored)),
        "false_terms": sum(len(s["false_terms"]) for s in scored), "decoys": sum(len(s["decoys"]) for s in scored),
        "filler_recall": _ratio(sum(c.fillers_kept for c in sc), fillers) if fillers else None,
        "fragment_kept": _ratio(sum(c.fragment_kept for c in sc), frag) if frag else None,
        "cuts": sum(c.cuts for c in sc), "completions": sum(len(c.completions) for c in sc),
        "no_speech": sum(bool(s["row"].get("no_speech")) for s in scored),
        "rtf_median": statistics.median(rtf) if rtf else None, "rtf_p90": _pct(rtf, 0.9),
        "sec_per_60": statistics.median(long_rtf) * 60 if long_rtf else None,
    }


def summarize(manifest: list[dict], rows: list[dict]) -> dict:
    """세트별 집계와, P 세트를 모두 합친 "P"."""
    scored = score_rows(manifest, rows)
    sets = sorted({s["clip"]["set"] for s in scored})
    out = {name: _summary([s for s in scored if s["clip"]["set"] == name]) for name in sets}
    p = [s for s in scored if s["clip"]["set"].startswith("P-")]
    if p:
        out["P"] = _summary(p)
    return out


def compare(manifest: list[dict], rows_a: list[dict], rows_b: list[dict], numnorm_p: bool = True) -> dict:
    """A − B 짝 비교(같은 클립). P는 숫자 정규화 CER, S는 CER_content. 화자별 CER(A, B)."""
    a = {s["row"]["clip_id"]: s for s in score_rows(manifest, rows_a)}
    b = {s["row"]["clip_id"]: s for s in score_rows(manifest, rows_b)}
    groups: dict[str, list[str]] = {}
    for cid in a.keys() & b.keys():
        groups.setdefault(a[cid]["clip"]["set"], []).append(cid)
    if any(k.startswith("P-") for k in groups):
        groups["P"] = [c for k, v in groups.items() if k.startswith("P-") for c in v]
    out = {}
    for name, cids in groups.items():
        key = "scn" if numnorm_p and name.startswith("P") else "sc"
        trip = [(a[c][key].n_content, a[c][key].e_content, b[c][key].e_content) for c in sorted(cids)]
        diff, lo, hi = bootstrap_diff(trip)
        speakers = {}
        for c in cids:
            spk = a[c]["clip"].get("speaker")
            if spk:
                n, ea, eb = speakers.get(spk, (0, 0, 0))
                speakers[spk] = (n + a[c][key].n_content, ea + a[c][key].e_content, eb + b[c][key].e_content)
        out[name] = {"n": len(cids), "diff": diff, "ci95": (lo, hi),
                     "speakers": {k: (v[1] / v[0], v[2] / v[0]) for k, v in sorted(speakers.items()) if v[0]}}
    return out


def verdict(small: dict | None, base: dict, resources: dict, has_s: bool, metric: str = "cer_content") -> tuple[str, list[str]]:
    """설계 8절의 자동 판정과 이유. 치명적 위험 후보는 사람이 원문과 대조해 확인해야 한다(이 판정은 그 전 단계)."""
    why = []
    status = resources.get("small_status", "ok")
    if small is None or status != "ok":
        if status == "aborted":
            why.append("small 측정이 메모리 압박으로 중단됨: 이 하드웨어(메모리)에서는 측정 불가 — 하드웨어 한계")
        elif status == "failed":
            why.append("small 측정이 오류로 끝남(로그 확인 필요)")
        else:
            why.append("small을 측정하지 않음")
        label = "대체 근거 없음"
    else:
        critical = [(k, name) for k, name in (("invented_severe_per10", "심각한 지어낸 말(10글자 이상, 10분당)"),
                                              ("omitted_severe_per10", "10글자 이상 빠뜨린 말(10분당)"),
                                              ("silence_halluc", "무음 구간에서 지어낸 말"),
                                              ("completions", "끊긴 문장 지어 붙이기"))
                    if (small.get(k) or 0) > (base.get(k) or 0)]
        for k, name in critical:
            why.append(f"치명적 위험 후보: {name} small {small[k]:.2f} > base {base[k]:.2f} (원문 대조 필요)")
        if small.get("decoys"):
            why.append(f"치명적 위험: 미끼 용어 {small['decoys']}회 출력")
        gain = base[metric] - small[metric]
        rel = gain / base[metric] if base[metric] else 0.0
        met = gain >= TARGET_ABS and rel >= TARGET_REL
        why.append(f"정확도 {metric}: base {base[metric]:.4f} → small {small[metric]:.4f} "
                   f"(절대 {gain * 100:+.2f}%p, 상대 {rel * 100:+.1f}%) — 목표(2.0%p·15%) {'달성' if met else '미달'}")
        res_fail = [name for ok, name in (
            ((resources.get("sec_per_60_t4") or 1e9) <= RES_T4_SEC, f"4스레드 60초 답변 ≤ {RES_T4_SEC:.0f}초"),
            ((resources.get("sec_per_60_t2") or 1e9) <= RES_T2_SEC, f"2스레드 60초 답변 ≤ {RES_T2_SEC:.0f}초"),
            ((resources.get("hwm_mb") or 1e9) <= RES_HWM_MB, f"프로세스 최대 메모리 ≤ {RES_HWM_MB}MB"),
            ((resources.get("load_s") or 1e9) <= RES_LOAD_S, f"첫 로딩 ≤ {RES_LOAD_S:.0f}초")) if not ok]
        for name in res_fail:
            why.append(f"자원 목표 미달: {name}")
        if critical or small.get("decoys") or not met:
            label = "대체 근거 없음"
        elif res_fail:
            label = "선택 사항으로만"
        else:
            label = "대체 근거 있음"
    if not has_s:
        why.append("S(자연스러운 면접 답변) 측정 없음: P(낭독)만으로 본 잠정 판단. S 측정 전까지 기본값을 바꾸지 않는다")
        label = f"잠정: {label}"
    return label, why


# ───────── 결과 읽기와 보고서 ─────────

CATEGORY_LABEL = {"ok": "완료", "guard_aborted": "자원 보호로 중단", "not_started": "자원 미회복으로 시작 안 함",
                  "failed": "프로그램·추론 오류", "missing": "기록 없음"}
_STEM = re.compile(r"^(?P<cfg>.+)-(?P<set>[A-Z])-t(?P<threads>\d+)-r(?P<repeat>\d+)$")


def run_category(parent: dict) -> str:
    """실행 결과 분류. 자원 보호 중단·미시작은 이 기계의 메모리 상태 때문이고, 모델 추론 실패(failed)와 따로 센다."""
    return {"ok": "ok", "aborted": "guard_aborted", "not_started": "not_started",
            "failed": "failed"}.get(parent.get("status"), "missing")


ACCURACY_SETS = ("P", "S")  # L(30초 지연 보충)은 지연 표에만 쓰고 정확도·판단에는 넣지 않는다


def accuracy_runs(results: dict) -> tuple[dict, dict]:
    """정확도 비교에 쓰는 4스레드 1회차 실행: (끝까지 마친 것, 도중에 멈췄지만 끝낸 클립이 있는 것), 설정 id별.
    도중에 멈춘 실행은 클립 수가 달라 같은 표에서 비교하면 안 되므로 따로 돌려준다. 한 run-id에는 P나 S 하나만 있다."""
    t4r1 = {m["cfg"]: r for stem, r in results.items()
            if (m := _STEM.match(stem)) and m["set"] in ACCURACY_SETS and m["threads"] == "4" and m["repeat"] == "1"}
    done = {cfg: r for cfg, r in t4r1.items() if run_category(r["parent"]) == "ok"}
    partial = {cfg: r for cfg, r in t4r1.items() if run_category(r["parent"]) != "ok" and r["rows"]}
    return done, partial


def load_results(run_dir: Path) -> dict[str, dict]:
    """실행(<config>-<set>-t<threads>-r<repeat>)별 원본 줄과 부모·자식 기록. 시작하지 않은 실행은 부모 기록만 있다."""
    stems = sorted({f.name[: -len(".jsonl")] for f in run_dir.glob("*.jsonl")}
                   | {f.name[: -len(".parent.json")] for f in run_dir.glob("*.parent.json")})
    out = {}
    for stem in stems:
        read = lambda suffix: json.loads(p.read_text()) if (p := run_dir / f"{stem}{suffix}").exists() else {}  # noqa: E731
        f = run_dir / f"{stem}.jsonl"
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
        out[stem] = {"rows": rows, "parent": read(".parent.json"), "child": read(".child.json")}
    return out


def _status_lines(results: dict) -> list[str]:
    counts = {k: 0 for k in CATEGORY_LABEL}
    rows = []
    for stem, r in results.items():
        p = r["parent"]
        cat = run_category(p)
        counts[cat] += 1
        detail = {"guard_aborted": p.get("reason"), "not_started": p.get("reason"),
                  "failed": f"returncode {p.get('returncode')}"}.get(cat, "")
        waited = (p.get("recovery") or {}).get("waited_ms")
        rows.append(f"| {stem} | {CATEGORY_LABEL[cat]} | {detail} | {len(r['rows'])}/{p.get('clips_expected', '?')} | "
                    f"{_fmt(p.get('wall_ms', 0) / 1000, nd=1)}초 | {_fmt(waited / 1000 if waited is not None else None, nd=0)}초 |")
    return ["## 실행 상태", "", " · ".join(f"{CATEGORY_LABEL[k]} {v}" for k, v in counts.items() if k != "missing" or v), "",
            "자원 보호로 중단·자원 미회복으로 시작 안 함은 모델 추론이 실패한 것이 아니라, 이 기계의 메모리 상태 때문에 안전하게 멈춘 것이다. "
            "그 실행의 수치는 측정값이 아니다(일부 클립만 끝났으면 아래 '미완료 실행의 부분 결과'에만 둔다). "
            "프로그램·추론 오류는 `.log`를 확인한다.", "",
            "| 실행 | 분류 | 사유 | 끝낸 클립 | 실행 시간 | 시작 전 대기 |", "|---|---|---|---|---|---|", *rows, ""]


def _fmt(v, pct=False, nd=2):
    if v is None:
        return "–"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def _resources(results: dict, model: str, manifest: list[dict]) -> dict:
    """모델별 자원: 4·2스레드 60초 답변 기준 시간(P-long·S의 중앙 RTF × 60, 반복 포함), 로딩, 최대 메모리, 압박."""
    long_ids = {c["clip_id"] for c in manifest if c["set"] in LONG_SETS}
    statuses, rtf = [], {4: [], 2: []}
    loads, hwm, rss_load, min_avail, swap, psi = [], [], [], [], [], []
    for stem, r in results.items():
        if not stem.startswith(f"{model}-"):
            continue
        p, c = r["parent"], r["child"]
        statuses.append(p.get("status", "missing"))
        if c.get("load_ms") is not None:
            loads.append(c["load_ms"] / 1000)
        for k, dst in (("hwm_kb", hwm), ("rss_after_load_kb", rss_load)):
            if c.get(k):
                dst.append(c[k] / 1024)
        if p:
            min_avail.append(p["min_available_kb"] / 1024)
            swap.append(p["swap_growth_kb"] / 1024)
            psi.append(p["max_psi_full"])
        if stem.startswith(f"{model}-default-") and p.get("threads") in rtf:
            rtf[p["threads"]] += [x["transcribe_ms"] / 1000 / x["audio_sec"] for x in r["rows"] if x["clip_id"] in long_ids]
    status = next((s for s in ("aborted", "failed", "not_started") if s in statuses), "ok" if statuses else "missing")
    return {"small_status" if model == "small" else "status": status, "runs": len(statuses),
            "sec_per_60_t4": statistics.median(rtf[4]) * 60 if rtf[4] else None,
            "sec_per_60_t4_p90": _pct(rtf[4], 0.9) * 60 if rtf[4] else None,
            "sec_per_60_t2": statistics.median(rtf[2]) * 60 if rtf[2] else None,
            "load_s": max(loads) if loads else None, "load_s_median": statistics.median(loads) if loads else None,
            "hwm_mb": max(hwm) if hwm else None, "rss_after_load_mb": max(rss_load) if rss_load else None,
            "min_available_mb": min(min_avail) if min_avail else None, "swap_growth_mb": max(swap) if swap else None,
            "max_psi_full": max(psi) if psi else None}


def latency_by_length(rows: list[dict], min_sec: float = 25.0) -> dict[int, dict]:
    """녹음 길이(30초 단위로 반올림)별 1건 지연 = decode + transcribe(모델을 불러 둔 뒤). 짧은 낭독 클립은 넣지 않는다."""
    buckets: dict[int, list[float]] = {}
    for r in rows:
        if r.get("audio_sec", 0) >= min_sec and not r.get("no_speech"):
            buckets.setdefault(int(round(r["audio_sec"] / 30) * 30), []).append((r.get("decode_ms", 0) + r["transcribe_ms"]) / 1000)
    return {k: {"n": len(v), "median_s": statistics.median(v), "p95_s": _pct(v, 0.95), "max_s": max(v)}
            for k, v in sorted(buckets.items())}


def _latency_lines(results: dict) -> list[str]:
    lines = ["## 녹음 1건 지연 (모델을 불러 둔 뒤 decode + 전사, default 설정, 반복 포함)", "",
             "| 모델 | 스레드 | 길이 | 건수 | 중앙 | p95 | 최대 |", "|---|---|---|---|---|---|---|"]
    for m in ("base", "small"):
        for t in (4, 2):
            rows = [x for stem, r in results.items() if stem.startswith(f"{m}-default-") and f"-t{t}-" in stem
                    for x in r["rows"]]
            for sec, v in latency_by_length(rows).items():
                lines.append(f"| {m} | {t} | {sec}초 | {v['n']} | {v['median_s']:.1f}초 | {v['p95_s']:.1f}초 | {v['max_s']:.1f}초 |")
    lines += ["", "p95는 최근순위 방식이라 건수가 20개 미만이면 사실상 최댓값이다.", "", "## 벤치마크 전체 실행 시간 (프로세스 시작·모델 로딩·예열 포함)", "",
              "| 모델 | 실행 수 | 합계 | 실행당 중앙 |", "|---|---|---|---|"]
    for m in ("base", "small"):
        walls = [r["parent"]["wall_ms"] / 60000 for stem, r in results.items() if stem.startswith(f"{m}-") and "wall_ms" in r["parent"]]
        if walls:
            lines.append(f"| {m} | {len(walls)} | {sum(walls):.1f}분 | {statistics.median(walls):.1f}분 |")
    return lines + [""]


def _repeat_diffs(results: dict) -> list[str]:
    lines = []
    for stem, r in results.items():
        if not stem.endswith("-r1"):
            continue
        first = {x["clip_id"]: x["text"] for x in r["rows"]}
        for k in range(2, 10):
            other = results.get(stem[:-1] + str(k))
            if not other:
                break
            same = [first.get(x["clip_id"]) == x["text"] for x in other["rows"] if x["clip_id"] in first]
            lines.append(f"- `{stem[:-3]}` r{k}: {len(same) - sum(same)}/{len(same)}개 클립의 출력이 r1과 다름")
    return lines


def build_report(data_dir: Path, run_id: str) -> str:
    run_dir = data_dir / "results" / run_id
    manifest = []
    for name in ("P", "S", "L"):
        f = data_dir / f"manifest-{name}.json"
        if f.exists():
            manifest += json.loads(f.read_text(encoding="utf-8"))
    results = load_results(run_dir)
    # 주 평가 세트는 이 run-id가 실제로 돌린 세트로 정한다(manifest는 S를 준비만 해 둔 경우에도 있다. P·S는 run-id를 나눈다)
    has_s = any((m := _STEM.match(stem)) and m["set"] == "S" for stem in results)
    accuracy, partial = accuracy_runs(results)
    lines = [f"# STT 평가 보고서 — {run_id}", ""]
    env_file = run_dir / "environment.json"
    if env_file.exists():
        env = json.loads(env_file.read_text(encoding="utf-8"))
        lines += ["## 환경", "", f"- CPU: {env['cpu']} ({env['cpu_count']} 논리 코어), RAM {env['mem_total_mb']}MB, "
                  f"스왑 {env['swap_total_mb']}MB, 시작 시 여유 {env['mem_available_mb']}MB·스왑 여유 {env['swap_free_mb']}MB, "
                  f"load {tuple(round(x, 2) for x in env['loadavg'])}",
                  f"- {env['os']}, Python {env['python']}, " + ", ".join(f"{k} {v}" for k, v in env["packages"].items()),
                  f"- git {env['git_commit'][:8]} (미커밋 파일 {env['git_uncommitted_files']}개)",
                  *[f"- 모델 {m['name']}: " + (f"리비전 {m['revision'][:8]}, model.bin {m['model_bin_mb']}MB sha256 "
                                              f"{m['model_bin_sha256'][:16]}…" if m["cached"] else "캐시에 없음")
                    for m in env["models"]],
                  "- 함께 돌던 프로세스(RSS): " + ", ".join(f"{p['name']} {p['rss_mb']}MB" for p in env["heavy_processes"]), ""]
    lines += _status_lines(results)
    summaries = {cfg: summarize(manifest, r["rows"]) for cfg, r in accuracy.items()}
    set_names = sorted({k for s in summaries.values() for k in s}, key=lambda k: (k != "P", k))
    cols = [("CER_content", "cer_content", True), ("CER_verbatim", "cer_verbatim", True), ("CER_num", "cer_num", True),
            ("빠뜨린 말/10분 (≥5·≥10)", None, False), ("지어낸 말/10분 (≥5·≥10)", None, False),
            ("무음 지어냄", "silence_halluc", False), ("용어 재현율", "term_recall", True), ("거짓 용어", "false_terms", False),
            ("미끼", "decoys", False), ("간투사", "filler_recall", True), ("말 고침", "fragment_kept", True),
            ("지어 붙이기", "completions", False), ("RTF 중앙", "rtf_median", False), ("상태", None, False)]
    lines += ["## 정확도 (설정별, 4스레드 1회)", ""]
    for set_name in set_names:
        lines += [f"### {set_name}", "", "| 설정 | " + " | ".join(c[0] for c in cols) + " |",
                  "|---|" + "---|" * len(cols)]
        for cfg, s in summaries.items():
            if set_name not in s:
                continue
            v = s[set_name]
            status = accuracy[cfg]["parent"].get("status", "–")
            cells = []
            for title, key, pct in cols:
                if title.startswith("빠뜨린"):
                    cells.append(f"{_fmt(v['omitted_per10'])}·{_fmt(v['omitted_severe_per10'])}")
                elif title.startswith("지어낸"):
                    cells.append(f"{_fmt(v['invented_per10'])}·{_fmt(v['invented_severe_per10'])}")
                elif title == "상태":
                    cells.append(status)
                else:
                    cells.append(_fmt(v[key], pct=pct, nd=3))
            lines.append(f"| {cfg} | " + " | ".join(cells) + " |")
        n = next(iter(s[set_name]["n"] for s in summaries.values() if set_name in s), 0)
        minutes = next(iter(s[set_name]["audio_min"] for s in summaries.values() if set_name in s), 0)
        lines += ["", f"클립 {n}개, {minutes}분.", ""]
    if partial:
        lines += ["## 미완료 실행의 부분 결과", "",
                  "도중에 멈춘 실행이 끝낸 클립만 채점했다. 측정 조건(클립 수·종류)이 달라 위 표와 비교하지 말고, base와는 같은 클립끼리만 본다.", "",
                  "| 설정 | 끝낸 클립 | CER_num | 같은 클립의 base-default CER_num | 클립당 지연 중앙 | 같은 클립 base 지연 중앙 | 분류 |",
                  "|---|---|---|---|---|---|---|"]
        base_rows = {x["clip_id"]: x for x in accuracy.get("base-default", {}).get("rows", [])}
        for cfg, r in partial.items():
            ids = {x["clip_id"] for x in r["rows"]}
            mine = summarize(manifest, r["rows"]).get("P") or next(iter(summarize(manifest, r["rows"]).values()), {})
            paired = [base_rows[i] for i in ids if i in base_rows]
            theirs = (summarize(manifest, paired).get("P") or {}) if paired else {}
            lat = lambda rows: statistics.median([(x.get("decode_ms", 0) + x["transcribe_ms"]) / 1000 for x in rows]) if rows else None  # noqa: E731
            lines.append(f"| {cfg} | {len(r['rows'])}/{r['parent'].get('clips_expected', '?')} | {_fmt(mine.get('cer_num'), pct=True)} | "
                         f"{_fmt(theirs.get('cer_num'), pct=True)} | {_fmt(lat(r['rows']), nd=1)}초 | {_fmt(lat(paired), nd=1)}초 | "
                         f"{CATEGORY_LABEL[run_category(r['parent'])]} |")
        lines.append("")
    res = {m: _resources(results, m, manifest) for m in ("base", "small")}
    lines += ["## 자원", "", "| 모델 | 상태 | 60초 답변 4스레드(중앙·p90) | 2스레드 | 최대/중앙 로딩 | 로딩 직후 RSS | 최대 RSS(VmHWM) | "
              "최소 MemAvailable | 스왑 증가 | PSI full 최대 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, r in res.items():
        st = r.get("small_status", r.get("status"))
        lines.append(f"| {m} | {st} ({r['runs']}회 실행) | {_fmt(r['sec_per_60_t4'], nd=1)}초·{_fmt(r['sec_per_60_t4_p90'], nd=1)}초 | "
                     f"{_fmt(r['sec_per_60_t2'], nd=1)}초 | {_fmt(r['load_s'], nd=1)}·{_fmt(r['load_s_median'], nd=1)}초 | "
                     f"{_fmt(r['rss_after_load_mb'], nd=0)}MB | {_fmt(r['hwm_mb'], nd=0)}MB | {_fmt(r['min_available_mb'], nd=0)}MB | "
                     f"{_fmt(r['swap_growth_mb'], nd=0)}MB | {_fmt(r['max_psi_full'])} |")
    lines += ["", "60초 답변 기준 시간 = P-long·S 클립의 전사 RTF 중앙값 × 60(예열 뒤, 반복 실행 포함). 로딩은 새 프로세스 기준이며 "
              "OS 디스크 캐시 상태는 통제하지 않음.", ""]
    lines += _latency_lines(results)
    diffs = _repeat_diffs(results)
    if diffs:
        lines += ["## 반복 실행 출력 일치", "", *diffs, ""]
    a, b = accuracy.get("small-default"), accuracy.get("base-default")
    a_partial = a is None and "small-default" in partial
    if a_partial:
        a = partial["small-default"]
    if b:
        cmp = compare(manifest, a["rows"], b["rows"]) if a else {}
        heading = "## small − base (default끼리, 짝 비교)"
        if a_partial:
            n = len({x["clip_id"] for x in a["rows"]} & {x["clip_id"] for x in b["rows"]})
            heading += f" — 부분 결과: small이 멈추기 전까지 끝낸 같은 클립 {n}개만"
        lines += [heading, ""]
        for name, c in sorted(cmp.items()):
            lines.append(f"- {name}: CER 차이 {c['diff'] * 100:+.2f}%p, 부트스트랩 95% [{c['ci95'][0] * 100:+.2f}, "
                         f"{c['ci95'][1] * 100:+.2f}]%p (클립 {c['n']}개, 음수면 small이 나음)")
            for spk, (ca, cb) in c["speakers"].items():
                lines.append(f"  - 화자 {spk}: small {ca * 100:.1f}% / base {cb * 100:.1f}%")
        primary = "S" if has_s else "P"
        metric = "cer_content" if has_s else "cer_num"
        small_sum = summaries.get("small-default", {}).get(primary) if a and res["small"]["small_status"] == "ok" else None
        label, why = verdict(small_sum, summaries["base-default"][primary], res["small"], has_s, metric=metric)
        lines += ["", "## 판단 (자동, 사람 검토 전)", "", f"**{label}**", "", *[f"- {w}" for w in why], ""]
        lines += ["## 치명적 위험 후보 (원문 대조용)", ""]
        for cfg in ("base-default", "small-default"):
            r = accuracy.get(cfg)
            if not r:
                continue
            for s in score_rows(manifest, r["rows"]):
                items = [f"빠뜨림 「{x}」" for x in s["sc"].omitted if len(x) >= SEVERE]
                items += [f"지어냄 「{x}」" for x in s["sc"].invented if len(x) >= SEVERE]
                items += [f"무음 「{x}」" for x in s["silence"]] + [f"지어 붙임 「{x}」" for x in s["sc"].completions]
                if items:
                    lines.append(f"- {cfg} `{s['clip']['clip_id']}`: " + " · ".join(items))
        lines.append("")
    (run_dir / "summary.json").write_text(json.dumps({"summaries": summaries, "resources": res,
                                                      "statuses": {k: run_category(r["parent"]) for k, r in results.items()}},
                                                     ensure_ascii=False,
                                                     indent=1, default=str), encoding="utf-8")
    _write_clips(run_dir, manifest, accuracy)
    return "\n".join(lines)


def _write_clips(run_dir: Path, manifest: list[dict], accuracy: dict) -> None:
    """클립별 정답과 default 출력 대조(로컬 전용 — S 녹음의 내용이 들어 있을 수 있어 커밋하지 않는다)."""
    texts = {cfg: {x["clip_id"]: x["text"] for x in r["rows"]} for cfg, r in accuracy.items()}
    lines = ["# 클립별 대조 (로컬 전용)", ""]
    for c in manifest:
        lines += [f"## {c['clip_id']} ({c['set']}, {c['audio_sec']}초)", "", f"- 정답: {c['reference']}"]
        for cfg in ("base-default", "small-default"):
            if c["clip_id"] in texts.get(cfg, {}):
                t = texts[cfg][c["clip_id"]]
                s = score_clip(c["reference"], t, numnorm=c["set"].startswith("P"), markup=c["set"] == "S")
                lines.append(f"- {cfg} (CER {_fmt(_ratio(s.e_content, s.n_content), pct=True)}): {t}")
        lines.append("")
    (run_dir / "clips.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m evals.stt.report")
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    text = build_report(args.data_dir, args.run_id)
    out = args.data_dir / "results" / args.run_id / "report.md"
    out.write_text(text, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
