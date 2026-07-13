# design.md — add-analyzer-retry-policy

## Architecture Decision

### Decision 1: Enhance existing `chat_with_retry` rather than add a new decorator

**Context**: `pipeline/model_client.py` already has `chat_with_retry()` (L210-260) with exponential backoff (max_retries=3, backoff_base=2.0). Introducing a separate `with_retry` decorator would create two competing retry mechanisms.

**Decision**: Enhance `chat_with_retry()` with an exception registry instead of adding a new decorator layer.

**Rationale**:
- Single retry code path avoids double-retry bugs (decorator retries × function retries)
- `chat_with_retry` already has exponential backoff, jitter, and delay — reuse instead of rewrite
- Exception registry is a 20-line addition vs a 60-line decorator

**Alternative rejected**: Adding a `with_retry` decorator on `chat()` — would stack retries (decorator catches → calls chat → chat calls chat_with_retry which retries again), creating max_attempts² behavior.

### Decision 2: Exception registry as a module-level tuple + helper function

**Context**: The proposal specifies 5 retryable and 3 non-retryable exception types.

**Decision**: Define `RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...]` at module level and `_is_retryable(exc) -> bool` helper.

**Rationale**:
- Tuple is immutable and importable by tests
- Helper function handles the `APIStatusError.status_code >= 500` edge case cleanly
- If a new exception needs to be added, change one line in the tuple

### Decision 3: Degradation in `step_analyze`, not in `chat_with_retry`

**Context**: When retries exhaust, the proposal requires degraded summary + status="degraded" + pipeline continuation.

**Decision**: `chat_with_retry` raises the last exception; `step_analyze` catches it and applies degraded handling.

**Rationale**:
- `chat_with_retry` is a transport-layer concern — it shouldn't know about business-level concepts like "degraded status"
- `step_analyze` owns the item's lifecycle and is the right place to decide fallback strategy
- Testable independently: test_retry covers transport, test_analyzer covers degradation

### Decision 4: Degraded items preserved in raw/ but excluded from articles/

**Context**: Degraded items have low-quality summaries (200-char truncation of raw description) but their raw data may still be useful.

**Decision**: `step_organize` checks `status != "degraded"` before writing to `knowledge/articles/`. Degraded items remain in the enrichment list and can be written to `knowledge/raw/` separately.

**Rationale**:
- Prevents low-quality entries from polluting the knowledge base
- Preserves raw data for debugging and future re-processing
- Clean separation: articles/ has quality gate, raw/ has completeness

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Double-retry if chat() is also wrapped | Medium | High | Decision 1 explicitly avoids this; code review gate |
| Existing callers break from changed exception behavior | Low | Medium | `chat_with_retry` signature unchanged; only internal exception handling refined |
| Degraded items silently lost | Low | Medium | Degraded items explicitly logged with WARNING; raw/ preservation |

## Cost Estimation

| Tokens | Base Cost | With 3 retries (worst case) |
|--------|-----------|---------------------------|
| 50 items × 500 tokens each | 25,000 prompt | 25,000 × 4 attempts = 100,000 prompt tokens |
| Per-day cost (DeepSeek) | ~$0.035 | ~$0.14 |

Budget guard: `BUDGET_YUAN=1.0` environment variable triggers alert at 80% (~$0.11).
