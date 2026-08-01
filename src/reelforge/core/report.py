"""Dashboard/report — summarize the ledger: runs, spend, quota, bandit, top posts.

`build_report` returns a plain dict (JSON/CLI friendly); `render_html` turns it
into a self-contained static dashboard page.
"""
from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timezone

from .learn import ThompsonBandit, reward_from_metrics
from .publish import PLATFORMS


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_report(ledger) -> dict:
    runs = ledger.list_runs()
    status_counts = Counter(r["status"] for r in runs)
    day = _today()
    quota = {}
    for platform, spec in PLATFORMS.items():
        key = spec.get("quota_key", platform)
        used = ledger.quota_used(key, day)
        quota[platform] = {"used": used, "limit": spec.get("limit", 0),
                           "remaining": max(0, spec.get("limit", 0) - used)}
    metrics = ledger.list_metrics()
    top = sorted(
        ({"post_id": m["post_id"], "platform": m["platform"],
          "hook": m["features"].get("hook"),
          "reward": round(reward_from_metrics({**m["metrics"], **m["features"]}), 3)}
         for m in metrics),
        key=lambda x: x["reward"], reverse=True,
    )[:10]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_total": len(runs),
        "status_counts": dict(status_counts),
        "spend": {"all_time": ledger.total_spend(), "today": ledger.day_spend(day)},
        "quota_today": quota,
        "bandit": ThompsonBandit(ledger).stats(),
        "top_posts": top,
        "recent_runs": [
            {"run_id": r["run_id"], "profile": r["profile_id"], "status": r["status"],
             "hook": r["meta"].get("hook")}
            for r in runs[-10:][::-1]
        ],
    }


def render_html(report: dict) -> str:
    def esc(x):
        return html.escape(str(x))

    def rows(items, cols):
        out = []
        for it in items:
            out.append("<tr>" + "".join(f"<td>{esc(it.get(c, ''))}</td>" for c in cols) + "</tr>")
        return "\n".join(out) or "<tr><td colspan=99 class=muted>(none)</td></tr>"

    st = report["status_counts"]
    status_html = " ".join(f"<span class=chip>{esc(k)}: <b>{esc(v)}</b></span>"
                           for k, v in st.items()) or "<span class=muted>no runs</span>"
    quota_html = rows(
        [{"platform": p, **q} for p, q in report["quota_today"].items()],
        ["platform", "used", "limit", "remaining"])
    bandit_html = rows(
        [{"arm": b["arm"], "mean": round(b["mean"], 3), "pulls": int(b["pulls"])}
         for b in report["bandit"]], ["arm", "mean", "pulls"])
    posts_html = rows(report["top_posts"], ["post_id", "platform", "hook", "reward"])
    runs_html = rows(report["recent_runs"], ["run_id", "profile", "status", "hook"])
    sp = report["spend"]
    return f"""<!DOCTYPE html><html><head><meta charset=utf-8>
<title>ReelForge dashboard</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0a0b10;color:#e7e9f0;margin:0;padding:32px}}
h1{{margin:0 0 4px}} h2{{margin:28px 0 8px;font-size:1.05rem;color:#9aa1b4}}
.muted{{color:#6b7288}} .chip{{background:#151824;border:1px solid #262b3d;border-radius:8px;padding:4px 10px;margin-right:6px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem;background:#10121a;border:1px solid #262b3d;border-radius:10px;overflow:hidden}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid #262b3d}} th{{background:#1b1f2e;color:#9aa1b4}}
.cards{{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}}
.card{{background:#151824;border:1px solid #262b3d;border-radius:12px;padding:16px 20px;min-width:160px}}
.card .n{{font-size:1.6rem;font-weight:800}} .g{{background:linear-gradient(120deg,#ff5c8a,#7c5cff,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent}}
</style></head><body>
<h1>Reel<span class=g>Forge</span> dashboard</h1>
<div class=muted>generated {esc(report['generated_at'])}</div>
<div class=cards>
  <div class=card><div class=muted>runs</div><div class=n>{esc(report['runs_total'])}</div></div>
  <div class=card><div class=muted>spend est (all-time)</div><div class=n>${sp['all_time']['est_usd']:.2f}</div></div>
  <div class=card><div class=muted>charged (all-time)</div><div class=n>${sp['all_time']['charged_usd']:.2f}</div></div>
  <div class=card><div class=muted>spend today</div><div class=n>${sp['today']['est_usd']:.2f}</div></div>
</div>
<h2>Run status</h2><div>{status_html}</div>
<h2>Quota today</h2><table><tr><th>platform</th><th>used</th><th>limit</th><th>remaining</th></tr>{quota_html}</table>
<h2>Hook bandit</h2><table><tr><th>arm</th><th>mean</th><th>pulls</th></tr>{bandit_html}</table>
<h2>Top posts</h2><table><tr><th>post</th><th>platform</th><th>hook</th><th>reward</th></tr>{posts_html}</table>
<h2>Recent runs</h2><table><tr><th>run</th><th>profile</th><th>status</th><th>hook</th></tr>{runs_html}</table>
</body></html>"""
