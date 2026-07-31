"""Publish subsystem: quota guard, scheduling, metadata, dry-run publish."""
from __future__ import annotations

from datetime import datetime, timezone

from reelforge.core.context import OpContext
from reelforge.core.profile import ContentProfile
from reelforge.core.state import Ledger
from reelforge.core.storage import Storage
from reelforge.core.publish import (QuotaGuard, build_publish_meta, next_best_time,
                                    DryRunPublisher, PublishMeta)
from reelforge.ops import publish as P


def _ctx(tmp_path, profile):
    led = Ledger(tmp_path / "db.sqlite")
    return OpContext(run_id=led.create_run(profile.id), profile=profile,
                     storage=Storage(tmp_path / "w"), ledger=led)


def _day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---- quota ----

def test_quota_guard_blocks_after_limit(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    g = QuotaGuard(led)
    assert g.check("youtube_shorts")[0] is True
    for _ in range(6):                 # 6 * 1600 = 9600 used
        g.consume("youtube_shorts")
    assert g.remaining("youtube_shorts") == 400
    assert g.check("youtube_shorts")[0] is False   # 400 < 1600


def test_instagram_quota_units(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    g = QuotaGuard(led)
    assert g.cost("instagram_reels") == 1
    g.consume("instagram_reels")
    assert g.remaining("instagram_reels") == 24


# ---- scheduling + metadata ----

def test_next_best_time_immediate_vs_scheduled():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    asap = ContentProfile(id="a", publish={"schedule": "asap_on_trigger"})
    assert next_best_time(now, asap) is None
    sched = ContentProfile(id="b", audience={"segment": "gen_z_millennial"},
                           publish={"schedule": "best_time"})
    when = next_best_time(now, sched)
    assert when is not None and when.hour == 19 and when >= now


def test_build_publish_meta_youtube():
    p = ContentProfile(id="bike", niche="cycling POV",
                       publish={"schedule": "asap_on_trigger", "hashtags": ["#mtb"],
                                "ai_disclosure": True, "made_for_kids": False})
    meta = build_publish_meta(p, "youtube_shorts")
    assert "#Shorts" in meta.title
    assert "#mtb" in meta.description
    assert "AI-generated" in meta.description       # disclosure note
    assert meta.privacy == "public"                 # asap -> public


def test_build_publish_meta_scheduled_private():
    p = ContentProfile(id="s", niche="x", audience={"segment": "parents"},
                       publish={"schedule": "best_time", "platforms": ["youtube_shorts"]})
    meta = build_publish_meta(p, "youtube_shorts")
    assert meta.privacy == "private" and meta.publish_at is not None


def test_dry_run_publisher():
    pub = DryRunPublisher("youtube_shorts")
    r = pub.publish("/tmp/x.mp4", PublishMeta(title="t"))
    assert r.ok and r.dry_run and r.url.startswith("https://youtube.com/shorts/")


# ---- op_publish ----

def test_op_publish_dry_run_records_and_consumes(tmp_path):
    prof = ContentProfile(id="bike", niche="cycling",
                          publish={"platforms": ["youtube_shorts"],
                                   "schedule": "asap_on_trigger", "hashtags": ["#Shorts"]})
    ctx = _ctx(tmp_path, prof)
    res = P.op_publish(ctx, "/tmp/draft.mp4", "youtube_shorts")  # dry_run default
    assert res.ok and res.outputs["dry_run"] is True
    assert res.outputs["url"].startswith("https://youtube.com/shorts/")
    assert ctx.ledger.quota_used("youtube", _day()) == 1600      # consumed
    assert any(a["kind"] == "published" for a in ctx.ledger.list_assets(ctx.run_id))


def test_op_publish_blocked_when_exhausted(tmp_path):
    prof = ContentProfile(id="bike", publish={"platforms": ["youtube_shorts"]})
    ctx = _ctx(tmp_path, prof)
    ctx.ledger.add_quota("youtube", _day(), 9600)   # only 400 left
    res = P.op_publish(ctx, "/tmp/draft.mp4", "youtube_shorts")
    assert res.ok is False and res.outputs["reason"] == "quota"
    assert ctx.ledger.quota_used("youtube", _day()) == 9600      # not consumed further
