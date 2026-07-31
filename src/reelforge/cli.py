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
    input: Optional[str] = typer.Option(None, help="input video path"),
    demo: bool = typer.Option(False, help="synthesize a test clip and run"),
    profiles_dir: str = typer.Option("profiles", help="profiles directory"),
    work: str = typer.Option(".rf_work", help="working directory"),
    auto_approve: bool = typer.Option(False, help="skip the approval stop"),
) -> None:
    """Run the footage pipeline end to end (stops at the review gate)."""
    from .flows import run_footage  # lazy: avoids importing heavy deps for --help

    prof = load_profile(profile, profiles_dir=profiles_dir)
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
    result = run_footage(src, prof, work_root=work, auto_approve=auto_approve)
    typer.echo("")
    for k, v in result.items():
        typer.echo(f"  {k:14} {v}")
    if result.get("status") == "awaiting_approval":
        typer.echo(f"\nReview card: {result['review_card']}")
        typer.echo("Approve then publish (publishing is a later phase).")


if __name__ == "__main__":
    app()
