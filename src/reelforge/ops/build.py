"""Build ops — turn ranked highlights into a finished vertical draft.

Deterministic ffmpeg/opencv editing, NO LLM. Each op = one responsibility:
select -> cut -> reframe -> grade -> caption -> render. Written for the OLD
ffmpeg 3.4 (only widely-supported filters: crop/scale/eq/curves/colorbalance/
subtitles/concat).
"""
from __future__ import annotations

from pathlib import Path

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import Caption, Highlight, OpResult, Segment

# ---- named color-grade looks (portable filters; no external .cube needed) ----
_LOOKS: dict[str, str] = {
    "teal_orange_punch": "colorbalance=rs=-0.15:bs=0.15:rh=0.15:bh=-0.15,eq=saturation=1.2:contrast=1.06",
    "vivid_action": "eq=saturation=1.35:contrast=1.12:brightness=0.02",
    "warm_storybook": "colorbalance=rm=0.10:gm=0.04:bm=-0.06,eq=saturation=1.10:brightness=0.03",
    "clean_bright": "eq=brightness=0.04:contrast=1.05:saturation=1.05",
    "none": "",
}


@op("select_clips")
def op_select_clips(ctx: OpContext, highlights: list[Highlight], profile) -> OpResult:
    """Pick & order the highlights to use. One job: selection (pure logic)."""
    min_len, max_len = profile.edit.length_s
    max_clips = max(1, profile.edit.clips_per_video[1])
    chosen = list(highlights[:max_clips])  # already score-sorted desc

    def _clamp(h: Highlight) -> Segment:
        start = max(0.0, h.start_s)
        end = h.end_s
        if end - start > max_len:
            end = start + max_len
        if end - start < min_len:
            end = start + min_len
        return Segment(start, end)

    segs = [_clamp(h) for h in chosen]
    if profile.edit.hook_first and segs:
        head, tail = segs[0], sorted(segs[1:], key=lambda s: s.start_s)
        segs = [head] + tail
    else:
        segs = sorted(segs, key=lambda s: s.start_s)
    return OpResult(outputs={"segments": segs}, metrics={"n_selected": float(len(segs))},
                    message=f"selected {len(segs)} clip(s)")


@op("cut")
def op_cut(ctx: OpContext, src: str, segment: Segment, name: str = "clip") -> OpResult:
    """Extract [start,end) from the source. One job: trim."""
    out = ctx.storage.path("build", f"{name}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    media.run([
        "ffmpeg", "-y", "-i", str(src),
        "-ss", f"{segment.start_s:.3f}", "-t", f"{segment.duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(out),
    ])
    return OpResult(outputs={"clip": str(out)}, artifacts={"clip": str(out)},
                    message=f"cut {segment.start_s:.1f}-{segment.end_s:.1f}s")


@op("reframe")
def op_reframe(ctx: OpContext, src: str, target_w_h: tuple[int, int],
               mode: str = "center") -> OpResult:
    """Center-crop to target aspect, then scale to exact target. One job: reframe."""
    w, h = int(target_w_h[0]), int(target_w_h[1])
    w -= w % 2
    h -= h % 2
    out = ctx.storage.path("build", f"{Path(src).stem}_rf.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})',"
        f"scale={w}:{h},setsar=1"
    )
    media.run([
        "ffmpeg", "-y", "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out),
    ])
    return OpResult(outputs={"path": str(out), "w": w, "h": h},
                    artifacts={"reframed": str(out)}, message=f"reframed {w}x{h}")


@op("color_grade")
def op_color_grade(ctx: OpContext, src: str, look: str) -> OpResult:
    """Apply a named color look. One job: grade."""
    out = ctx.storage.path("build", f"{Path(src).stem}_g.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    filt = _LOOKS.get(look)
    if not filt:  # 'none' or unknown -> passthrough copy
        import shutil
        shutil.copy2(src, out)
        return OpResult(outputs={"path": str(out)}, artifacts={"graded": str(out)},
                        message=f"look '{look}' -> passthrough")
    media.run([
        "ffmpeg", "-y", "-i", str(src), "-vf", filt,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", str(out),
    ])
    return OpResult(outputs={"path": str(out)}, artifacts={"graded": str(out)},
                    message=f"look '{look}'")


def _ts(t: float) -> str:
    """ASS timestamp H:MM:SS.cc"""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(captions: list[Caption], style: str = "karaoke_bold",
              play_w: int = 1080, play_h: int = 1920) -> str:
    """Return valid ASS subtitle text for the given cues. Pure/testable."""
    bold = 1 if "bold" in style else 0
    fontsize = int(play_h * 0.055)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_w}\nPlayResY: {play_h}\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        f"Style: Default,Arial,{fontsize},&H00FFFFFF,&H00000000,&H64000000,"
        f"{bold},1,3,1,2,40,40,{int(play_h*0.10)}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in captions:
        text = c.text.replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ts(c.start_s)},{_ts(c.end_s)},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + ("\n" if lines else "")


