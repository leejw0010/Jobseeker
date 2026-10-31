#!/usr/bin/env bash
# 2단계: P 전체(설계 6절). 사용: cd backend && evals/stt/run_p_full.sh <data-dir> [run-id]
# 중요한 것부터 돈다(default 정확도 → 속도 반복 → 나머지 설정). 실행마다 앞 실행의 메모리 압박이 가라앉기를 먼저 기다린다
# (run.wait_for_recovery). 한 실행이 실패·중단돼도 다음으로 넘어가지만, 자원이 10분 안에 회복하지 않으면 배치를 멈춘다.
# 이미 있는 결과 파일은 건너뛴다(중간에 끊겼다가 다시 돌릴 때).
set -u
D=${1:?data-dir}; R=${2:-p-full}
PY=.venv/bin/python
LONG=$($PY -c "import json,sys; print(','.join(c['clip_id'] for c in json.load(open(sys.argv[1])) if c['set']=='P-long'))" "$D/manifest-P.json")

run() {  # run <config> <threads> <repeat> [clips]
  local f="$D/results/$R/$1-P-t$2-r$3.jsonl"
  [ -e "$f" ] && { echo "skip $1 t$2 r$3"; return; }
  $PY -m evals.stt.run config --data-dir "$D" --set P --config "$1" --run-id "$R" --threads "$2" --repeat "$3" ${4:+--clips "$4"}
  # 3 = 실행 전 자원 회복 대기(10분)를 넘김: 다음 실행도 같은 압박을 받으므로 배치를 멈춘다
  [ $? -eq 3 ] && { echo "resource not recovered — stopping batch"; exit 3; }
  return 0
}

[ -e "$D/results/$R/environment.json" ] || $PY -m evals.stt.run env --data-dir "$D" --run-id "$R"
run base-default 4 1; run small-default 4 1
for m in base small; do
  for rep in 2 3; do run "$m-default" 4 "$rep" "$LONG"; done
  for rep in 1 2 3; do run "$m-default" 2 "$rep" "$LONG"; done
done
for v in beam1 vadoff hot prompt-terms prompt-verbatim; do run "base-$v" 4 1; run "small-$v" 4 1; done
for m in base small; do for rep in 2 3; do run "$m-beam1" 4 "$rep" "$LONG"; done; done
$PY -m evals.stt.report --data-dir "$D" --run-id "$R"
echo done
