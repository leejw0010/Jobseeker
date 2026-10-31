"""전사 채점. 모델 출력은 이 모듈 안에서만 정규화하고, 원본은 바꾸지 않는다(설계 5·7절).

정답 표기(설계 4절): (음) 간투사 · 단어- 말 고침 조각 · // 끝맺지 못한 문장의 끊긴 자리 · {a|b} 둘 다 맞는 표기
"""
import random
import re
import unicodedata
from dataclasses import dataclass, field

SPAN_MIN = 5  # 빠뜨린 말·지어낸 말로 목록에 넣는 최소 연속 글자 수
COMPLETION_MIN = 2  # // 뒤에 이만큼 이상 삽입되면 "문장 지어 붙이기"


def normalize(text: str) -> str:
    """NFC, 영문 소문자, 문장부호·공백·기호·제어 문자 제거. 채점 비교에만 쓴다."""
    text = unicodedata.normalize("NFC", text).lower()
    return "".join(c for c in text if unicodedata.category(c)[0] not in "PZSC")


# ───────── 숫자 읽기 (간이) ─────────

_DIGITS = "영일이삼사오육칠팔구"
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _read4(n: int) -> str:
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
        d, n = divmod(n, unit)
        if d:
            out += (name if d == 1 and unit > 1 else _DIGITS[d] + name)
    return out


