"""ReelForge CLI.

    reelforge doctor                        # check ffmpeg / deps
    reelforge profiles [--dir profiles]     # list ContentProfiles
    reelforge ops                           # list registered atomic ops
    reelforge run --profile bike_pov --input ride.mp4
    reelforge run --profile bike_pov --demo # synthesize a test clip and run
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .core import media
from .core.profile import load_profile
from .core.op import REGISTRY
from . import ops  # noqa: F401  (registers ops)

app = typer.Typer(add_completion=False, help="Generic short-form content pipeline.")


@app.command()
def doctor() -> None:
    """Check the runtime environment."""
    ok = media.have_ffmpeg()
    typer.echo(f"ffmpeg/ffprobe: {'OK' if ok else 'MISSING'}")
    try:
        import cv2  # noqa: F401
        typer.echo("opencv:        OK")
    except Exception:  # noqa: BLE001
        typer.echo("opencv:        MISSING")
    try:
        import scenedetect  # noqa: F401
        typer.echo("scenedetect:   OK")
    except Exception:  # noqa: BLE001
        typer.echo("scenedetect:   MISSING")
    try:
        import faster_whisper  # noqa: F401
        typer.echo("faster-whisper: OK (captions available)")
    except Exception:  # noqa: BLE001
        typer.echo("faster-whisper: absent (captions will be skipped)")
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def profiles(dir: str = typer.Option("profiles", help="profiles directory")) -> None:
    """List available ContentProfiles."""
    d = Path(dir)
    if not d.exists():
        typer.echo(f"no profiles dir: {d}")
        raise typer.Exit(code=1)
    for y in sorted(d.glob("*.yaml")):
        try:
            p = load_profile(y)
            typer.echo(f"{p.id:18} mode={p.source.mode.value:10} niche={p.niche}")
        except Exception as e:  # noqa: BLE001
            typer.echo(f"{y.name:18} ERROR: {e}")


@app.command()
def ops() -> None:
    """List registered atomic ops."""
    for name in sorted(REGISTRY):
        typer.echo(name)


@app.command()
def run(
    profile: str = typer.Option(..., help="profile id or path to yaml"),
    input: Optional[str] = typer.Option(None, help="input video path (footage mode)"),
    topic: Optional[str] = typer.Option(None, help="topic/brief (generative/hybrid mode)"),
    voice: Optional[str] = typer.Option(None, help="narration audio/video (hybrid mode)"),
    demo: bool = typer.Option(False, help="synthesize a test clip (footage mode)"),
    profiles_dir: str = typer.Option("profiles", help="profiles directory"),
    work: str = typer.Option(".rf_work", help="working directory"),
    auto_approve: bool = typer.Option(False, help="skip the approval stop"),
    publish: bool = typer.Option(False, help="publish after approval (needs --auto-approve)"),
    live: bool = typer.Option(False, help="real upload/generation instead of dry-run (needs creds)"),
) -> None:
    """Run the pipeline end to end (stops at the review gate). Routes by source.mode."""
    from .flows import run_footage, run_generative, run_hybrid  # lazy

    prof = load_profile(profile, profiles_dir=profiles_dir)

    creds = None
    if live:
        from .core.credentials import load_credentials
        creds = load_credentials()
        if not creds:
            typer.echo("--live set but no credentials found; run `reelforge setup`.")

    if prof.source.mode.value == "generative":
        typer.echo(f"running generative profile '{prof.id}'"
                   + (f" on topic '{topic}'" if topic else ""))
        result = run_generative(prof, topic=topic, work_root=work,
                                auto_approve=auto_approve, publish=publish,
                                dry_run=not live, creds=creds)
    elif prof.source.mode.value == "hybrid":
        typer.echo(f"running hybrid profile '{prof.id}'"
                   + (f" on topic '{topic}'" if topic else "")
                   + (f" with narration {voice}" if voice else " (generated narration)"))
        result = run_hybrid(prof, topic=topic, voice_input=voice, work_root=work,
                            auto_approve=auto_approve, publish=publish,
                            dry_run=not live, creds=creds)
    else:
        src = input
        if demo or not src:
            if not media.have_ffmpeg():
                typer.echo("ffmpeg required for --demo"); raise typer.Exit(code=1)
            demo_path = Path(work) / "_demo_input.mp4"
            typer.echo("synthesizing demo clip...")
            media.synth_test_clip(demo_path, duration=14.0, fps=30, size="640x360")
            src = str(demo_path)
        if not Path(src).exists():
            typer.echo(f"input not found: {src}"); raise typer.Exit(code=1)
        typer.echo(f"running profile '{prof.id}' on {src}")
        result = run_footage(src, prof, work_root=work, auto_approve=auto_approve,
                             publish=publish, dry_run=not live, creds=creds)
    typer.echo("")
    for k, v in result.items():
        typer.echo(f"  {k:14} {v}")
    if result.get("status") == "awaiting_approval":
        typer.echo(f"\nReview card: {result['review_card']}")
        typer.echo(f"Approve, then: reelforge publish --run {result['run_id']} "
                   f"--profile {prof.id} --work {work}")


@app.command()
def publish(
    run: str = typer.Option(..., help="run id to publish"),
    profile: str = typer.Option(..., help="profile id or path"),
    profiles_dir: str = typer.Option("profiles", help="profiles directory"),
    work: str = typer.Option(".rf_work", help="working directory"),
    live: bool = typer.Option(False, help="real upload instead of dry-run (needs creds)"),
) -> None:
    """Publish an approved run's draft to its target platforms (dry-run by default)."""
    from .flows import publish_run

    prof = load_profile(profile, profiles_dir=profiles_dir)
    creds = None
    if live:
        from .core.credentials import load_credentials
        creds = load_credentials()
    result = publish_run(run, prof, work_root=work, dry_run=not live, creds=creds)
    for k, v in result.items():
        typer.echo(f"  {k:14} {v}")


