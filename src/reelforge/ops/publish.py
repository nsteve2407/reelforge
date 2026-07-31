"""Publish ops — upload behind the approval gate, quota-aware. One job each.

Default is DRY-RUN (no credentials needed): the whole path runs, records a
'published' asset + quota usage, and returns a simulated URL. Pass dry_run=False
with creds to hit the real YouTube/Instagram adapters.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.context import OpContext
from ..core.op import op
from ..core.publish import (QuotaGuard, build_publish_meta, get_publisher,
                            next_best_time)
from ..core.types import OpResult


@op("quota_guard")
def op_quota_guard(ctx: OpContext, platform: str) -> OpResult:
    """Check remaining daily API quota for a platform. One job: gate on quota."""
    guard = QuotaGuard(ctx.ledger)
    allowed, after = guard.check(platform)
    return OpResult(
        ok=True,
        outputs={"allowed": allowed, "remaining": guard.remaining(platform),
                 "cost": guard.cost(platform)},
        metrics={"remaining": float(guard.remaining(platform))},
        message=f"{platform}: {'ok' if allowed else 'EXHAUSTED'} "
                f"(remaining {guard.remaining(platform)})",
    )


@op("schedule")
def op_schedule(ctx: OpContext, platform: str) -> OpResult:
    """Compute the publish time from the profile schedule. One job: scheduling."""
    when = next_best_time(datetime.now(timezone.utc), ctx.profile)
    return OpResult(outputs={"scheduled_at": when.isoformat() if when else None},
                    message=f"scheduled_at={when.isoformat() if when else 'immediate'}")


@op("publish")
def op_publish(ctx: OpContext, draft: str, platform: str, *,
               dry_run: bool = True, creds: dict | None = None) -> OpResult:
    """Publish one draft to one platform. One job: upload (quota-guarded)."""
    guard = QuotaGuard(ctx.ledger)
    allowed, _after = guard.check(platform)
    if not allowed:
        return OpResult(ok=False, outputs={"published": False, "reason": "quota"},
                        message=f"{platform}: quota exhausted, skipped")

    meta = build_publish_meta(ctx.profile, platform)
    publisher = get_publisher(platform, dry_run=dry_run, creds=creds)
    result = publisher.publish(str(draft), meta)

    if result.ok:
        guard.consume(platform)
        ctx.asset("published", str(draft), platform=platform, url=result.url,
                  video_id=result.video_id, dry_run=result.dry_run,
                  scheduled_at=result.scheduled_at)
    return OpResult(
        ok=result.ok,
        outputs={"published": result.ok, "result": result,
                 "url": result.url, "dry_run": result.dry_run,
                 "remaining": guard.remaining(platform)},
        message=result.message,
    )
