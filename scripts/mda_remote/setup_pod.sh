#!/usr/bin/env bash
# Bootstrap a RunPod GPU pod (24GB card) and run the 8B backfill + 30B comparison.
# Expects pairs.parquet and remote_sweep.py in /workspace (scp them up first).
# Leaves results_8b.jsonl / results_30b.jsonl in /workspace and touches DONE when
# finished; the pod is NOT terminated here -- results must be scp'd down first.
set -euo pipefail
cd /workspace

if ! curl -sf localhost:11434/api/version > /dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
  export OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_NUM_PARALLEL=6
  nohup ollama serve > ollama.log 2>&1 &
  for i in $(seq 30); do curl -sf localhost:11434/api/version && break; sleep 2; done
fi
ollama pull qwen3:8b
ollama pull qwen3:30b-a3b
pip install -q --break-system-packages requests duckdb

python3 remote_sweep.py --input pairs.parquet --output results_8b.jsonl --model qwen3:8b --parallel 6
python3 remote_sweep.py --input pairs.parquet --output results_30b.jsonl --model qwen3:30b-a3b --parallel 4 --sample 300

touch DONE
echo "sweep complete: $(wc -l < results_8b.jsonl) 8B rows, $(wc -l < results_30b.jsonl) 30B rows"