@app.command()
def setup() -> None:
    """Show per-component go-live TODOs and which credentials are set."""
    from .core.credentials import env_status
    typer.echo("ReelForge go-live checklist (all optional; unset = dry-run/fallback):\n")
    for r in env_status():
        mark = "OK " if r["ready"] else "TODO"
        typer.echo(f"[{mark}] {r['component']}")
        typer.echo(f"       account: {r['account']}")
        typer.echo(f"       get key: {r['where']}")
        typer.echo(f"       env:     {', '.join(r['set']) or '(none set)'}"
                   + (f"  missing: {', '.join(r['missing_required'])}" if r["missing_required"] else ""))
        typer.echo(f"       unlocks: {r['gate']}\n")


learn_app = typer.Typer(add_completion=False, help="Learning loop: hook bandit + pre-publish scorer.")
app.add_typer(learn_app, name="learn")


def _ctx(work: str, run_label: str = "learn"):
    from .core.context import OpContext
    from .core.profile import ContentProfile
    from .core.state import Ledger
    from .core.storage import Storage
    led = Ledger(Path(work) / "reelforge.db")
    rid = led.create_run(run_label)
    return OpContext(run_id=rid, profile=ContentProfile(id=run_label),
                     storage=Storage(Path(work) / rid), ledger=led)


@learn_app.command("insights")
def learn_insights(work: str = typer.Option(".rf_work", help="working directory")) -> None:
    """Show the hook bandit ranking + logged-post count + scorer status."""
    from .core.state import Ledger
    from .core.learn import ThompsonBandit, LogisticScorer
    led = Ledger(Path(work) / "reelforge.db")
    typer.echo("Hook bandit (ranked by posterior mean):")
    for s in ThompsonBandit(led).stats():
        bar = "#" * int(round(s["mean"] * 20))
        typer.echo(f"  {s['arm']:14} mean={s['mean']:.3f} pulls={s['pulls']:.0f}  {bar}")
    typer.echo(f"\nlogged posts: {len(led.list_metrics())}")
    sp = Path(work) / "scorer.json"
    typer.echo(f"scorer: {'trained (' + sp.name + ')' if sp.exists() else 'not trained'}")
    led.close()


