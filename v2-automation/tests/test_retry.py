"""Unit tests for analyzer-retry-policy (spec coverage: 5 requirements)"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.model_client import (  # noqa: E402
    RETRYABLE_EXCEPTIONS,
    Usage,
    _is_retryable,
    chat_with_retry,
)


# ── Mocks ──────────────────────────────────────────────────────────────

def _mock_response(prompt_tokens: int = 100, completion_tokens: int = 50) -> MagicMock:
    r = MagicMock()
    r.usage = Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return r


def _mock_httpx_error(status_code: int) -> Exception:
    """Create a mock httpx.HTTPStatusError with given status code."""
    import httpx
    request = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    return httpx.HTTPStatusError("msg", request=request, response=response)


# ── Test: EXCEPTION-REGISTRY ───────────────────────────────────────────

class TestExceptionRegistry:
    """spec: EXCEPTION-REGISTRY"""

    def test_retryable_timeout(self):
        import httpx
        assert _is_retryable(httpx.TimeoutException("timeout"))

    def test_retryable_connect_error(self):
        import httpx
        assert _is_retryable(httpx.ConnectError("connect"))

    def test_retryable_5xx(self):
        assert _is_retryable(_mock_httpx_error(503))

    def test_retryable_500_boundary(self):
        assert _is_retryable(_mock_httpx_error(500))

    def test_non_retryable_4xx(self):
        assert not _is_retryable(_mock_httpx_error(404))

    def test_non_retryable_400(self):
        assert not _is_retryable(_mock_httpx_error(400))

    def test_non_retryable_401(self):
        assert not _is_retryable(_mock_httpx_error(401))

    def test_non_retryable_json_error(self):
        assert not _is_retryable(json.JSONDecodeError("x", "y", 0))

    def test_non_retryable_key_error(self):
        assert not _is_retryable(KeyError("missing"))

    def test_non_retryable_value_error(self):
        assert not _is_retryable(ValueError("bad"))


# ── Test: RETRY-POLICY ────────────────────────────────────────────────

class TestRetryPolicy:
    """spec: RETRY-POLICY"""

    def test_first_attempt_succeeds(self):
        provider = MagicMock()
        provider.chat.return_value = _mock_response(100, 50)

        resp = chat_with_retry(provider, [{"role": "user", "content": "hi"}])
        assert resp.usage.total_tokens == 150
        assert provider.chat.call_count == 1

    def test_retry_with_eventual_success(self):
        import httpx
        provider = MagicMock()
        provider.chat.side_effect = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _mock_response(100, 50),
        ]

        resp = chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                               max_retries=3, backoff_base=0.01)
        assert resp.usage.total_tokens == 150
        assert provider.chat.call_count == 3

    def test_retry_exhausts_and_raises(self):
        import httpx
        provider = MagicMock()
        provider.chat.side_effect = httpx.TimeoutException("always timeout")

        with pytest.raises(httpx.TimeoutException):
            chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                            max_retries=2, backoff_base=0.01)
        assert provider.chat.call_count == 2

    def test_4xx_not_retried(self):
        provider = MagicMock()
        provider.chat.side_effect = _mock_httpx_error(404)

        with pytest.raises(Exception):
            chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                            max_retries=3, backoff_base=0.01)
        assert provider.chat.call_count == 1  # 不应重试 4xx

    def test_content_error_not_retried(self):
        provider = MagicMock()
        provider.chat.side_effect = json.JSONDecodeError("bad json", "...", 0)

        with pytest.raises(json.JSONDecodeError):
            chat_with_retry(provider, [{"role": "user", "content": "hi"}])
        assert provider.chat.call_count == 1


# ── Test: COST-TRACKING ────────────────────────────────────────────────

class TestCostTracking:
    """spec: COST-TRACKING"""

    def test_cost_tracker_logs_success(self):
        provider = MagicMock()
        provider.chat.return_value = _mock_response(200, 100)
        records: list[tuple[str, int]] = []

        chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                        cost_tracker=lambda s, t: records.append((s, t)))
        assert records == [("success", 300)]

    def test_cost_tracker_logs_retry_failed(self):
        import httpx
        provider = MagicMock()
        provider.chat.side_effect = [
            httpx.TimeoutException("t1"),
            httpx.TimeoutException("t2"),
            _mock_response(100, 50),
        ]
        records: list[tuple[str, int]] = []

        chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                        max_retries=3, backoff_base=0.01,
                        cost_tracker=lambda s, t: records.append((s, t)))
        assert records == [
            ("retry_failed", 0),
            ("retry_failed", 0),
            ("success", 150),
        ]

    def test_cost_tracker_logs_final_attempt_when_exhausted(self):
        import httpx
        provider = MagicMock()
        provider.chat.side_effect = httpx.TimeoutException("always timeout")
        records: list[tuple[str, int]] = []

        with pytest.raises(httpx.TimeoutException):
            chat_with_retry(provider, [{"role": "user", "content": "hi"}],
                            max_retries=2, backoff_base=0.01,
                            cost_tracker=lambda s, t: records.append((s, t)))

        assert all(r[0] == "retry_failed" for r in records)
        assert len(records) == 2
        assert all(r[1] == 0 for r in records)

    def test_cost_tracker_optional(self):
        provider = MagicMock()
        provider.chat.return_value = _mock_response(100, 50)
        resp = chat_with_retry(provider, [{"role": "user", "content": "hi"}])
        assert resp.usage.total_tokens == 150  # 不传 cost_tracker 也应正常
