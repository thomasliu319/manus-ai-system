# analyzer-retry-policy

## ADDED Requirements

### Requirement: EXCEPTION-REGISTRY

The `chat_with_retry()` function in `pipeline/model_client.py` MUST distinguish retryable from non-retryable exceptions.

**Implementation note**: Add a dedicated `except` clause for non-retryable exceptions BEFORE the existing `except (httpx.HTTPStatusError, ...)` block. Non-retryable exceptions propagate immediately; the existing httpx catch block is unchanged for retryables (httpx classes are superclasses of the openai exceptions → already covered).

#### Scenario: Non-retryable exceptions propagate immediately (new except clause)
- **WHEN** `provider.chat()` raises `json.JSONDecodeError`, `KeyError`, or `ValueError`
- **THEN** a dedicated `except` clause catches them BEFORE the httpx catch
- **AND** the exception MUST propagate immediately without retry

#### Scenario: Transient exceptions trigger retry (existing httpx catch unchanged)
- **WHEN** `provider.chat()` raises `httpx.TimeoutException`, `httpx.ConnectError`, or `httpx.HTTPStatusError` with `status_code >= 500`
- **THEN** the existing except block catches them
- **AND** the call MUST be retried according to RETRY-POLICY
- **AND** `openai.APITimeoutError` / `openai.APIConnectionError` / `openai.APIStatusError` are already covered via httpx superclass inheritance

#### Scenario: HTTP 4xx errors MUST NOT be retried (new behavior)
- **WHEN** `provider.chat()` raises `httpx.HTTPStatusError` with `status_code` in 400-499
- **THEN** the existing except block catches it
- **AND** `_is_retryable()` returns False
- **AND** the exception MUST be re-raised immediately without retry

### Requirement: RETRY-POLICY

The retry logic MUST use exponential backoff with jitter.

#### Scenario: Exponential backoff timing
- **WHEN** a retryable exception is caught
- **THEN** retries MUST follow: max_attempts=3, base_delay=1s, factor=2
- **AND** delay sequence MUST be approximately 1s → 2s → 4s
- **AND** max_delay MUST be capped at 20s
- **AND** jitter MUST multiply delay by 1.0-1.5× (only upward, anti-thundering-herd)

#### Scenario: Rate limit uses same backoff
- **WHEN** `RateLimitError` (HTTP 429) is raised
- **THEN** same exponential backoff policy as above
- **AND** `Retry-After` header MUST NOT be consumed (deferred to future iteration)

### Requirement: COST-TRACKING

Every retry attempt MUST be recorded in cost_tracker with attempt-level granularity.

#### Scenario: Successful attempt logs tokens
- **WHEN** any attempt (including first) succeeds
- **THEN** cost_tracker MUST log the attempt with `tokens=response.usage.total_tokens` and status="success"

#### Scenario: Failed retry attempt logs zero tokens
- **WHEN** a retry attempt raises a retryable exception before receiving a response
- **THEN** cost_tracker MUST log the attempt with `tokens=0` and status="retry_failed"
- **AND** when this is the final attempt (attempt == max_attempts), MUST also raise the exception after logging

### Requirement: DEGRADATION

When all retries are exhausted, the pipeline MUST degrade gracefully without aborting.

#### Scenario: Max retries exhausted triggers degraded path
- **WHEN** max_attempts consecutive retries all fail for a given item
- **THEN** `step_analyze` MUST fall back to using `item["description"]` (truncated to 200 chars) as default summary
- **AND** the item's `status` field MUST be set to `"degraded"`
- **AND** `step_analyze` MUST continue processing remaining items

#### Scenario: Degraded items bypass articles output
- **WHEN** `step_organize` encounters an item with `status="degraded"`
- **THEN** it MUST skip that item from `knowledge/articles/`
- **AND** MUST log `WARNING` with item title for audit traceability
- **AND** raw/ preservation is handled by `step_collect` (collected before degradation occurs, not re-specified here)

## MODIFIED Requirements

### Requirement: RETRY-SCOPE-REFINEMENT

The existing `chat_with_retry()` function MUST be enhanced from blanket retry to exception-aware retry.

#### Scenario: Existing retry behavior preserved for known retryables
- **WHEN** `chat_with_retry()` is called
- **THEN** all previously retryable exceptions (timeout, connection, HTTP 5xx) MUST still be retried
- **AND** the existing `except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)` catch block MUST remain structurally unchanged
- **AND** the exponential backoff timing (1s→2s→4s) MUST remain, with jitter added as a net-new behavior

#### Scenario: HTTP 4xx errors no longer retried (actual scope of refinement)
- **WHEN** `chat_with_retry()` catches an `httpx.HTTPStatusError` with `status_code` in 400-499 range
- **THEN** `_is_retryable()` MUST return False (4xx responses are deterministic — retry yields same result)
- **AND** the exception MUST be re-raised immediately

#### Scenario: New except clause for content-layer exceptions
- **WHEN** `provider.chat()` raises `json.JSONDecodeError`, `KeyError`, or `ValueError`
- **THEN** a new `except` clause BEFORE the httpx catch ensures immediate propagation
- **AND** these were never retried in the old code either (not httpx subclasses); the new clause makes this explicit and testable
