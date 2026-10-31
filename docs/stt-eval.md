# 로컬 STT 정확도 평가 실행 방법

설계: [superpowers/specs/2026-10-30-a-stt-evaluation-design.md](superpowers/specs/2026-10-30-a-stt-evaluation-design.md). 측정 결과: [research/stt-eval-2026-10-30.md](research/stt-eval-2026-10-30.md).

평가 도구는 운영과 같은 경로(`app.stt.decode` → 무음 검사 → `app.stt.run_whisper`)로 전사하고, 모델이 낸 원본을 고치지 않고 저장한 뒤 따로 채점합니다. 기본 STT 설정은 바꾸지 않습니다.

## 준비

- 데이터·결과 폴더 `D`는 **저장소 밖**에 둡니다(예: `~/stt-eval`). 녹음과 원본 출력이 들어갑니다.
- 명령은 모두 `backend/`에서 `.venv/bin/python`으로 실행합니다.

```bash
cd backend
D=~/stt-eval
.venv/bin/python -m evals.stt.data public --data-dir $D          # P: Zeroth-Korean·FLEURS ko_kr(CC BY 4.0) 208개 클립
LOCAL_STT_MODEL=small .venv/bin/python -m app.stt download        # small 모델 미리 받기(약 460MB). base는 이미 받아 둔 것 사용
```

평가 실행은 `HF_HUB_OFFLINE=1`, `LOCAL_STT_ALLOW_DOWNLOAD=false`로 돌아 캐시에 없는 모델을 받지 않습니다.

## 단계

| 단계 | 명령 | 확인 |
|---|---|---|
| 0. 도구 점검 | `.venv/bin/python -m evals.stt.run config --data-dir $D --set P --config base-default --run-id smoke --clips zeroth-000,…` 을 `--repeat 1`, `--repeat 2`로 → `python -m evals.stt.report --data-dir $D --run-id smoke` | 보고서 생성, "반복 실행 출력 일치" |
| 1a. 프롬프트 점검 | `.venv/bin/python -m evals.stt.run probe --data-dir $D --clip long-120-4 --model base` | `initial_prompt`는 창 1에서만 이전 토큰이 있고 `hotwords`는 모든 창에 들어가는지 |
| 1b. small 메모리 점검 | `run config … --config small-default --run-id smoke-small --clips <10개>` | `status: ok`이면 다음 단계, `aborted`면 하드웨어 한계로 기록하고 small 전체 생략 |
| 2. P 전체 | `evals/stt/run_p_full.sh $D p-full`(환경 기록 → 12개 설정 1회씩 → `base/small-default`·`-beam1`은 P-long 8개로 `--repeat 2`·`3`, `-default`는 `--threads 2 --repeat 1~3` → 보고서). 끊겼다가 다시 돌리면 있는 결과는 건너뜀 | `D/results/p-full/report.md` |
| 3. S | 아래 S 준비 뒤 `data spont`, 같은 12개 설정을 `--set S`로. **run-id는 P와 다르게**(한 run-id에 P·S를 섞으면 거부) | 화자별 결과, 판단이 "잠정"에서 벗어남 |
| 보충. 30초 지연 | `evals/stt/run_latency.sh $D lat`(L-30 클립 생성 → base·small default를 4·2스레드로 3회씩) | 30초 녹음 1건 지연. 정확도·판단에는 쓰지 않음 |

설정 id: `{base,small}-{default,beam1,vadoff,hot,prompt-terms,prompt-verbatim}`(`backend/evals/stt/configs.py`).

**메모리 안전 중단.** 실행 중 0.5초마다 메모리를 보고, `MemAvailable` < 200MB, 시작 대비 스왑 증가 > 256MB, PSI `full` avg10 > 10 중 하나가 2초 넘게 이어지면 평가 하위 프로세스만 멈추고 `<결과>.parent.json`에 `aborted`와 측정값을 남깁니다. 다른 프로세스와 시스템 설정은 건드리지 않습니다.

**실행 사이 자원 회복 대기.** 실행을 시작하기 전에 앞 실행이 남긴 메모리 압박이 가라앉기를 기다립니다(`run.wait_for_recovery`: PSI `full` 10초 평균 ≤ 1, `MemAvailable` ≥ 500MB가 10초 이어짐). 10분 안에 회복하지 않으면 그 실행은 시작하지 않고(`not_started`) 배치 스크립트는 멈춥니다(종료 코드 3). 중단 기준(위)은 그대로입니다. 2026-10-30 실행에서는 이 대기가 없어, 앞 실행의 압박을 물려받은 24개 실행이 시작 2초 만에 연달아 중단됐습니다.

**실행 상태 분류**(보고서 "실행 상태"): `완료` · `자원 보호로 중단`(위 기준, 모델 추론 실패가 아님) · `자원 미회복으로 시작 안 함` · `프로그램·추론 오류`(하위 프로세스 오류 종료, `.log` 확인). 도중에 멈춘 실행은 정확도 표에 넣지 않고 "미완료 실행의 부분 결과"에 끝낸 클립 수와 함께 따로 적으며, base와는 같은 클립끼리만 비교합니다.

**L-30 구성**(30초 지연 보충, `data latency`): Zeroth test 160번부터 발화를 순서대로 보며 **통째로만** 넣습니다(자르지 않음, 넘치는 발화는 건너뜀). 앞 0.5초 무음 → 발화 → 발화 사이 0.5초 → … → 남는 시간은 뒤 무음(최소 0.5초)으로 정확히 30초. 말소리가 22.5초(75%) 미만이면 만들지 않습니다. 클립마다 `composition`(말소리·무음 초, 발화 수)을 `manifest-L.json`에 남깁니다. 2026-11-01 생성 결과: 8개 모두 30.0초, 말소리 24.1~28.0초, 발화 2~4개. P-long(60·120초)은 처음 설계대로 앞 2초·가운데 5초·뒤 2초 이상 무음입니다.

