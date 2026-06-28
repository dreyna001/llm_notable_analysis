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

From `s3_notable_pipeline` with venv active:

```bash
python -m pytest tests/test_golden_eval.py -v
```

```powershell
python -m pytest tests/test_golden_eval.py -v
```

Proves manifest validity and reference rubrics. Does **not** call Bedrock.

## Run live (opt-in)

Requires AWS credentials with Bedrock model access and `BEDROCK_MODEL_ID` set:

```bash
export GOLDEN_EVAL_LIVE=1
export BEDROCK_MODEL_ID="arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-4-6"
export AWS_REGION="us-east-1"
python -m pytest tests/test_golden_eval.py -v
```

```powershell
$env:GOLDEN_EVAL_LIVE = "1"
$env:BEDROCK_MODEL_ID = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-4-6"
$env:AWS_REGION = "us-east-1"
python -m pytest tests/test_golden_eval.py -v
```

Run after prompt or model changes. Failures report case id, actual verdict, and rubric misses.

## Add a case

1. Add alert JSON under `alerts/`
2. Add reference analysis under `references/`
3. Append entry to `manifest.json` with `expected_verdict` and `evidence_any`
4. Run offline tests, then live eval when Bedrock is available

## Out of scope (this slice)

- Portal chat golden questions
- SPL/query-result interpretation scoring
- Weekly summary or cross-case retrieval evals
- Preview scenario bundle alignment (on-prem only)
