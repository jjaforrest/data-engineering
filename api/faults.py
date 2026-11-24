from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict, deque
from typing import Any, Callable, Iterable

DEFAULT_SEED: int = 42


def _unit_hash(seed: int | str, page: int, page_size: int, salt: str = "") -> float:
    """Return a deterministic float in [0.0, 1.0) for (seed, page, page_size, salt)."""
    payload = f"{seed}:{page}:{page_size}:{salt}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    # Use top 64 bits for a uniform float in [0.0, 1.0)
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value / float(1 << 64)


class RateLimiter:
    """Sliding-window per-key rate limiter (60 requests per 60s window)."""

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """
        Return (allowed, retry_after_seconds).
        If not allowed, retry_after_seconds is at least 1.
        """
        current = time.monotonic() if now is None else now
        bucket = self._hits[key]

        cutoff = current - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            oldest = bucket[0]
            retry_after = max(1, math.ceil((oldest + self.window_seconds) - current))
            return False, retry_after

        bucket.append(current)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


class FaultInjector:
    """
    Deterministic fault injector for 500-on-first-request and repeated records.
    Tracks first-seen (seed, page, page_size) in memory (single-worker process).
    """

    def __init__(
        self,
        seed: int | str = DEFAULT_SEED,
        error_rate: float = 0.015,  # 1.5% (within 1-2%)
        repeat_count: int = 120,     # >= 100 records appended to later pages
    ) -> None:
        if not (0.01 <= error_rate <= 0.02):
            raise ValueError("error_rate must be between 0.01 and 0.02 (1-2%)")
        if repeat_count < 100:
            raise ValueError("repeat_count must be >= 100")

        self.seed = seed
        self.error_rate = error_rate
        self.repeat_count = repeat_count
        self._seen_first_request: set[tuple[str, int, int]] = set()

    def reset_state(self) -> None:
        self._seen_first_request.clear()

    def should_fail_500_on_first_request(self, page: int, page_size: int) -> bool:
        """
        Deterministic 1-2% 500 fault on the first request for (seed, page, page_size).
        Subsequent requests for the same (seed, page, page_size) return False.
        """
        key = (str(self.seed), page, page_size)
        is_500_candidate = _unit_hash(self.seed, page, page_size, salt="500") < self.error_rate
        if not is_500_candidate:
            return False

        if key not in self._seen_first_request:
            self._seen_first_request.add(key)
            return True
        return False

    def repeated_records_for_page(
        self,
        page: int,
        page_size: int,
        earlier_records_provider: Callable[[int], Iterable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        For later pages (page > 1), deterministically select >= 100 records from
        earlier pages (pages < page) to append so dedup logic can be tested.
        """
        if page <= 1 or page_size <= 0:
            return []

        pool = list(earlier_records_provider(page))
        if not pool:
            return []

        count = min(len(pool), max(100, self.repeat_count))
        indexed = sorted(
            range(len(pool)),
            key=lambda idx: _unit_hash(self.seed, page, page_size, salt=f"dup:{idx}"),
        )
        chosen_indices = sorted(indexed[:count])
        return [dict(pool[i]) for i in chosen_indices]


class FaultState:
    """Stateful wrapper used by api/main.py for rate limiting and 500 fault injection."""

    def __init__(
        self,
        seed: int | str = DEFAULT_SEED,
        error_rate: float = 0.015,
        repeat_count: int = 120,
        max_requests: int = 60,
        window_seconds: float = 60.0,
    ) -> None:
        self.seed = seed
        self._injector = FaultInjector(
            seed=seed,
            error_rate=error_rate,
            repeat_count=repeat_count,
        )
        self._rate_limiter = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

    def check_rate_limit(self, key: str) -> int | None:
        allowed, retry_after = self._rate_limiter.check(key)
        return None if allowed else retry_after

    def should_fail_with_500(self, page: int, page_size: int) -> bool:
        return self._injector.should_fail_500_on_first_request(page=page, page_size=page_size)

    def reset(self) -> None:
        self._injector.reset_state()
        self._rate_limiter.reset()


def get_repeated_records_for_page(
    seed: int | str,
    page: int,
    page_size: int,
    total_pages: int,
    fetch_record_fn: Callable[[int, int, int], Any],
    repeat_count: int = 120,
) -> list[Any]:
    """
    Deterministically sample >= 100 earlier records for later pages (page > 1)
    when at least 100 earlier records exist.
    """
    if page <= 1 or page_size <= 0 or total_pages <= 1:
        return []

    earlier_pages = min(page - 1, total_pages)
    total_earlier = earlier_pages * page_size
    if total_earlier < 100:
        return []

    count = min(total_earlier, max(100, repeat_count))
    indexed = sorted(
        range(total_earlier),
        key=lambda flat_idx: _unit_hash(seed, page, page_size, salt=f"dup:{flat_idx}"),
    )
    chosen = sorted(indexed[:count])

    duplicates: list[Any] = []
    for flat_idx in chosen:
        earlier_page = (flat_idx // page_size) + 1
        earlier_index = flat_idx % page_size
        rec = fetch_record_fn(earlier_page, earlier_index, page_size)
        if rec is not None:
            duplicates.append(rec)
    return duplicates


def faulty_page_numbers(
    seed: int | str,
    page_size: int,
    total_pages: int = 200,
    error_rate: float = 0.015,
) -> list[int]:
    """
    Return sorted 1-based page numbers in [1, total_pages] that deterministically
    trigger a first-request 500 for the given (seed, page_size).
    """
    if page_size <= 0 or total_pages < 1:
        return []
    if not (0.01 <= error_rate <= 0.02):
        raise ValueError("error_rate must be between 0.01 and 0.02 (1-2%)")

    return [
        page
        for page in range(1, total_pages + 1)
        if _unit_hash(seed, page, page_size, salt="500") < error_rate
    ]