@op("captions")
def op_captions(ctx: OpContext, src: str, style: str = "karaoke_bold",
                lang: str = "en") -> OpResult:
    """Burn captions if a transcriber is available; else pass through. One job: captions."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:  # noqa: BLE001 - graceful when captions extra not installed
        out = ctx.storage.path("build", f"{Path(src).stem}_cap.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(src, out)
        return OpResult(outputs={"path": str(out), "captioned": False},
                        artifacts={"captioned": str(out)},
                        message="captions skipped (no transcriber)")

    # transcribe -> ASS -> burn (runs only when faster-whisper is installed)
    wav = media.extract_audio_wav(src, ctx.storage.path("build", "cap.wav"))
    model = WhisperModel("small", device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language=lang, word_timestamps=True)
    caps: list[Caption] = []
    for seg in segments:
        caps.append(Caption(float(seg.start), float(seg.end), seg.text.strip()))
    info = media.probe(src)
    ass = build_ass(caps, style, info.width, info.height)
    ass_path = ctx.storage.write_text(ass, "build", "captions.ass")
    out = ctx.storage.path("build", f"{Path(src).stem}_cap.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    esc = str(ass_path).replace(":", "\\:").replace("'", "\\'")
    media.run([
        "ffmpeg", "-y", "-i", str(src), "-vf", f"subtitles='{esc}'",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", str(out),
    ])
    return OpResult(outputs={"path": str(out), "captioned": True},
                    artifacts={"captioned": str(out)}, message=f"burned {len(caps)} cues")


@op("render")
def op_render(ctx: OpContext, clips: list[str], name: str = "draft") -> OpResult:
    """Concatenate clips into the final draft. One job: render."""
    if not clips:
        return OpResult(ok=False, message="no clips to render")
    out = ctx.storage.path(f"{name}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        import shutil
        shutil.copy2(clips[0], out)
    else:
        # concat filter re-encode: robust to differing params across clips
        cmd = ["ffmpeg", "-y"]
        for c in clips:
            cmd += ["-i", str(c)]
        n = len(clips)
        streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
        cmd += [
            "-filter_complex", f"{streams}concat=n={n}:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(out),
        ]
        media.run(cmd)
    return OpResult(outputs={"draft": str(out)}, artifacts={"draft": str(out)},
                    message=f"rendered {len(clips)} clip(s)")


@op("mux_audio")
def op_mux_audio(ctx: OpContext, video: str, tracks: list[dict],
                 name: str = "muxed") -> OpResult:
    """Mix narration/music onto a video's timeline. One job: audio mux.

    `tracks` = [{"path": str, "gain": float}]. Replaces the video's own audio.
    """
    tracks = [t for t in tracks if t and t.get("path")]
    if not tracks:
        return OpResult(ok=False, message="no audio tracks to mux")
    out = ctx.storage.path("build", f"{name}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(video)]
    for t in tracks:
        cmd += ["-i", str(t["path"])]
    if len(tracks) == 1:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        vol = [f"[{i + 1}:a:0]volume={t.get('gain', 1.0)}[a{i}]"
               for i, t in enumerate(tracks)]
        mix_in = "".join(f"[a{i}]" for i in range(len(tracks)))
        fc = ";".join(vol) + ";" + mix_in + \
            f"amix=inputs={len(tracks)}:duration=longest[a]"
        cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-shortest", str(out)]
    media.run(cmd)
    return OpResult(outputs={"path": str(out)}, artifacts={"muxed": str(out)},
                    message=f"muxed {len(tracks)} audio track(s)")


@op("captions_from_script")
def op_captions_from_script(ctx: OpContext, video: str, scenes: list[dict],
                            style: str = "singalong_lyrics") -> OpResult:
    """Burn captions from known scene text+timings (no transcriber). One job: captions."""
    caps: list[Caption] = []
    t = 0.0
    for s in scenes:
        dur = float(s.get("seconds", 2.0))
        caps.append(Caption(t, t + dur, str(s.get("text", "")).strip()))
        t += dur
    info = media.probe(video)
    ass = build_ass(caps, style, info.width, info.height)
    ass_path = ctx.storage.write_text(ass, "build", "script_captions.ass")
    out = ctx.storage.path("build", f"{Path(video).stem}_cap.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    esc = str(ass_path).replace(":", "\\:").replace("'", "\\'")
    try:
        media.run(["ffmpeg", "-y", "-i", str(video), "-vf", f"subtitles='{esc}'",
                   "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", str(out)])
        captioned = True
        msg = f"burned {len(caps)} caption(s)"
    except media.FFmpegError:
        import shutil
        shutil.copy2(video, out)
        captioned = False
        msg = "caption burn unavailable (no libass); passthrough"
    return OpResult(outputs={"path": str(out), "captioned": captioned},
                    artifacts={"captioned": str(out)}, message=msg)
