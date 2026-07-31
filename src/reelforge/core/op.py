"""The `@op` decorator — the uniform contract for every atomic task.

Contract (all ops follow this):

    @op("detect_scenes")
    def op_detect_scenes(ctx: OpContext, video: str, ...) -> OpResult:
        ...
        return OpResult(outputs={...}, artifacts={...}, metrics={...})

The decorator wraps the call to: log start/finish to the ledger, time it,
record metrics, and register any artifacts as assets. This gives every op
observability for free and makes each op a drop-in Prefect @task later
(the body stays a pure function). Ops are single-responsibility: one op
does exactly one thing.
"""
from __future__ import annotations

import functools
import time
from typing import Callable

from .context import OpContext
from .types import OpResult

# Registry of all known ops, for introspection / CLI listing.
REGISTRY: dict[str, Callable] = {}


def op(name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(ctx: OpContext, *args, **kwargs) -> OpResult:
            ctx.log(name, "start")
            t0 = time.perf_counter()
            try:
                result = fn(ctx, *args, **kwargs)
            except Exception as e:  # noqa: BLE001 - surface as failed event, re-raise
                ctx.log(name, "error", f"{type(e).__name__}: {e}")
                raise
            if not isinstance(result, OpResult):
                raise TypeError(
                    f"op '{name}' must return OpResult, got {type(result).__name__}"
                )
            dt = time.perf_counter() - t0
            result.metrics.setdefault("elapsed_s", round(dt, 3))
            for a_name, a_path in result.artifacts.items():
                ctx.asset(a_name, a_path)
            status = "ok" if result.ok else "fail"
            ctx.log(name, status, result.message)
            return result

        wrapper._op_name = name  # type: ignore[attr-defined]
        REGISTRY[name] = wrapper
        return wrapper

    return deco