**채점 규칙.** P 정답은 표기 없이 글자 그대로 채점합니다(FLEURS 정답의 `깁슨(Gibson)` 같은 괄호는 간투사가 아님). `(음)`·`//` 등 표기는 S 정답에만 씁니다. P의 주 지표는 숫자를 양쪽 다 한자어 읽기로 바꾼 CER_num입니다.

**결과 파일** (`D/results/<run-id>/`): `<설정>-<세트>-t<스레드>-r<반복>.jsonl`(원본, 덮어쓰지 않음), `.child.json`(로딩·메모리), `.parent.json`(상태·메모리 압박), `.log`, `environment.json`, `report.md`, `summary.json`, `clips.md`(클립별 대조 — **로컬 전용**).

## S: 자연스러운 면접 답변 준비

최소 파일럿 표본: 동의한 화자 3명 이상 × 답변 6개 이상(30~120초), 약 20분. 녹음과 정답이 없으면 S 단계는 실행하지 않고 판단은 "잠정"으로 남습니다. **녹음이나 정답을 지어내지 않습니다.**

1. **동의서**(화자마다 서면): 이 평가에만 로컬에서 사용 · 외부(OpenAI 등)로 보내지 않음 · 저장소에 넣지 않음 · 결과는 집계치만 공개 · 예시 문장은 따로 허락한 것만 · 언제든 철회 가능(그 화자 파일 삭제 후 다시 채점) · 기본값 결정(D-20) 기록 뒤 삭제(보관을 원하면 날짜).
2. **녹음**: 앱 질문 은행에서 자기소개·프로젝트 경험(기술 용어)·행동 질문을 섞어 원고 없이 답합니다. 48kHz 모노 WAV 권장. 앱 브라우저에서 녹음한 WebM도 됩니다. `D/spont/`에 둡니다.
3. **정답 전사**: 녹음을 들으며 들은 그대로 적습니다. **모델 출력을 보지 않습니다.** 다른 사람이 답변의 20% 이상을 다시 듣고 고칩니다.

| 표기 | 뜻 | 예 |
|---|---|---|
| `(음)` | 간투사 | `(음) 저는 (어) 백엔드를` |
| `단어-` | 말을 시작하다 끊고 고침 | `프론트- 백엔드를 맡았고` |
| `//` | 끝맺지 못하고 버린 문장의 끊긴 자리 | `그래서 제가 그때 // 결과적으로는` |
| `{3월\|삼 월}` | 둘 다 맞는 표기 | `{AWS\|에이더블유에스}에 올렸습니다` |

4. **`D/spont/manifest.json`**:

```json
[
  {"clip_id": "s-a-01", "speaker": "A", "device": "노트북 내장", "env": "조용함", "question_id": "q12",
   "audio": "a-01.wav",
   "reference": "(음) 저는 프론트- 백엔드를 맡았고 {AWS|에이더블유에스}에 // 결과적으로는 레디스로 캐시를 붙였습니다",
   "terms": [["AWS", "에이더블유에스"], ["레디스", "Redis"]],
   "prompt_terms": ["백엔드 개발자", "주식회사 예시"]}
]
```

- `terms`: 실제로 말한 고유명사·전문용어(등장할 때마다 한 항목, 허용 표기 목록).
- `prompt_terms`: 앱이 답변 **전에** 알 수 있는 용어(질문 문구, 지원 회사·직무). 실제로 말한 용어를 여기에 넣지 않습니다.
- 정답에 미끼 용어(`쿠버네티스`, `그라파나`, `카산드라`, `테라폼`, `엘라스틱서치`)가 있으면 검사에서 거부됩니다.

```bash
.venv/bin/python -m evals.stt.data spont --data-dir $D    # 검사 통과 시 manifest-S.json
```

## 공개 범위

- `D/`의 녹음·원본 출력·`clips.md`는 커밋하지 않습니다.
- P 집계와 예시(출처·라이선스 표기)는 `docs/research/`에 둘 수 있습니다. S는 집계치만, 예시는 화자가 허락한 것만 둡니다.

## 알려진 한계 (2026-10-30 실행)

결과를 검증된 결과·부분 결과·하드웨어 한계·측정하지 않음으로 나눈 표는 [research/stt-eval-2026-10-30.md](research/stt-eval-2026-10-30.md)의 "결과 구분"에 있습니다.

- 이 기계(RAM 3.7GB, 스왑 1GB가 시작 전부터 거의 참, 개발 서버·VS Code 실행 중)에서 `small`은 23개 클립 만에 스왑을 319MB 늘려 메모리 감시가 멈췄습니다. **`small` 평가는 하드웨어 한계로 미완료**이며, 보호 기준을 우회해 다시 돌리지 않습니다.
- 끝까지 측정한 것은 `base-default`의 P 1회뿐입니다. 나머지 설정·반복·2스레드는 측정값이 없습니다(위 "실행 사이 자원 회복 대기" 참고).
- 원본 측정값(JSONL·실행 기록·보고서·manifest·로그)은 저장소 밖 `~/stt-eval-archive/2026-10-30/`에 체크섬(`SHA256SUMS`)과 함께 보관합니다. 요약은 [research/stt-eval-2026-10-30.md](research/stt-eval-2026-10-30.md).
- 전체 재실행은 사용자 승인 뒤에만 합니다. 고친 실행 도구는 2026-11-01에 작은 점검(base, 2+2개 클립)으로만 확인했습니다.

