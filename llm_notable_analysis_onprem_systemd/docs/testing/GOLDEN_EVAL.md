# Golden Eval (first slice)

Small fixed corpus for **analyzer disposition** on easy baseline alerts.

## Corpus

| Case | Expected verdict | Intent |
|------|------------------|--------|
| `beaconing-tp` | `likely_malicious` | Obvious C2 beaconing |
| `patch-admin-fp` | `likely_benign` | Approved SCCM patch activity |
| `sparse-unknown` | `unknown` | Single low-signal DNS event |

Files under `data/golden_eval/`:

- `manifest.json` — case list and rubric tokens
- `alerts/` — raw notable JSON inputs
- `references/` — human-reviewed reference analyses (offline baseline)

Rubric checks (deterministic):

1. Response passes analyzer JSON schema
2. `alert_reconciliation.verdict` matches expected enum
3. At least one `evidence_any` token appears somewhere in the analysis JSON

## Run offline (CI default)

From repo root with venv active. CI uses `unittest discover` (same as below).

```bash
export PYTHONPATH=".:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src"
python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service \
  -p "test_golden_eval.py" -v
```

```powershell
$env:PYTHONPATH = ".;llm_notable_analysis_onprem_systemd/src;onprem-llm-sdk/src"
python -m unittest discover `
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service `
  -p "test_golden_eval.py" -v
```

Proves manifest validity, reference rubrics, and preview case-1 alignment. Does **not** call the LLM.

## Run live (opt-in)

Requires vLLM/LiteLLM (or compatible OpenAI endpoint) reachable at `LLM_API_URL`:

```bash
export PYTHONPATH=".:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src"
export GOLDEN_EVAL_LIVE=1
export LLM_API_URL="http://127.0.0.1:4000/v1/chat/completions"
python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service \
  -p "test_golden_eval.py" -v
```

```powershell
$env:PYTHONPATH = ".;llm_notable_analysis_onprem_systemd/src;onprem-llm-sdk/src"
$env:GOLDEN_EVAL_LIVE = "1"
$env:LLM_API_URL = "http://127.0.0.1:4000/v1/chat/completions"
python -m unittest discover `
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service `
  -p "test_golden_eval.py" -v
```

Run after prompt or model changes. Failures report case id, actual verdict, and rubric misses.

## Add a case

1. Add alert JSON under `alerts/`
2. Add reference analysis under `references/`
3. Append entry to `manifest.json` with `expected_verdict` and `evidence_any`
4. Run offline tests, then live eval when an LLM is available

## Out of scope (this slice)

- Portal chat golden questions
- SPL/query-result interpretation scoring
- Weekly summary or cross-case retrieval evals
- Automated timer/report export (see `docs/planning/golden_eval_harness_todo.md`)
