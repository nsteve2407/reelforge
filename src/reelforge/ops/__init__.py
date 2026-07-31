"""Atomic ops — one file per stage, one function per single responsibility.

Every op: `def op_x(ctx: OpContext, ...) -> OpResult`, decorated with @op("x").
Import side-effects register ops into core.op.REGISTRY.
"""
from . import ingest, understand, build, review, publish, research  # noqa: F401
