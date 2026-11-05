# 익명 음성·얼굴·Gaze 검증

이 도구는 **연습 후 관찰 집계**를 검증한다. 음성 에너지는 VAD·발음·감정 판정이 아니고, 얼굴 자세는 시선·집중도·자신감 판정이 아니다. Gaze는 개발 전용 실험실에 유지한다. 실제 면접 도중 답을 표시하지 않는다.

## 증거 수준

| evidence | 확인 범위 | 확인하지 못하는 것 |
|---|---|---|
| `synthetic-signal` | 순수 계산, 실제 AudioContext에 넣은 합성 PCM, 가짜 얼굴 검출기의 UI·거절·중단 배선 | 실제 발화·사람·카메라 정확도 |
| `public-fixture-real-model` | 아래 고정 공개 fixture와 실제 Whisper base·기존 MediaPipe Face Landmarker 실행 | 자발적 면접 발화·실시간 기기·안경·조명·시선 정확도 |
| `human-device` | 사람이 직접 동의하고 실제 장치에서 수행한 실행 | 표본 밖 사용자·기기에 대한 일반화 |

자동 테스트가 `human-device` 증거를 만들지는 않는다. 기본 E2E의 fake face 및 STT off 결과는 공개 fixture의 실제 모델 결과와 구분한다. 사람 파일럿과 실제 카메라·마이크, Supabase·유료 OpenAI 품질 검증은 이번 자동 실행에서 수행하지 않았다.

## 익명 파일 계약

음성·얼굴 보고서와 Gaze 실험실에 명시적 JSON 내보내기 버튼이 있다. 원본 관측·요약은 탭 메모리만 사용하며 서버 전송·localStorage·IndexedDB 보관을 추가하지 않는다. 사람이 누르기 전에는 파일도 만들지 않는다. 내려받은 파일은 동의 철회·결과 삭제로 회수할 수 없다는 안내를 화면에 표시한다.

`schemaVersion=jobseeker-validation-v1`; kind는 `voice|face|gaze-phase0`, evidence는 위 세 값, status는 `complete|invalid|aborted|error`다. 익명 `runId`, protocol/method/config/code 버전과 dirty 여부, 브라우저·OS·delegate·조건·뷰포트·DPR·알려진 카메라 해상도, 분모, 허용된 숫자 집계 또는 null, 정해진 reasonCodes, 개별 verdict만 내보낸다. 브라우저는 엔진 계열이며 OS는 범주다. 알 수 없는 크기는 null이다. 비교 전 사람이 별도 장치 기록에서 브라우저/OS 정확한 버전도 확인한다.

전사 원문·추임새 낱말·사용자/답변 ID·경로·키·token·영상/음성·특징점·좌표/에너지 시계열·보정 계수는 내보내지 않는다. 추임새는 후보 **개수**만 나간다. 녹음 revision이 바뀌거나 삭제/동의 철회로 지운 요약은 내보낼 수 없다. 저장한 전사문과 다르거나 편집 중인 전사문의 속도·추임새와 음성 내보내기는 숨긴다. 얼굴 요약은 녹음 revision 당시의 delegate와 해상도를 기억한다. 같은 요약을 다시 내려받아도 runId는 같아 중복 분석을 막는다. 익명 내보내기에는 식별 가능한 메모를 덧붙이지 않는다.

Gaze는 완료한 실패도 `complete`로 남기며, 창/해상도 무효·사용자 중단·카메라/모델 오류도 별도 시도로 남긴다. 무효 시도의 accepted는 검증하지 않았으면 null이다. 결과를 지우거나 실험실을 떠나면 집계도 사라진다. 새 보정마다 새 runId를 사용한다.

## 오프라인 비교

```bash
cd backend
.venv/bin/python -m evals.validation.compare \
  --input /tmp/run-1.json --input /tmp/run-2.json --out /tmp/new-validation-comparison
```

입력은 단일 artifact 또는 artifact 배열이다. 출력 디렉터리는 새 것이어야 하며 `comparison.json`, `.csv`, `.md`를 만든다. 비교 모듈은 Python 표준 라이브러리만 쓰고 app.config·provider를 import하지 않으며 네트워크 호출도 없다. 알 수 없는 schemaVersion/필드·reason code, 비유한 수, 음수·서로 모순되는 분모, 중복 runId를 거부한다. 기존 `{note,runs}` Gaze 파일은 **legacy unversioned 개수**로만 별도 표시하며 새 수치와 합치지 않는다.

