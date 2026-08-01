"""Learning loop core: a Thompson-sampling bandit + a pre-publish scorer.

Dependency-light and fully testable. Production swaps behind the same shapes:
- Bandit  -> MABWiser ThompsonSampling (this is a Beta-Bernoulli sampler).
- Scorer  -> XGBoost + SHAP (this is a numpy logistic regression + coef weights).

The bandit keeps choosing better hook archetypes over time; the scorer ranks
candidate variants BEFORE publishing so the review gate shows the best of N.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Hook archetypes the bandit chooses among (research-backed short-form hooks).
HOOK_ARMS = ["text_overlay", "hard_cut", "music_drop", "pattern_break", "surprise"]

# Features the scorer reads from a candidate/post.
_CATEG = ["hook", "caption_style", "lut", "music_mood"]
_NUM = ["length_s"]


def reward_from_metrics(metrics: dict) -> float:
    """Map raw post metrics to a [0,1] reward (early retention preferred)."""
    if "retention3s" in metrics and metrics["retention3s"] is not None:
        return float(np.clip(metrics["retention3s"], 0.0, 1.0))
    length = float(metrics.get("length_s", 0) or 0)
    avd = float(metrics.get("avg_view_duration", 0) or 0)
    if length > 0 and avd > 0:
        return float(np.clip(avd / length, 0.0, 1.0))
    # fallback: engagement rate vs views
    views = float(metrics.get("views", 0) or 0)
    eng = float(metrics.get("likes", 0) + metrics.get("comments", 0)
                + metrics.get("shares", 0))
    return float(np.clip(eng / views, 0.0, 1.0)) if views > 0 else 0.0


class ThompsonBandit:
    """Beta-Bernoulli Thompson sampling over discrete arms, persisted in the ledger."""

    def __init__(self, ledger, scope: str = "hook", arms: Optional[list[str]] = None,
                 rng: Optional[np.random.Generator] = None):
        self.ledger = ledger
        self.scope = scope
        self.arms = arms or HOOK_ARMS
        self.rng = rng or np.random.default_rng()
        for a in self.arms:  # ensure rows exist
            if not any(r["arm"] == a for r in ledger.list_arms(scope)):
                ledger.set_arm(scope, a, 1.0, 1.0)

    def select(self) -> str:
        samples = {}
        for a in self.arms:
            alpha, beta = self.ledger.get_arm(self.scope, a)
            samples[a] = float(self.rng.beta(alpha, beta))
        return max(samples, key=samples.get)

    def update(self, arm: str, reward: float) -> None:
        reward = float(np.clip(reward, 0.0, 1.0))
        alpha, beta = self.ledger.get_arm(self.scope, arm)
        self.ledger.set_arm(self.scope, arm, alpha + reward, beta + (1.0 - reward))

    def stats(self) -> list[dict]:
        out = []
        for a in self.arms:
            alpha, beta = self.ledger.get_arm(self.scope, a)
            out.append({"arm": a, "alpha": alpha, "beta": beta,
                        "mean": alpha / (alpha + beta), "pulls": (alpha + beta) - 2.0})
        out.sort(key=lambda x: x["mean"], reverse=True)
        return out


@dataclass
class LogisticScorer:
    """Tiny logistic-regression 'will it land?' scorer over content features."""
    vocab: dict = field(default_factory=dict)      # "key=value" -> column index
    num_mean: dict = field(default_factory=dict)
    num_std: dict = field(default_factory=dict)
    weights: list = field(default_factory=list)
    bias: float = 0.0
    trained: bool = False

    def _vectorize(self, feats: dict) -> np.ndarray:
        x = np.zeros(len(self.vocab) + len(_NUM), dtype=float)
        for k in _CATEG:
            col = self.vocab.get(f"{k}={feats.get(k)}")
            if col is not None:
                x[col] = 1.0
        for i, k in enumerate(_NUM):
            mu, sd = self.num_mean.get(k, 0.0), self.num_std.get(k, 1.0) or 1.0
            x[len(self.vocab) + i] = (float(feats.get(k, 0) or 0) - mu) / sd
        return x

    def fit(self, rows: list[tuple[dict, int]], iters: int = 400, lr: float = 0.3) -> float:
        if not rows:
            return 0.0
        # build categorical vocab
        self.vocab = {}
        for feats, _ in rows:
            for k in _CATEG:
                key = f"{k}={feats.get(k)}"
                self.vocab.setdefault(key, len(self.vocab))
        # numeric standardization stats
        for k in _NUM:
            vals = np.array([float(f.get(k, 0) or 0) for f, _ in rows])
            self.num_mean[k] = float(vals.mean())
            self.num_std[k] = float(vals.std() or 1.0)
        X = np.array([self._vectorize(f) for f, _ in rows])
        y = np.array([float(lbl) for _, lbl in rows])
        w = np.zeros(X.shape[1])
        b = 0.0
        n = len(y)
        for _ in range(iters):
            z = X @ w + b
            p = 1.0 / (1.0 + np.exp(-z))
            grad_w = X.T @ (p - y) / n
            grad_b = float((p - y).mean())
            w -= lr * grad_w
            b -= lr * grad_b
        self.weights, self.bias, self.trained = list(w), float(b), True
        return self.accuracy(rows)

    def score(self, feats: dict) -> float:
        if not self.trained:
            return 0.5
        x = self._vectorize(feats)
        z = float(np.dot(x, np.array(self.weights)) + self.bias)
        return 1.0 / (1.0 + math.exp(-z))

    def accuracy(self, rows: list[tuple[dict, int]]) -> float:
        if not rows:
            return 0.0
        correct = sum(1 for f, lbl in rows if (self.score(f) >= 0.5) == bool(lbl))
        return correct / len(rows)

    def to_json(self) -> str:
        return json.dumps({"vocab": self.vocab, "num_mean": self.num_mean,
                           "num_std": self.num_std, "weights": self.weights,
                           "bias": self.bias, "trained": self.trained})

    @classmethod
    def from_json(cls, s: str) -> "LogisticScorer":
        d = json.loads(s)
        return cls(**d)


def rows_from_metrics(records: list[dict]) -> list[tuple[dict, int]]:
    """Turn logged post_metrics into (features, label) with label = above-median reward."""
    if not records:
        return []
    rewards = [reward_from_metrics({**r["metrics"], **r["features"]}) for r in records]
    med = float(np.median(rewards))
    rows = []
    for r, rew in zip(records, rewards):
        rows.append((r["features"], 1 if rew >= med else 0))
    return rows
