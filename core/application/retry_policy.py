"""Pure retry classification logic — no infrastructure dependencies."""
from __future__ import annotations


def is_terminal(current_retry_count: int, max_retries: int) -> bool:
    """Return True if the next failure should be terminal (no more retries)."""
    return current_retry_count + 1 >= max_retries