@learn_app.command("ingest")
def learn_ingest(
    run: str = typer.Option(..., help="run id the post came from"),
    platform: str = typer.Option("youtube_shorts"),
    hook: str = typer.Option(..., help="hook archetype used"),
    caption_style: str = typer.Option("karaoke_bold"),
    lut: str = typer.Option("none"),
    music_mood: str = typer.Option("none"),
    length: float = typer.Option(0.0, help="video length seconds"),
    views: int = typer.Option(0),
    watch: float = typer.Option(0.0, help="avg view duration seconds"),
    retention: Optional[float] = typer.Option(None, help="first-3s retention 0..1"),
    work: str = typer.Option(".rf_work"),
) -> None:
    """Log a published post's outcome and update the bandit."""
    from .ops import learn as L
    ctx = _ctx(work)
    ctx.run_id = run  # attribute the metrics row to the real run
    features = {"hook": hook, "caption_style": caption_style, "lut": lut,
                "music_mood": music_mood, "length_s": length}
    metrics = {"views": views, "avg_view_duration": watch, "length_s": length}
    if retention is not None:
        metrics["retention3s"] = retention
    res = L.op_log_metrics(ctx, run, platform, features, metrics)
    typer.echo(f"logged; reward={res.outputs['reward']:.3f} (hook '{hook}')")
    ctx.ledger.close()


@learn_app.command("train")
def learn_train(work: str = typer.Option(".rf_work")) -> None:
    """Retrain the pre-publish scorer from logged metrics."""
    from .ops import learn as L
    ctx = _ctx(work)
    res = L.op_train_scorer(ctx)
    typer.echo(f"trained on {res.outputs['n_rows']} row(s), accuracy={res.outputs['accuracy']:.2f}")
    ctx.ledger.close()


@app.command()
def batch(
    profiles: str = typer.Option(..., help="comma-separated profile ids"),
    topic: Optional[str] = typer.Option(None, help="topic for generative/hybrid channels"),
    profiles_dir: str = typer.Option("profiles", help="profiles directory"),
    work: str = typer.Option(".rf_work", help="working directory"),
    auto_approve: bool = typer.Option(False),
    publish: bool = typer.Option(False),
    live: bool = typer.Option(False),
    enforce_budget: bool = typer.Option(False, help="trim generative scenes to stay in budget"),
) -> None:
    """Run multiple channels/profiles in one pass (multi-channel scale)."""
    from .flows import run_batch
    creds = None
    if live:
        from .core.credentials import load_credentials
        creds = load_credentials()
    items = [{"profile": p.strip(), "topic": topic} for p in profiles.split(",") if p.strip()]
    results = run_batch(items, profiles_dir=profiles_dir, work_root=work,
                        auto_approve=auto_approve, publish=publish, dry_run=not live,
                        creds=creds, enforce_budget=enforce_budget)
    for r in results:
        typer.echo(f"  {r.get('profile'):18} {r.get('status'):18} "
                   + (r.get('error', '') or f"draft={r.get('draft','')}"))


@app.command()
def report(
    work: str = typer.Option(".rf_work", help="working directory"),
    html: Optional[str] = typer.Option(None, help="write an HTML dashboard to this path"),
) -> None:
    """Print a status/spend/quota/bandit summary; optionally write an HTML dashboard."""
    from .core.state import Ledger
    from .core.report import build_report, render_html
    led = Ledger(Path(work) / "reelforge.db")
    rep = build_report(led)
    sp = rep["spend"]
    typer.echo(f"runs: {rep['runs_total']}  |  status: {rep['status_counts']}")
    typer.echo(f"spend est all-time: ${sp['all_time']['est_usd']:.2f} "
               f"(charged ${sp['all_time']['charged_usd']:.2f})  |  today: ${sp['today']['est_usd']:.2f}")
    typer.echo("quota today: " + ", ".join(
        f"{p}={q['used']}/{q['limit']}" for p, q in rep["quota_today"].items()))
    if rep["bandit"]:
        top = rep["bandit"][0]
        typer.echo(f"top hook: {top['arm']} (mean {top['mean']:.3f})")
    if html:
        Path(html).write_text(render_html(rep), encoding="utf-8")
        typer.echo(f"dashboard -> {html}")
    led.close()


if __name__ == "__main__":
    app()
