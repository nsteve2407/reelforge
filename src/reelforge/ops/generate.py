"""Generate ops — brief -> script -> scene clips / voice / music. One job each.

`op_write_script` is the one genuine LLM touch (Claude when ANTHROPIC_API_KEY is
set, deterministic template otherwise). The media ops delegate to a generator
(dry-run by default, real fal/MiniMax when creds are supplied).
"""
from __future__ import annotations

import os

from ..core.context import OpContext
from ..core.generate import get_generator
from ..core.op import op
from ..core.types import OpResult

# A simple, safe kid-friendly rhyme scaffold used by the offline fallback.
_RHYME_LINES = [
    "Little {subj} bounces in the morning sun",
    "Clap your hands and wiggle, everyone",
    "Up goes the {subj}, round and round",
    "Down come the giggles, what a happy sound",
    "Count with me: one, two, three, four",
    "Sing it again, let's do one more",
    "Twinkle colors dancing in the sky",
    "Wave to the {subj} as we say goodbye",
]


def _fallback_script(profile, topic, n: int, per_s: float) -> dict:
    subj = (topic or profile.niche or "friends").split()[0].lower()
    title = (topic or profile.niche or profile.id).strip().title()
    scenes = []
    narration = []
    for i in range(n):
        text = _RHYME_LINES[i % len(_RHYME_LINES)].format(subj=subj)
        scenes.append({"text": text, "seconds": round(per_s, 2)})
        narration.append(text)
    return {"title": title, "narration": " ".join(narration), "scenes": scenes}


def _claude_script(profile, topic, n: int, per_s: float) -> dict:
    import anthropic  # lazy

    client = anthropic.Anthropic()
    prompt = (
        f"Write a short, wholesome, original {profile.niche or 'kids'} rhyme for a "
        f"vertical video. Topic: {topic or profile.niche}. Exactly {n} short lines "
        f"(one scene each, <=10 words). Return ONLY the lines, one per line."
    )
    msg = client.messages.create(model="claude-sonnet-4-5", max_tokens=400,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    lines = [ln.strip("-• ").strip() for ln in text.splitlines() if ln.strip()][:n]
    while len(lines) < n:
        lines.append("La la la, sing along with me")
    scenes = [{"text": ln, "seconds": round(per_s, 2)} for ln in lines]
    return {"title": (topic or profile.niche or profile.id).title(),
            "narration": " ".join(lines), "scenes": scenes}


@op("write_script")
def op_write_script(ctx: OpContext, topic: str | None = None,
                    n_scenes: int | None = None) -> OpResult:
    """Draft the script/scene list. Claude if keyed, else template fallback."""
    p = ctx.profile
    n = int(n_scenes or p.generate.animation.get("scenes_per_video", 6) or 6)
    min_len, max_len = p.edit.length_s
    total = min(max_len, max(min_len, n * 4.0))
    per_s = total / n
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            script = _claude_script(p, topic, n, per_s)
            src = "claude"
        except Exception as e:  # noqa: BLE001
            ctx.log("write_script", "warn", f"claude failed, fallback: {e}")
            script, src = _fallback_script(p, topic, n, per_s), "fallback"
    else:
        script, src = _fallback_script(p, topic, n, per_s), "fallback"
    return OpResult(outputs={"script": script, "total_s": total, "source": src},
                    metrics={"n_scenes": float(n), "total_s": total},
                    message=f"{n}-scene script ({src}), {total:.0f}s")


@op("gen_scene_clip")
def op_gen_scene_clip(ctx: OpContext, index: int, prompt: str,
                      target_w_h: tuple[int, int], seconds: float,
                      provider: str | None = None, dry_run: bool = True,
                      creds: dict | None = None) -> OpResult:
    """Generate one animated scene clip. One job: a scene."""
    gen = get_generator(provider, dry_run=dry_run,
                        creds=creds.get(provider) if isinstance(creds, dict) and provider in creds else creds)
    out = ctx.storage.path("generate", f"scene{index}.mp4")
    res = gen.video(str(out), prompt, w=int(target_w_h[0]), h=int(target_w_h[1]),
                    seconds=seconds, index=index)
    return OpResult(outputs={"clip": res.path, "provider": res.provider},
                    artifacts={"scene": res.path}, message=res.message)


@op("gen_voiceover")
def op_gen_voiceover(ctx: OpContext, text: str, seconds: float,
                     provider: str | None = None, dry_run: bool = True,
                     creds: dict | None = None) -> OpResult:
    """Generate narration audio. One job: voiceover."""
    gen = get_generator(provider, dry_run=dry_run,
                        creds=creds.get(provider) if isinstance(creds, dict) and provider in creds else creds)
    out = ctx.storage.path("generate", "voice.m4a")
    res = gen.voice(str(out), text, seconds=seconds)
    return OpResult(outputs={"audio": res.path, "provider": res.provider},
                    artifacts={"voice": res.path}, message=res.message)


@op("gen_music")
def op_gen_music(ctx: OpContext, mood: str, seconds: float,
                 provider: str | None = None, dry_run: bool = True,
                 creds: dict | None = None) -> OpResult:
    """Generate a music bed. One job: music."""
    gen = get_generator(provider, dry_run=dry_run,
                        creds=creds.get(provider) if isinstance(creds, dict) and provider in creds else creds)
    out = ctx.storage.path("generate", "music.m4a")
    res = gen.music(str(out), mood=mood, seconds=seconds)
    return OpResult(outputs={"audio": res.path, "provider": res.provider},
                    artifacts={"music": res.path}, message=res.message)
