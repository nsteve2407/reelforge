"""Resilience + orchestration helpers.

`retry` / `with_retries` give any op exponential-backoff retries (used for the
network-y live publish/generation calls). This is the portable core; Prefect is
the production orchestrator drop-in (see flows/prefect_flow.py) — every op is a
pure function, so it maps 1:1 onto a Prefect @task with retries=... .
"""
from __future__ import annotations

import functools
import time
from typing import Callable, Iterable


def retry(fn: Callable, *args, retries: int = 3, backoff: float = 0.2,
          exceptions: tuple = (Exception,), sleep: Callable[[float], None] = time.sleep,
          on_retry: Callable[[int, Exception], None] | None = None, **kwargs):
    """Call fn(*args, **kwargs), retrying on `exceptions` with exponential backoff.

    Retries `retries` times AFTER the first attempt (so up to retries+1 calls).
    Re-raises the last exception if all attempts fail.
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except exceptions as e:  # noqa: BLE001
            if attempt >= retries:
                raise
            if on_retry:
                on_retry(attempt + 1, e)
            sleep(backoff * (2 ** attempt))
            attempt += 1


def with_retries(retries: int = 3, backoff: float = 0.2,
                 exceptions: tuple = (Exception,),
                 sleep: Callable[[float], None] = time.sleep) -> Callable:
    """Decorator form of `retry`."""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return retry(fn, *args, retries=retries, backoff=backoff,
                         exceptions=exceptions, sleep=sleep, **kwargs)
        return wrapper
    return deco
