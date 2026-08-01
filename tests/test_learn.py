"""Learning loop: reward mapping, Thompson bandit, logistic scorer, ops."""
from __future__ import annotations

from collections import Counter

import numpy as np

from reelforge.core.state import Ledger
from reelforge.core.learn import (HOOK_ARMS, ThompsonBandit, LogisticScorer,
                                  reward_from_metrics, rows_from_metrics)
from reelforge.ops import learn as L


# ---- reward mapping ----

def test_reward_from_metrics():
    assert reward_from_metrics({"retention3s": 0.7}) == 0.7
    assert reward_from_metrics({"avg_view_duration": 15, "length_s": 30}) == 0.5
    assert abs(reward_from_metrics({"views": 100, "likes": 5, "comments": 3,
                                    "shares": 2}) - 0.1) < 1e-9
    assert reward_from_metrics({}) == 0.0


# ---- bandit ----

def test_bandit_prefers_rewarding_arm(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    b = ThompsonBandit(led, rng=np.random.default_rng(0))
    for _ in range(40):
        b.update("hard_cut", 1.0)
    for a in HOOK_ARMS:
        if a != "hard_cut":
            for _ in range(10):
                b.update(a, 0.0)
    assert b.stats()[0]["arm"] == "hard_cut"          # top by posterior mean
    picks = Counter(b.select() for _ in range(100))
    assert picks.most_common(1)[0][0] == "hard_cut"   # exploits the winner


def test_bandit_persists_across_instances(tmp_path):
    led = Ledger(tmp_path / "db.sqlite")
    ThompsonBandit(led).update("surprise", 1.0)
    a, beta = Ledger(tmp_path / "db.sqlite").get_arm("hook", "surprise")
    assert a == 2.0 and beta == 1.0


# ---- scorer ----

def test_scorer_learns_separable():
    rows = []
    for _ in range(10):
        rows.append(({"hook": "good", "caption_style": "bold", "lut": "x",
                      "music_mood": "up", "length_s": 20}, 1))
        rows.append(({"hook": "bad", "caption_style": "plain", "lut": "y",
                      "music_mood": "down", "length_s": 50}, 0))
    s = LogisticScorer()
    acc = s.fit(rows)
    assert acc == 1.0
    assert s.score(rows[0][0]) > s.score(rows[1][0])
    # round-trips through JSON
    s2 = LogisticScorer.from_json(s.to_json())
    assert abs(s2.score(rows[0][0]) - s.score(rows[0][0])) < 1e-9


def test_rows_from_metrics_median_label():
    recs = [
        {"features": {"hook": "a"}, "metrics": {"retention3s": 0.9}},
        {"features": {"hook": "b"}, "metrics": {"retention3s": 0.1}},
    ]
    rows = rows_from_metrics(recs)
    labels = {f["hook"]: lbl for f, lbl in rows}
    assert labels["a"] == 1 and labels["b"] == 0


# ---- ops ----

def test_ops_select_log_train_score(ctx):
    arm = L.op_select_hook(ctx).outputs["hook"]
    assert arm in HOOK_ARMS

    # log a spread of outcomes tying hook -> reward
    for i in range(6):
        good = i % 2 == 0
        feats = {"hook": "hard_cut" if good else "surprise", "caption_style": "b",
                 "lut": "teal", "music_mood": "up", "length_s": 20}
        mets = {"retention3s": 0.8 if good else 0.2, "views": 1000}
        L.op_log_metrics(ctx, f"post{i}", "youtube_shorts", feats, mets)

    tr = L.op_train_scorer(ctx)
    assert tr.outputs["n_rows"] == 6 and tr.outputs["trained"] is True

    hi = L.op_score_candidate(ctx, {"hook": "hard_cut", "caption_style": "b",
                                    "lut": "teal", "music_mood": "up", "length_s": 20})
    lo = L.op_score_candidate(ctx, {"hook": "surprise", "caption_style": "b",
                                    "lut": "teal", "music_mood": "up", "length_s": 20})
    assert hi.outputs["score"] >= lo.outputs["score"]
    # bandit learned hard_cut is better
    assert ThompsonBandit(ctx.ledger).stats()[0]["arm"] == "hard_cut"


def test_fetch_analytics_offline_graceful(ctx):
    res = L.op_fetch_analytics(ctx, "vid1", "youtube_shorts")
    assert res.ok and res.outputs["metrics"] == {}
