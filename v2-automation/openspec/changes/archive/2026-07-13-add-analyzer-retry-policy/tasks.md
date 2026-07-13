# tasks.md — add-analyzer-retry-policy

## Implementation tasks

### 1. Add exception registry to model_client.py
- [ ] Define `RETRYABLE_EXCEPTIONS` tuple at module level in `pipeline/model_client.py`
- [ ] Add `_is_retryable(exc: BaseException) -> bool` helper (returns True for RETRYABLE_EXCEPTIONS + `APIStatusError(status_code>=500)`)
- [ ] Modify `chat_with_retry()` catch block to skip retry when `not _is_retryable(exc)` → immediate raise
- **Files**: `pipeline/model_client.py`
- **Spec**: EXCEPTION-REGISTRY, RETRY-SCOPE-REFINEMENT

### 2. Add per-attempt cost tracking to chat_with_retry
- [ ] Add optional `cost_tracker: Callable[[str, int], None] | None = None` parameter to `chat_with_retry()` signature
- [ ] On success: call `cost_tracker("success", response.usage.total_tokens)`
- [ ] On retryable failure: call `cost_tracker("retry_failed", 0)`
- [ ] Backward compat: `cost_tracker=None` → no-op, existing callers unaffected
- **Files**: `pipeline/model_client.py`
- **Spec**: COST-TRACKING

### 3. Add degraded handling to step_analyze
- [ ] Wrap `chat_with_retry()` call in `try/except` in `step_analyze()`
- [ ] On exception: construct degraded item with `summary=description[:200]`, `tags=["degraded"]`, `score=0`, `status="degraded"`
- [ ] Continue loop to process remaining items
- [ ] Log WARNING with item title and exception type
- **Files**: `pipeline/pipeline.py`
- **Spec**: DEGRADATION

### 4. Add degraded filter to step_organize
- [ ] Add check at start of `step_organize`: `if item.get("status") == "degraded": continue`
- [ ] Log INFO "skipping degraded item: {title}"
- **Files**: `pipeline/pipeline.py`
- **Spec**: DEGRADATION (Scenario: Degraded items bypass articles output)

### 5. Write unit tests
- [ ] `test_retryable_exceptions` — verify _is_retryable returns True for 6 exception types
- [ ] `test_non_retryable_exceptions` — verify _is_retryable returns False for JSONDecodeError/KeyError/ValueError
- [ ] `test_5xx_is_retryable` — APIStatusError(503) → True, APIStatusError(404) → False
- [ ] `test_retry_eventual_success` — flaky function succeeds on 3rd attempt
- [ ] `test_retry_exhausts_and_raises` — all attempts fail → original exception propagates
- [ ] `test_cost_tracker_logs_success` — cost_tracker callback receives ("success", >0)
- [ ] `test_cost_tracker_logs_retry_failed` — cost_tracker callback receives ("retry_failed", 0)
- [ ] `test_degraded_item_status` — step_analyze produces status="degraded" on failure
- [ ] `test_degraded_item_skipped_in_organize` — step_organize filters out degraded items
- **Files**: `tests/test_retry.py`
- **Spec**: All 5 requirements

### 6. Integration test (dry-run pipeline)
- [ ] Run `python pipeline/pipeline.py --dry-run --limit 3`
- [ ] Verify degraded items appear in output dict but not in `knowledge/articles/`
- **Command**: `python pipeline/pipeline.py --dry-run --limit 3 --verbose`
- **Spec**: DEGRADATION end-to-end

## Task dependencies

```
Task 1 ──→ Task 2 ──→ Task 3 ──→ Task 4
  │                    │
  └──→ Task 5 ────────┘
                          │
                          └──→ Task 6
```

## Verification checklist

After all tasks complete, run `/opsx-verify`:
- [ ] EXCEPTION-REGISTRY: `_is_retryable()` returns correct for all 6+3 types
- [ ] RETRY-POLICY: timing follows 1s→2s→4s with jitter
- [ ] COST-TRACKING: each attempt logged with correct status and tokens
- [ ] DEGRADATION: degraded items flow through pipeline, skip articles output
- [ ] RETRY-SCOPE-REFINEMENT: non-retryable exceptions propagate immediately