kind/evidence/protocol/method/config/code/dirty/환경이 다르면 별도 그룹이다. 완료한 실패·inconclusive도 모든 해당 개별 판정의 분모에 남긴다. invalid/aborted/error는 제외 이유별 시도 수로 보존한다. **repeatSpreadReference = (e50Relative 최대−최소) / e50Relative 중앙값**이다. 동일 기록 조건의 완료한 fresh 보정에서 유한한 e50 값 3개 이상이며 중앙값>0일 때만 표시한다. 누락된 e50은 제외하되 시도 수는 보존한다. 이는 반복 참고값으로만 쓰며 **H2 전체 인증은 항상 false**다. 현재 기준/임계값을 낮추거나 기능을 자동으로 켜지 않는다.

## 공개 fixture와 실제 모델 재현

다운로드는 선택 작업이며 전체 데이터셋을 받지 않는다. 출처·사용권·고정 revision·SHA256은 [fixtures.json](../backend/evals/validation/fixtures.json)에 있다. 음성은 Zeroth-Korean test의 앞 **2개**(CC BY 4.0, Lucas Jo/Wonkyum Lee, Bingsu packaging)다. 얼굴은 NASA Eileen Collins portrait의 scikit-image v0.24.0 사본으로, scikit-image가 public domain임을 명시한 연구용 fixture다. 실제 사람의 지원서·녹음·얼굴 자료를 사용하지 않는다. NASA/인물의 제품 보증이나 상업용 홍보 이미지로 사용하지 않는다.

