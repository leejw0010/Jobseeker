"""평가 데이터 준비(설계 3절). 데이터와 결과는 저장소 밖 --data-dir에 둔다.

  python -m evals.stt.data public --data-dir D   # P: Zeroth-Korean·FLEURS ko_kr 받기 → D/clips/*.webm, D/manifest-P.json
  python -m evals.stt.data spont --data-dir D    # S: D/spont/manifest.json 검사 → D/clips/*.webm, D/manifest-S.json

S 녹음·정답은 사람이 준비한다(docs/stt-eval.md). 이 모듈은 없는 녹음이나 정답을 만들지 않는다.
"""
import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import av
import httpx
import numpy as np

from .configs import DECOYS
from .score import normalize, parse_reference

RATE = 48000  # 브라우저 MediaRecorder와 같은 48kHz 모노 Opus로 인코딩한다
OPUS_BITRATE = 32000
ROWS_API = "https://datasets-server.huggingface.co/rows"
TERMS_FILE = Path(__file__).with_name("p_terms.json")

PUBLIC = {
    "zeroth": {"dataset": "Bingsu/zeroth-korean", "config": "default", "split": "test",
               "revision": "bd173fe2c8ed0dccd47acb4eda77542593651622", "license": "CC BY 4.0", "text": "text",
               "url": "https://huggingface.co/datasets/Bingsu/zeroth-korean"},
    "fleurs": {"dataset": "google/fleurs", "config": "ko_kr", "split": "test",
               "revision": "70bb2e84b976b7e960aa89f1c648e09c59f894dd", "license": "CC BY 4.0",
               "text": "raw_transcription", "url": "https://huggingface.co/datasets/google/fleurs"},
}
N_SHORT = 100  # 세트마다 데이터셋 순서로 앞 100개
LONG_TARGETS = [60, 60, 60, 60, 120, 120, 120, 120]  # P-long: Zeroth 100번째부터 이어 붙임
LONG_POOL = 200
REQUIRED = ("clip_id", "speaker", "audio", "reference", "terms", "prompt_terms")


# ───────── 받기 ─────────