def _read_int(n: int) -> str:
    if n == 0:
        return "영"
    out = ""
    for unit, name in ((10 ** 12, "조"), (10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        g, n = divmod(n, unit)
        if g:
            out += ("만" if g == 1 and name == "만" else _read4(g) + name)
    return out


def sino_korean(text: str) -> str:
    """아라비아 숫자를 한자어 수 읽기로 바꾼다(2011 → 이천십일, 3.5 → 삼점오). 고유어 수("두 개", "세 시")는 다루지 않는다."""
    def read(m: re.Match) -> str:
        whole, _, frac = m.group().replace(",", "").partition(".")
        return _read_int(int(whole)) + ("점" + "".join(_DIGITS[int(d)] for d in frac) if frac else "")
    return _NUMBER.sub(read, text)


# ───────── 정답 파싱 ─────────

@dataclass
class Reference:
    chars: str  # 정규화한 정답(간투사·말 고침 조각 포함)
    kinds: list[str]  # 글자마다 word | filler | fragment
    cuts: list[int]  # // 앞까지의 글자 수(그 자리 뒤에서 문장이 끊김)
    groups: list[tuple[int, int, str]] = field(default_factory=list)  # 간투사·조각의 [시작, 끝) 구간


_ALT = re.compile(r"\{([^{}]*)\}")
_TOKEN = re.compile(r"\(([^()]*)\)|//|[^\s()/]+(?:/[^\s()/]+)*")


def _prep(text: str, numnorm: bool) -> str:
    return normalize(sino_korean(text) if numnorm else text)


def parse_reference(text: str, hyp_norm: str = "", numnorm: bool = False, markup: bool = True) -> Reference:
    """{a|b}는 출력(정규화형)에 들어 있는 표기 중 가장 긴 것, 없으면 첫 표기로 고른다.
    markup=False면 표기 없이 글자 그대로 읽는다(공개 데이터 정답의 괄호는 간투사가 아니라 원문 괄호이므로)."""
    text = unicodedata.normalize("NFC", text)
    if not markup:
        chars = _prep(text, numnorm)
        return Reference(chars, ["word"] * len(chars), [])

    def pick(m: re.Match) -> str:
        options = m.group(1).split("|")
        found = [o for o in options if _prep(o, numnorm) and _prep(o, numnorm) in hyp_norm]
        return max(found, key=lambda o: len(_prep(o, numnorm))) if found else options[0]

    text = _ALT.sub(pick, text)
    chars, kinds, cuts, groups = [], [], [], []
    for m in _TOKEN.finditer(text):
        tok = m.group()
        if tok == "//":
            cuts.append(len(chars))
            continue
        if m.group(1) is not None:
            piece, kind = _prep(m.group(1), numnorm), "filler"
        elif tok.endswith("-") and len(tok) > 1:
            piece, kind = _prep(tok[:-1], numnorm), "fragment"
        else:
            piece, kind = _prep(tok, numnorm), "word"
        if kind != "word" and piece:
            groups.append((len(chars), len(chars) + len(piece), kind))
        chars.extend(piece)
        kinds.extend([kind] * len(piece))
    return Reference("".join(chars), kinds, cuts, groups)


# ───────── 정렬 ─────────

def align(ref: str, hyp: str) -> list[tuple[str, int | None, int | None]]:
    """글자 단위 레벤슈타인 정렬. op는 = S D I. 동점이면 대각선(=/S) > 삭제 > 삽입 순으로 고른다."""
    n, m = len(ref), len(hyp)
    dp = [list(range(m + 1))] + [[i] + [0] * m for i in range(1, n + 1)]
    for i in range(1, n + 1):
        row, prev, r = dp[i], dp[i - 1], ref[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (r != hyp[j - 1]), prev[j] + 1, row[j - 1] + 1)
    ops, i, j = [], n, m
    while i or j:
        if i and j and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "S", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("D", i - 1, None))
            i -= 1
        else:
            ops.append(("I", None, j - 1))
            j -= 1
    return ops[::-1]


# ───────── 한 클립 채점 ─────────

@dataclass
class ClipScore:
    n_content: int
    e_content: int
    n_verbatim: int
    e_verbatim: int
    omitted: list[str]
    invented: list[str]
    fillers: int
    fillers_kept: int
    fragment_chars: int
    fragment_kept: int
    cuts: int
    completions: list[str]


def score_clip(reference: str, hyp_text: str, numnorm: bool = False, markup: bool = True) -> ClipScore:
    """CER_content: 정답 간투사에 걸린 편집(그 글자의 치환·삭제, 간투사 글자 사이 삽입)만 빼고 센다.
    출력 쪽에서 간투사 낱말을 지우지 않으므로 말하지 않은 간투사는 삽입 오류가 된다."""
    hyp = _prep(hyp_text, numnorm)
    ref = parse_reference(reference, hyp, numnorm, markup)
    ops = align(ref.chars, hyp)
    kinds = ref.kinds
    filler = lambda i: 0 <= i < len(kinds) and kinds[i] == "filler"  # noqa: E731

    e_content = e_verbatim = 0
    omitted, invented, completions = [], [], []
    run_d, run_i = [], []
    inserted_at: dict[int, list[str]] = {}
    matched = [False] * len(kinds)
    consumed = 0  # 지금까지 정렬한 정답 글자 수

    def flush_d():
        if len(run_d) >= SPAN_MIN:
            omitted.append("".join(run_d))
        run_d.clear()

    def flush_i():
        if len(run_i) >= SPAN_MIN:
            invented.append("".join(run_i))
        run_i.clear()

    for op, ri, hi in ops:
        if op != "=":
            e_verbatim += 1
        if op == "I":
            flush_d()
            run_i.append(hyp[hi])
            inserted_at.setdefault(consumed, []).append(hyp[hi])
            if not (filler(consumed - 1) and filler(consumed)):
                e_content += 1
            continue
        flush_i()
        consumed += 1
        if op == "=":
            matched[ri] = True
            flush_d()
            continue
        if not filler(ri):
            e_content += 1
        if op == "D":
            if not filler(ri):  # 간투사를 빼먹은 것은 내용 누락으로 보지 않는다(구간을 끊지도 않음)
                run_d.append(ref.chars[ri])
        else:
            flush_d()
    flush_d()
    flush_i()

    for k in ref.cuts:
        ins = inserted_at.get(k, [])
        if len(ins) >= COMPLETION_MIN:
            completions.append("".join(ins))
    fillers = [(s, e) for s, e, kind in ref.groups if kind == "filler"]
    fragments = [(s, e) for s, e, kind in ref.groups if kind == "fragment"]
    return ClipScore(
        n_content=sum(k != "filler" for k in kinds), e_content=e_content,
        n_verbatim=len(kinds), e_verbatim=e_verbatim,
        omitted=omitted, invented=invented,
        fillers=len(fillers), fillers_kept=sum(2 * sum(matched[s:e]) >= e - s for s, e in fillers),
        fragment_chars=sum(e - s for s, e in fragments), fragment_kept=sum(sum(matched[s:e]) for s, e in fragments),
        cuts=len(ref.cuts), completions=completions,
    )


# ───────── 용어·무음·불확실성 ─────────

def count_terms(terms: list[list[str]], hyp_text: str) -> tuple[int, int]:
    """(찾은 수, 전체 등장 수). terms의 항목 하나가 한 번 등장(허용 표기 목록). 같은 용어가 두 번이면 항목도 두 번."""
    hyp = normalize(hyp_text)
    listed: dict[tuple[str, ...], int] = {}
    for variants in terms:
        key = tuple(v for v in (normalize(x) for x in variants) if v)
        listed[key] = listed.get(key, 0) + 1
    found = sum(min(n, max((hyp.count(v) for v in key), default=0)) for key, n in listed.items())
    return found, len(terms)


def false_terms(prompt_terms: list[str], reference: str, hyp_text: str) -> list[str]:
    """프롬프트·hotwords에 넣은 용어 중 정답에 없는데 출력에 나온 것."""
    ref, hyp = normalize(reference), normalize(hyp_text)
    out = []
    for term in dict.fromkeys(prompt_terms):
        t = normalize(term)
        if t and t not in ref and t in hyp:
            out.append(term)
    return out


def silence_hallucinations(segments: list[dict], silences: list[list[float]]) -> list[str]:
    """길이의 절반 넘게 넣어 둔 무음 구간과 겹치는 세그먼트의 글자(무음에서 지어낸 말 후보)."""
    out = []
    for seg in segments:
        dur = seg["end"] - seg["start"]
        overlap = sum(max(0.0, min(seg["end"], e) - max(seg["start"], s)) for s, e in silences)
        if dur > 0 and overlap > dur / 2 and seg["text"].strip():
            out.append(seg["text"].strip())
    return out


def bootstrap_diff(clips: list[tuple[int, int, int]], iters: int = 10000, seed: int = 0) -> tuple[float, float, float]:
    """(정답 글자 수, A 편집 수, B 편집 수) 목록 → (micro CER(A) − CER(B), 95% 구간 아래, 위). 클립 단위로 다시 뽑는다."""
    def diff(sample):
        n = sum(c[0] for c in sample)
        return (sum(c[1] for c in sample) - sum(c[2] for c in sample)) / n if n else 0.0

    rng = random.Random(seed)
    stats = sorted(diff([clips[rng.randrange(len(clips))] for _ in clips]) for _ in range(iters))
    return diff(clips), stats[int(0.025 * iters)], stats[min(iters - 1, int(0.975 * iters))]