- [Zeroth-Korean 고정판 데이터 카드](https://huggingface.co/datasets/Bingsu/zeroth-korean/blob/bd173fe2c8ed0dccd47acb4eda77542593651622/README.md)
- [scikit-image astronaut 사용권 설명](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut)
- [NASA 이미지 사용 지침](https://www.nasa.gov/nasa-brand-center/images-and-media/)

```bash
cd backend
.venv/bin/python -m evals.validation.prepare --out /tmp/new-jobseeker-media-fixtures
# base가 캐시에 있어야 한다. 없으면 다운로드하지 않고 실패한다.
HF_HUB_OFFLINE=1 .venv/bin/python -m evals.validation.bench_voice \
  --fixtures /tmp/new-jobseeker-media-fixtures --out /tmp/new-voice-result.json \
  --code-version "$(git rev-parse HEAD)"

# Whisper 프로세스 종료 뒤에 실행: RAM 약 3.7GB에서 모델을 동시에 올리지 않는다.
cd ../web
VALIDATION_FIXTURES_DIR=/tmp/new-jobseeker-media-fixtures \
VITE_VALIDATION_CODE_VERSION="$(git rev-parse HEAD)" \
LD_LIBRARY_PATH="$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu" \
npx playwright test -c playwright.validation.config.ts

LD_LIBRARY_PATH="$HOME/.cache/playwright-syslibs/root/usr/lib/x86_64-linux-gnu" \
npx playwright test -c playwright.validation-gaze.config.ts
```

브라우저 fixture 검증은 백엔드 없이 5183, Gaze fake 흐름은 5185를 쓴다. 일반 E2E의 8011/5179와 겹치지 않는다. `VALIDATION_RESULTS_DIR`를 지정하지 않으면 익명 결과는 `/tmp/jobseeker-media-browser-artifacts`에 기록한다. fixture는 브라우저 route로 로컬에서 공급하며 모델도 고정 SHA를 검사한다. PCM은 살아 있는 AudioContext의 analyser와 **녹음기와 같은 byte RMS 함수**를 거친다. gated tone/constant tone/clipping을 구분하고 세 AudioContext를 닫는다. MediaPipe는 고정 portrait와 검은 프레임을 같은 VIDEO detector에 넣고 두 번 순차 생성·close하며 임시 canvas stream의 track도 모두 정지한다.

STT는 CPU INT8 base, 2 threads, 한국어 beam5/VAD on/previous text off로 2개×3회 실행한다. 전사문을 파일이나 표준 출력에 남기지 않고 공개 정답 대비 CER 집계만 계산한다. cold는 모델 로딩+첫 전사, warm p50/p95는 이후 5회이며 모델을 두 번 생성/해제한다. 이는 2개 낭독 fixture의 smoke 관측이며 정확도 벤치마크로 일반화하지 않는다.

CPU/RSS 정의: STT CPU는 `process_time`, RSS는 프로세스 `ru_maxrss`; 브라우저 CPU는 해당 Chromium 인스턴스의 SystemInfo process CPU 합계 변화, RSS는 실행 후 살아 있는 프로세스별 `/proc` VmHWM 합계다. 브라우저 RSS는 연속 측정한 동시 peak가 아니며 임시 브라우저 전체의 보수적 참고값이다. PCM 세 행에 붙인 CPU/RSS는 세 조건 전체 실행의 공통 자원값이므로 행별로 더하지 않는다. p50/p95도 장치/실제 CPU delegate 결과와 섞지 않는다.

## 사람이 직접 하는 파일럿

```bash
scripts/start-validation-pilot.sh --check
scripts/start-validation-pilot.sh
# Web http://127.0.0.1:5181, API http://127.0.0.1:8013
# Gaze http://127.0.0.1:5181/dev/gaze-lab
```

매번 새로운 `/tmp/jobseeker-human-pilot-*` DB/recordings만 쓰고, 서버는 localhost에만 연다. 개인 dotenv가 있으면 읽지 않고 시작을 거부한다(`.env.example`은 허용). 앱은 test 환경/개발 사용자, 관찰 on, competency evidence off, 로컬 base 캐시 전용·외부 비밀값 빈 값으로 시작한다. 유료 API 0회다. 모델은 첫 로컬 전사 시에만 로딩하므로 종료·기동 검증 자체는 실제 녹음이나 모델을 쓰지 않는다. Ctrl-C는 이 실행이 만든 서버 PID만 종료한다. 종료 메시지의 임시 디렉터리를 사람이 확인 후 삭제한다. 다른 개발 서버나 운영 자료를 지우지 않는다.

| 순서 | 사람이 동의하고 할 것 | 기록/판독 |
|---|---|---|
| 1 | Practice를 시작하고 마이크 동의. 조용한 환경에서 15–30초 자연스럽게 답변 | 관찰 조건 `quiet`, 전체 길이/coverage/속도 후보, CPU, 브라우저/OS 버전. 원본과 전사 차이는 직접 확인 |
| 2 | 같은 장치에서 작은 배경 소음만 추가 | `background-noise`; RMS가 말소리와 소음을 구별했다고 해석하지 않음 |
| 3 | “음, 어, 그러니까” 문장과 “음악, 어머니, 그동안” 대조 문장을 따로 말하기 | `filler-candidates`/`non-filler-control`; 독립 낱말 후보와 비후보 확인. 오탐도 기록 |
| 4 | 전사 편집→저장/취소, 재녹음, 결과 삭제, 동의 철회, 새로고침 | 편집 중/불일치 전사 속도·음성 export 숨김, 옛 revision 제거, 동의 철회 후 export 없음, 탭 새로고침 시 집계 없음. 이미 다운로드한 파일은 회수되지 않음 |
| 5 | 카메라 별도 동의. 정면→이마/볼 경계→좌우 돌림/숙임을 따로 수행 | `face-in-frame`/`face-edge`/`face-pose`; 얼굴 없음과 검출 실패·프레임 이탈을 혼동하지 않기 |
| 6 | 평소 조명/안경부터 시작해 저조도 또는 안경 하나만 변경 | `low-light` 또는 `glasses`; 원인 하나씩, 추적 실패와 분석 공백도 보존 |
| 7 | Gaze에서 평소 조건으로 **새 보정 3회**, 각 완료 후 export | [3회 프로토콜](research/2026-11-04-gaze-protocol.md). 같은 보정의 반복 예측은 독립 시행 아님 |
| 8 | Gaze 실행 중 창 크기 변경, 별도 실행에서 카메라 해상도 변경, 별도 실행에서 중단 | invalid 이유 구별 및 aborted/export 상태, 실패 완료 분모 보존 |

원본 음성·얼굴은 사람의 명시적 동의 없이 외부로 보내거나 재전사하지 않는다. 파일럿은 사용자가 직접 수행하며 이 문서의 표를 자동 테스트 결과로 채우지 않는다. 기기·언어별 정확도 결론과 실험실 밖 Gaze 활성화는 이 증거만으로 하지 않는다.