def fetch_rows(dataset: str, config: str, split: str, offset: int, length: int, get=httpx.get,
               wait: float = 5.0) -> list[dict]:
    """Hugging Face datasets-server의 rows API(한 번에 최대 100행). 일시적인 5xx는 세 번까지 다시 묻는다."""
    rows = []
    while length > 0:
        n = min(100, length)
        params = {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": n}
        for attempt in range(4):
            r = get(ROWS_API, params=params, timeout=60)
            if r.status_code < 500 or attempt == 3:
                break
            time.sleep(wait * (attempt + 1))
        r.raise_for_status()
        rows += [x["row"] for x in r.json()["rows"]]
        offset, length = offset + n, length - n
    return rows


def check_revision(url: str, expected: str) -> None:
    """자산 주소의 /--/<리비전>/--/가 기대한 리비전과 다르면 멈춘다(다른 판의 데이터를 섞지 않기 위해)."""
    m = re.search(r"/--/([0-9a-f]+)/--/", url)
    if not m or m.group(1) != expected:
        raise ValueError(f"데이터셋 리비전이 다릅니다: {m.group(1) if m else '없음'} (기대 {expected})")


# ───────── 오디오 ─────────

def load_pcm(data: bytes) -> np.ndarray:
    """오디오 파일 → 48kHz 모노 int16."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    parts = []
    with av.open(io.BytesIO(data)) as c:
        for frame in c.decode(audio=0):
            parts += [o.to_ndarray().reshape(-1) for o in resampler.resample(frame)]
    parts += [o.to_ndarray().reshape(-1) for o in resampler.resample(None)]
    return np.concatenate(parts).astype(np.int16)


def encode_webm(pcm: np.ndarray, rate: int = RATE) -> bytes:
    """int16 모노 → WebM/Opus 32kbps(MediaRecorder와 같은 형식)."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="webm") as c:
        st = c.add_stream("libopus", rate=rate, layout="mono")
        st.bit_rate = OPUS_BITRATE
        for i in range(0, pcm.size, 960):
            chunk = pcm[i:i + 960]
            chunk = np.pad(chunk, (0, 960 - chunk.size))
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts = rate, i
            for p in st.encode(frame):
                c.mux(p)
        for p in st.encode(None):
            c.mux(p)
    return buf.getvalue()


LEAD, GAP, MID, TRAIL = 2.0, 0.5, 5.0, 2.0  # P-long 무음: 앞, 발화 사이, 가운데, 뒤(최소)


def fit_count(durations: list[float], target_sec: float) -> int:
    """앞에서부터 몇 개의 발화가 target_sec 안에 들어가는가(무음 포함)."""
    budget, total, n = target_sec - LEAD - MID - TRAIL, 0.0, 0
    for dur in durations:
        step = dur + (GAP if n >= 2 else 0.0)  # 첫 경계는 0.5초 대신 가운데 5초가 들어가는 자리가 따로 있다
        if total + step > budget:
            break
        total, n = total + step, n + 1
    return n


def build_long(utts: list[tuple[np.ndarray, str]], target_sec: float, rate: int = RATE):
    """발화를 순서대로 이어 정확히 target_sec짜리 녹음을 만든다: 앞 2초, 발화 사이 0.5초, 가운데 경계에 5초, 뒤 2초 이상 무음.
    들어가는 만큼만 쓴다. 반환 (int16 PCM, 이어 붙인 정답, 무음 구간 [앞, 가운데, 뒤]의 [시작, 끝]초)."""
    lead, gap, mid = LEAD, GAP, MID
    chosen = utts[:fit_count([pcm.size / rate for pcm, _ in utts], target_sec)]
    if len(chosen) < 2:
        raise ValueError("이어 붙일 발화가 부족합니다")
    half = len(chosen) // 2
    out = [np.zeros(int(lead * rate), np.int16)]
    t = lead
    silences = [[0.0, lead]]
    for i, (pcm, _) in enumerate(chosen):
        if i == half:
            silences.append([t, t + mid])
            out.append(np.zeros(int(mid * rate), np.int16))
            t += mid
        elif i:
            out.append(np.zeros(int(gap * rate), np.int16))
            t += gap
        out.append(pcm)
        t += pcm.size / rate
    end = int(target_sec * rate)
    pcm = np.concatenate(out)
    pcm = np.concatenate([pcm, np.zeros(end - pcm.size, np.int16)])
    silences.append([round(t, 3), float(target_sec)])
    return pcm, " ".join(text for _, text in chosen), silences


# ───────── P ─────────

def _download(url: str, path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content


def _utterances(key: str, offset: int, length: int, raw: Path) -> list[dict]:
    meta = PUBLIC[key]
    rows = fetch_rows(meta["dataset"], meta["config"], meta["split"], offset, length)
    out = []
    for i, row in enumerate(rows, start=offset):
        url = row["audio"][0]["src"]
        check_revision(url, meta["revision"])
        pcm = load_pcm(_download(url, raw / key / f"{i:04d}{Path(url.split('?')[0]).suffix}"))
        out.append({"index": i, "pcm": pcm, "text": row[meta["text"]].strip(),
                    "source": {k: meta[k] for k in ("dataset", "revision", "split", "license", "url")} | {"index": i}})
    return out


def _entry(clip_id: str, set_name: str, pcm: np.ndarray, reference: str, source: dict, terms: dict,
           silences=None) -> dict:
    t = terms.get(clip_id, [])
    return {"clip_id": clip_id, "set": set_name, "audio_sec": round(pcm.size / RATE, 3), "reference": reference,
            "terms": t, "prompt_terms": [v[0] for v in t], "silences": silences or [], "source": source}


def prepare_public(data_dir: Path) -> list[dict]:
    terms = json.loads(TERMS_FILE.read_text(encoding="utf-8")) if TERMS_FILE.exists() else {}
    clips, raw = data_dir / "clips", data_dir / "raw"
    clips.mkdir(parents=True, exist_ok=True)
    manifest = []
    for key in ("zeroth", "fleurs"):
        for u in _utterances(key, 0, N_SHORT, raw):
            cid = f"{key}-{u['index']:03d}"
            (clips / f"{cid}.webm").write_bytes(encode_webm(u["pcm"]))
            manifest.append(_entry(cid, f"P-{key}", u["pcm"], u["text"], u["source"], terms))
    pool = _utterances("zeroth", N_SHORT, LONG_POOL, raw)
    for n, target in enumerate(LONG_TARGETS):
        pcm, text, silences = build_long([(u["pcm"], u["text"]) for u in pool], target)
        used = fit_count([u["pcm"].size / RATE for u in pool], target)
        cid = f"long-{target}-{n}"
        source = dict(pool[0]["source"], index=[u["index"] for u in pool[:used]])
        (clips / f"{cid}.webm").write_bytes(encode_webm(pcm))
        manifest.append(_entry(cid, "P-long", pcm, text, source, terms, silences))
        pool = pool[used:]
    for e in manifest:
        bad = [d for d in DECOYS if normalize(d) in normalize(e["reference"])]
        if bad:
            raise ValueError(f"{e['clip_id']} 정답에 미끼 용어가 있습니다: {bad}")
    (data_dir / "manifest-P.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


LAT_TARGETS = [30] * 8  # 보충 지연 측정용 L-30(설계의 P와 별도, 정확도 판단에 쓰지 않음)
LAT_OFFSET, LAT_POOL = 160, 80  # P-long이 쓴 Zeroth 100~158번 다음부터
# L-30 구성: 앞 0.5초 무음, 발화 사이 0.5초, 뒤는 남는 만큼(최소 0.5초). 가운데 긴 무음은 넣지 않는다(P-long과 다름)
L_LAYOUT = {"lead": 0.5, "gap": 0.5, "trail_min": 0.5}
MIN_SPEECH_RATIO = 0.75  # 말소리가 이보다 적은 클립은 만들지 않는다(무음이 지연을 줄여 보이게 하지 않도록)


def pack_utterances(durations: list[float], target_sec: float, lead: float = 0.5, gap: float = 0.5,
                    trail_min: float = 0.5) -> list[int]:
    """순서대로 보며 들어가는 발화의 번호. 넘치는 발화는 자르지 않고 건너뛴다(정답 문장이 잘리지 않게)."""
    budget, total, chosen = target_sec - lead - trail_min, 0.0, []
    for i, dur in enumerate(durations):
        step = dur + (gap if chosen else 0.0)
        if total + step <= budget:
            chosen.append(i)
            total += step
    return chosen


def build_packed(utts: list[tuple[np.ndarray, str]], target_sec: float, rate: int = RATE):
    """L_LAYOUT대로 통째 발화만 이어 정확히 target_sec짜리 녹음을 만든다.
    반환 (int16 PCM, 이어 붙인 정답, 무음 구간 [앞, 뒤], 쓴 발화 번호, 구성)."""
    lead, gap = L_LAYOUT["lead"], L_LAYOUT["gap"]
    used = pack_utterances([pcm.size / rate for pcm, _ in utts], target_sec, lead, gap, L_LAYOUT["trail_min"])
    speech = sum(utts[i][0].size for i in used) / rate
    if not used or speech < MIN_SPEECH_RATIO * target_sec:
        raise ValueError(f"{target_sec:.0f}초 클립을 채울 발화가 부족합니다(말소리 {speech:.1f}초)")
    parts = [np.zeros(int(lead * rate), np.int16)]
    for k, i in enumerate(used):
        if k:
            parts.append(np.zeros(int(gap * rate), np.int16))
        parts.append(utts[i][0])
    pcm = np.concatenate(parts)
    end_speech = pcm.size / rate
    pcm = np.concatenate([pcm, np.zeros(int(target_sec * rate) - pcm.size, np.int16)])
    composition = {"lead_sec": lead, "gap_sec": gap, "gaps": len(used) - 1, "trail_sec": round(target_sec - end_speech, 3),
                   "speech_sec": round(speech, 3), "silence_sec": round(target_sec - speech, 3), "utterances": len(used)}
    return (pcm, " ".join(utts[i][1] for i in used), [[0.0, lead], [round(end_speech, 3), float(target_sec)]],
            used, composition)


def prepare_latency(data_dir: Path) -> list[dict]:
    """30초 녹음 지연 보충 측정용 클립(L-30). 구성은 L_LAYOUT(앞 0.5초, 발화 사이 0.5초, 뒤 나머지), 발화는 자르지 않는다."""
    clips, raw = data_dir / "clips", data_dir / "raw"
    clips.mkdir(parents=True, exist_ok=True)
    pool, manifest = _utterances("zeroth", LAT_OFFSET, LAT_POOL, raw), []
    for n, target in enumerate(LAT_TARGETS):
        pcm, text, silences, used, composition = build_packed([(u["pcm"], u["text"]) for u in pool], target)
        cid = f"lat-{target}-{n}"
        (clips / f"{cid}.webm").write_bytes(encode_webm(pcm))
        entry = _entry(cid, f"L-{target}", pcm, text, dict(pool[0]["source"], index=[pool[i]["index"] for i in used]),
                       {}, silences)
        manifest.append(entry | {"composition": composition})
        pool = [u for i, u in enumerate(pool) if i not in set(used)]
    (data_dir / "manifest-L.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


# ───────── S ─────────

def validate_spont(entries: list[dict], root: Path) -> list[str]:
    """S manifest 검사. 오류 문장 목록(비어 있으면 통과)."""
    errors, seen = [], set()
    for n, e in enumerate(entries):
        cid = e.get("clip_id", f"#{n}")
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            errors.append(f"{cid}: 필수 항목 없음 {missing}")
            continue
        if cid in seen:
            errors.append(f"{cid}: clip_id 중복")
            continue
        seen.add(cid)
        ref = e["reference"]
        if not (root / e["audio"]).is_file():
            errors.append(f"{cid}: 오디오 파일 없음 {e['audio']}")
        elif ref.count("(") != ref.count(")") or ref.count("{") != ref.count("}"):
            errors.append(f"{cid}: 정답의 괄호 짝이 맞지 않음")
        elif not any(k != "filler" for k in parse_reference(ref).kinds):
            errors.append(f"{cid}: 정답에 내용이 없음")
        elif any(normalize(d) in normalize(ref) for d in DECOYS):
            errors.append(f"{cid}: 정답에 미끼 용어가 있음(configs.DECOYS와 겹치지 않게)")
        elif not (isinstance(e["terms"], list) and all(isinstance(t, list) for t in e["terms"])
                  and isinstance(e["prompt_terms"], list)):
            errors.append(f"{cid}: terms는 [[표기, …], …], prompt_terms는 [용어, …]")
    return errors


def prepare_spont(data_dir: Path) -> list[dict]:
    root = data_dir / "spont"
    entries = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errors = validate_spont(entries, root)
    if errors:
        raise ValueError("\n".join(errors))
    clips = data_dir / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    manifest = []
    for e in entries:
        pcm = load_pcm((root / e["audio"]).read_bytes())
        (clips / f"{e['clip_id']}.webm").write_bytes(encode_webm(pcm))
        manifest.append({**{k: e.get(k) for k in ("clip_id", "speaker", "device", "env", "question_id")},
                         "set": "S", "audio_sec": round(pcm.size / RATE, 3), "reference": e["reference"],
                         "terms": e["terms"], "prompt_terms": e["prompt_terms"], "silences": [],
                         "source": {"audio": e["audio"]}})
    (data_dir / "manifest-S.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m evals.stt.data")
    ap.add_argument("what", choices=["public", "spont", "latency"])
    ap.add_argument("--data-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        m = {"public": prepare_public, "spont": prepare_spont, "latency": prepare_latency}[args.what](args.data_dir)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    by_set: dict[str, int] = {}
    for e in m:
        by_set[e["set"]] = by_set.get(e["set"], 0) + 1
    print(json.dumps(by_set, ensure_ascii=False))


if __name__ == "__main__":
    main()
