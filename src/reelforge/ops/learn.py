"""Learn ops — close the loop: pick hooks, log outcomes, train the scorer.

Classical/statistical, no LLM. `op_select_hook` and `op_log_metrics` drive the
bandit; `op_train_scorer`/`op_score_candidate` drive the pre-publish scorer.
The scorer is persisted per work-root (next to the ledger db) so it's shared
across runs.
"""
from __future__ import annotations

from pathlib import Path

from ..core.context import OpContext
from ..core.learn import (HOOK_ARMS, LogisticScorer, ThompsonBandit,
                          reward_from_metrics, rows_from_metrics)
from ..core.op import op
from ..core.types import OpResult


def _scorer_path(ctx: OpContext) -> Path:
    return Path(ctx.ledger.db_path).parent / "scorer.json"


@op("select_hook")
def op_select_hook(ctx: OpContext, scope: str = "hook") -> OpResult:
    """Pick the next hook archetype via the bandit. One job: exploration/exploitation."""
    bandit = ThompsonBandit(ctx.ledger, scope=scope)
    arm = bandit.select()
    return OpResult(outputs={"hook": arm, "arms": bandit.stats()},
                    message=f"selected hook '{arm}'")


@op("log_metrics")
def op_log_metrics(ctx: OpContext, post_id: str, platform: str, features: dict,
                   metrics: dict, scope: str = "hook") -> OpResult:
    """Log a published post's outcome + update the bandit. One job: record reward."""
    ctx.ledger.add_metrics(ctx.run_id, post_id, platform, features, metrics)
    reward = reward_from_metrics({**metrics, **features})
    hook = features.get("hook")
    if hook in HOOK_ARMS:
        ThompsonBandit(ctx.ledger, scope=scope).update(hook, reward)
    return OpResult(outputs={"reward": reward, "hook": hook},
                    metrics={"reward": reward},
                    message=f"logged {platform} post; reward={reward:.3f}")


@op("fetch_analytics")
def op_fetch_analytics(ctx: OpContext, post_id: str, platform: str,
                       provider=None, creds: dict | None = None) -> OpResult:
    """Fetch post performance. Injectable provider; offline returns {} gracefully."""
    if provider is None:
        return OpResult(ok=True, outputs={"metrics": {}},
                        message="no analytics provider (offline); supply metrics manually")
    try:
        m = provider() or {}
    except Exception as e:  # noqa: BLE001
        return OpResult(ok=True, outputs={"metrics": {}}, message=f"analytics failed: {e}")
    return OpResult(outputs={"metrics": m}, message=f"fetched {len(m)} metric(s)")


@op("train_scorer")
def op_train_scorer(ctx: OpContext) -> OpResult:
    """Retrain the pre-publish scorer from logged metrics. One job: fit model."""
    records = ctx.ledger.list_metrics()
    rows = rows_from_metrics(records)
    scorer = LogisticScorer()
    acc = scorer.fit(rows) if rows else 0.0
    if rows:
        _scorer_path(ctx).write_text(scorer.to_json(), encoding="utf-8")
    return OpResult(outputs={"n_rows": len(rows), "accuracy": acc, "trained": bool(rows)},
                    metrics={"n_rows": float(len(rows)), "accuracy": acc},
                    message=f"trained on {len(rows)} row(s), acc={acc:.2f}")


@op("score_candidate")
def op_score_candidate(ctx: OpContext, features: dict) -> OpResult:
    """Predict 'will it land?' for a candidate. One job: pre-publish score."""
    p = _scorer_path(ctx)
    scorer = LogisticScorer.from_json(p.read_text()) if p.exists() else LogisticScorer()
    prob = scorer.score(features)
    return OpResult(outputs={"score": prob, "trained": scorer.trained},
                    metrics={"score": prob}, message=f"score={prob:.3f}")
