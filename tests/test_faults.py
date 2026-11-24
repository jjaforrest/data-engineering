from api.faults import FaultInjector, RateLimiter, faulty_page_numbers


def test_rate_limiter_60_per_min_returns_retry_after():
    limiter = RateLimiter(max_requests=60, window_seconds=60.0)
    t0 = 1000.0

    for i in range(60):
        allowed, retry_after = limiter.check("key-a", now=t0 + i * 0.1)
        assert allowed is True
        assert retry_after == 0

    allowed, retry_after = limiter.check("key-a", now=t0 + 10.0)
    assert allowed is False
    assert retry_after >= 1

    # Different key is not blocked
    other_allowed, _ = limiter.check("key-b", now=t0 + 10.0)
    assert other_allowed is True


def test_500_first_request_only_and_retry_identical():
    seed = 42
    page_size = 100
    target_pages = faulty_page_numbers(seed=seed, page_size=page_size, total_pages=500, error_rate=0.015)
    assert len(target_pages) > 0

    page = target_pages[0]
    injector = FaultInjector(seed=seed, error_rate=0.015, repeat_count=120)

    # First attempt fails with 500
    assert injector.should_fail_500_on_first_request(page, page_size) is True
    # Immediate retry succeeds (no 500)
    assert injector.should_fail_500_on_first_request(page, page_size) is False

    # Build deterministic page payload
    def build_page(p: int) -> list[dict]:
        earlier = [{"id": f"rec-{ep}-{i}"} for ep in range(1, p) for i in range(page_size)]
        current = [{"id": f"rec-{p}-{i}"} for i in range(page_size)]
        dups = injector.repeated_records_for_page(p, page_size, lambda _cur: earlier)
        return current + dups

    first_success = build_page(page)
    retry_payload = build_page(page)
    assert first_success == retry_payload


def test_two_full_pulls_are_identical_and_append_at_least_100_records():
    seed = 42
    page_size = 150
    pages = range(1, 6)

    def run_full_pull() -> list[list[dict]]:
        injector = FaultInjector(seed=seed, error_rate=0.015, repeat_count=120)
        all_records_by_page: dict[int, list[dict]] = {}
        pulled: list[list[dict]] = []

        for p in pages:
            if injector.should_fail_500_on_first_request(p, page_size):
                assert injector.should_fail_500_on_first_request(p, page_size) is False

            base = [{"id": f"p{p}-r{i}"} for i in range(page_size)]
            earlier = [rec for prev_p in range(1, p) for rec in all_records_by_page[prev_p]]
            dups = injector.repeated_records_for_page(p, page_size, lambda _cur, e=earlier: e)
            if p > 1:
                assert len(dups) >= 100
                earlier_ids = {r["id"] for r in earlier}
                assert all(d["id"] in earlier_ids for d in dups)

            all_records_by_page[p] = base
            pulled.append(base + dups)

        return pulled

    assert run_full_pull() == run_full_pull()