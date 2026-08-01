"""Prefect orchestration adapter (optional).

Runs the pipelines as Prefect flows when Prefect is installed — giving durable
scheduling, retries, and observability — and falls back to the plain in-process
functions otherwise. Because every op is already a pure function, moving to
finer @task granularity is mechanical; this wrapper flips the whole run into a
Prefect @flow as the first, low-risk step.

    from reelforge.flows.prefect_flow import run_footage_orchestrated
    run_footage_orchestrated("ride.mp4", profile)   # uses Prefect if available
"""
from __future__ import annotations

from .footage import run_footage
from .generative import run_generative
from .hybrid import run_hybrid


def prefect_available() -> bool:
    try:
        import prefect  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _wrap(fn, name: str):
    if not prefect_available():
        return fn
    from prefect import flow
    return flow(name=name, log_prints=True)(fn)


def run_footage_orchestrated(*args, **kwargs):
    return _wrap(run_footage, "reelforge-footage")(*args, **kwargs)


def run_generative_orchestrated(*args, **kwargs):
    return _wrap(run_generative, "reelforge-generative")(*args, **kwargs)


def run_hybrid_orchestrated(*args, **kwargs):
    return _wrap(run_hybrid, "reelforge-hybrid")(*args, **kwargs)
