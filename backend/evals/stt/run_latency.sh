#!/usr/bin/env bash
# 보충: 30초 녹음 1건 지연(L-30, 정확도 판단에는 쓰지 않음). 사용: cd backend && evals/stt/run_latency.sh <data-dir> [run-id]
# 다른 측정과 겹치지 않게 혼자 돌린다. 이미 있는 결과 파일은 건너뛴다.
set -u
D=${1:?data-dir}; R=${2:-lat}
PY=.venv/bin/python
[ -e "$D/manifest-L.json" ] || $PY -m evals.stt.data latency --data-dir "$D" || exit 1
[ -e "$D/results/$R/environment.json" ] || $PY -m evals.stt.run env --data-dir "$D" --run-id "$R"
for m in base small; do
  for t in 4 2; do
    for rep in 1 2 3; do
      f="$D/results/$R/$m-default-L-t$t-r$rep.jsonl"
      [ -e "$f" ] && continue
      $PY -m evals.stt.run config --data-dir "$D" --set L --config "$m-default" --run-id "$R" --threads "$t" --repeat "$rep"
      [ $? -eq 3 ] && { echo "resource not recovered — stopping batch"; exit 3; }
    done
  done
done
$PY -m evals.stt.report --data-dir "$D" --run-id "$R"
echo done
