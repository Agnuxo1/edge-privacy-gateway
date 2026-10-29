#!/usr/bin/env bash
# edge-medicine benchmark job (server-ia, CPU lane). Usage: bash bench/job.sh [quick]
set -euo pipefail
cd "$(dirname "$0")/.."
P=/home/ai/proyectos/edge-medicine; mkdir -p "$P" results
export HF_HOME="$P/hf" BENCH_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
if [ ! -x "$P/.venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$P/.venv"
  "$P/.venv/bin/pip" install -q presidio-analyzer gliner 2>&1 | tail -3
  "$P/.venv/bin/python" -m spacy download en_core_web_lg 2>&1 | tail -2
fi
PY="$P/.venv/bin/python"
"$PY" -c "import torch,gliner,presidio_analyzer,spacy;print('torch',torch.__version__,'gliner',gliner.__version__,'spacy',spacy.__version__)" | tee results/versions.txt
"$PY" -m pip freeze > results/pip_freeze.txt
nproc > results/cpu.txt; lscpu | grep -i "model name" >> results/cpu.txt || true
# dev split for thresholds: train partition 2, first 300 docs (never test)
"$PY" - <<'PYEOF'
import json, sys; sys.path.insert(0, "bench"); from common import load, partition
rows = [r for r in load("data/sub/nem_train_health.jsonl") if partition(r["uid"]) == 2][:300]
with open("results/_dev300.jsonl", "w", encoding="utf8") as f:
    for r in rows: f.write(json.dumps(r) + "\n")
PYEOF
pick() { "$PY" bench/score.py tune results/_dev300.jsonl "$@" | tee -a results/tuning.txt | awk '/^BEST/{print $2}'; }
declare -A TH
for m in presidio:"0.0 0.35 0.5 0.7" gliner_gretel:"0.3 0.5 0.7" gliner_nvidia:"0.3 0.5 0.7"; do
  name=${m%%:*}; files=()
  for t in ${m#*:}; do
    "$PY" bench/run_method.py "$name" results/_dev300.jsonl "results/dev__${name}__$t.jsonl" --threshold "$t" >> results/run.log 2>&1
    files+=("results/dev__${name}__$t.jsonl")
  done
  best=$(pick "${files[@]}"); t=${best##*__}; TH[$name]=${t%.jsonl}; echo "$name threshold ${TH[$name]}" | tee -a results/tuning.txt
done
TH[gliner_gretel_int8]=${TH[gliner_gretel]}
LIM=""; [ "${1:-}" = quick ] && LIM="--limit 200"
for ds in nem gretel; do
  data=data/sub/${ds}_test_health.jsonl
  for m in navajo_v1 navajo_v2 navajo_v2_nolex navajo_v2_nokv navajo_v2_noshape navajo_v2_nodates navajo_v2_nonames navajo_v2_nov1 \
           presidio gliner_gretel gliner_gretel_int8 gliner_nvidia; do
    extra="$LIM"; [ "$m" = gliner_nvidia ] && [ "$ds" = nem ] && [ -z "$LIM" ] && extra="--limit 1500"
    echo "$(date -u +%FT%TZ) $ds $m" >> results/run.log
    "$PY" bench/run_method.py "$m" "$data" "results/${ds}__${m}.jsonl" --threshold "${TH[$m]:-0.5}" $extra >> results/run.log 2>&1 || echo "FAILED $ds $m" >> results/run.log
  done
done
"$PY" bench/score.py report results | tee results/summary.txt
