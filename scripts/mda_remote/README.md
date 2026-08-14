# MD&A remote sweep (RunPod)

One-shot backfill of the MD&A feature sweep on a rented GPU, plus a qwen3:30b-a3b
comparison sample to decide the extraction model. Same prompt/schema/settings as the
nightly scripts/mda_feature_sweep.py (asserted at export time).

Order:

1. `uv run scripts/mda_remote/export_pending.py` -> data/mda_pairs_pending.parquet
2. Create a RunPod pod (RTX 4090, 24GB, 50GB disk), scp up pairs.parquet,
   remote_sweep.py, setup_pod.sh to /workspace, run `bash setup_pod.sh` in tmux
3. When DONE appears, scp down results_8b.jsonl and results_30b.jsonl,
   terminate the pod
4. `uv run scripts/mda_remote/merge_results.py results_8b.jsonl`
5. `uv run scripts/mda_remote/compare_models.py results_8b.jsonl results_30b.jsonl`
