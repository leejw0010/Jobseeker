# 면접 서비스 동작 분석과 적용 기록

조사일: 2026-10-15. 공개 서비스 설명, 실제 내려받은 공개 클라이언트, 도구 실행 결과를 구분한다. 로그인한 제품 화면이나 유료 면접 세션을 분석한 결과가 아니다.

## 공개 자료에서 확인한 동작

| 서비스 | 확인한 동작 | JobSeeker에 적용 |
| --- | --- | --- |
| Final Round AI Practice Interview | 회사·직무·공고·이력서를 묶은 Goal, 대화형 면접, 회고와 취약점 재연습 | 지원 건에 고정된 기준 자료, 보완 답변 재연습 |
| Yoodli | 기본 질문과 답변에 따른 동적 후속 질문, 분석 또는 추가 질문 선택 | 답변 확인 후 꼬리질문/다음 질문 선택 |
| Big Interview PracticeAI | 공고/이력서/대화에 따른 질문, 답변별·기준별 피드백 펼쳐보기, 전사문과 예시 답변 비교 | 구체성·질문 적합성·제출본 연결 기준을 펼쳐 실제 인용과 함께 확인 |

출처:
- https://www.finalroundai.com/ai-mock-interview
- https://support.yoodli.ai/en/articles/9550465-practice-with-yoodli
- https://support.yoodli.ai/en/articles/11556965-creating-custom-goals
- https://support.yoodli.ai/en/articles/10055659-builder
- https://support.biginterview.com/en/article/practiceai-qxju4/

개별 기능을 새로운 발명으로 주장하지 않는다. JobSeeker의 적용안은 기존 Track의 **실제 제출 버전**과 면접 답변을 연결하고, 그 기준 본문을 보관하며, 피드백의 인용이 실제 원문에 있는지를 확인하는 것이다. 경쟁 서비스의 저장 구조, 모델, 프롬프트, 점수 알고리즘을 알아냈다는 의미가 아니다.

## REA 실제 실행

공식 https://github.com/morluto/rea 의 npm 패키지 `rea-agents`를 별도 임시 캐시에 설치했다. 전역 설치, `setup`, 사용자 에이전트 설정 변경은 하지 않았다. 실행 버전은 6.5.0이다.

실제로 내려받은 Yoodli의 공개 홈페이지 부트스트랩:

https://yoodli.ai/_next/static/chunks/pages/index-4809e9b3fd578e12.js

- HTTP 200, 942 bytes
- SHA256: `2394a2634b72b204ddf0a42ca457e6e5fc879ba89e13dad26afecd509fda49f8`
- 원문에서 확인 가능한 범위: Next.js/Webpack 홈페이지 부트스트랩, `/` 페이지 등록, 제목/설명, 외부 모듈로의 렌더링 위임.
- 면접 질문 생성이나 평가 로직이 들어 있는 자료는 아니다.

실행한 명령(경로는 실제 임시 디렉터리로 대체):

```bash
npx -y rea-agents@6.5.0 --version
npx --offline -y rea-agents@6.5.0 analyze-javascript-application /absolute/path/to/yoodli-public-client --analysis-timeout-ms 20000 --format json
```

REA는 파일 목록과 해시를 수집했으나 AST 분석 전 프로세스 소유권 확인에서 중단됐다.

```text
exit: 1
code: capability_unavailable
provider_id: process-ownership
operation: prepare_owned_process
ps -axo pid=,ppid=,pgid=,uid=,stat=,command=
fatal library error, lookup self
parsed_javascript_files: 0
visited_ast_nodes: 0
modules: 0
findings: 0
```

따라서 REA가 제품 내부 알고리즘을 복원했다고 주장하지 않는다. 소유권 확인을 우회하거나 가짜 실행 자료를 사용하지 않았다. 공식 문서도 Linux에서 정상 동작하는 procps `ps`를 요구한다. 라이브 웹 분석에는 접근 가능한 Chrome CDP endpoint와 실제 target이 추가로 필요하다.

- https://github.com/morluto/rea/blob/main/docs/installation.md#linux-owned-process-prerequisite
- https://github.com/morluto/rea/blob/main/docs/browser-observation.md

다음 관찰 실험은 동일 질문에 구체적인 답변과 모호한 답변을 입력해 후속 질문 및 회고의 차이를 기록하는 것이다. 현재 확인한 공개 설명은 이 실험의 결과를 대신하지 않는다.

## 구현의 검증 범위

LLM 경로는 외부 호출을 모의 응답으로 대체해 JSON 처리와 인용 검증을 시험한다. 실제 API 응답의 코칭 품질, 실제 면접 성과, 경쟁 제품 대비 효과는 검증하지 않았다. 기본 점검은 수치 등 표현의 존재만 확인하는 규칙이며, 의미나 사실 여부를 판정하는 AI 평가로 표시하지 않는다.
