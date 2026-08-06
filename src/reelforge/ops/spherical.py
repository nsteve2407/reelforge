"""360 (dual-fisheye) support — stitch + auto-reframe an Insta360 feed to flat 9:16.

Insta360 `.insv` files store two ~193° fisheye lenses (a full sphere), either as
two video tracks or one side-by-side track. To turn a 360 ride into a normal reel
we:
  1. stitch the lenses to an equirectangular panorama (ffmpeg `v360=dfisheye:e`);
  2. auto-pick a virtual-camera yaw path that follows the most salient motion — a
     lightweight "virtual cameraman" (saliency + optical flow), grounded in the
     Pano2Vid / AutoCam and 360-saliency literature (Google's SH pipeline,
     SalFormer360); and
  3. render a flat rectilinear view that pans along that path via `v360=dfisheye:flat`
     driven by `sendcmd`.

Limitation: ffmpeg has no camera IMU, so the horizon is NOT gyro-locked the way
Insta360's Media SDK FlowState is. For production-grade stitching + horizon lock,
swap `op_reframe_360`'s ffmpeg call for the (approval-gated) Insta360 Media SDK
(github.com/Insta360Develop/Desktop-MediaSDK-Cpp) — same op boundary, better pixels.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..core import media
from ..core.context import OpContext
from ..core.op import op
from ..core.types import OpResult

IH_FOV = 193.0    # per-lens field of view (Insta360 X-series ~189-204°)
D_FOV = 104.0     # output rectilinear FOV — a natural, slightly-wide POV


def video_stream_count(path: str | Path) -> int:
    proc = media.run(["ffprobe", "-v", "error", "-select_streams", "v",
                      "-show_entries", "stream=index", "-of", "json", str(path)])
    return len(json.loads(proc.stdout or "{}").get("streams", []))


def is_360(path: str | Path) -> bool:
    """Dual-fisheye 360 source: an `.insv`, or any file with 2 video (lens) tracks."""
    if str(path).lower().endswith(".insv"):
        return True
    try:
        return video_stream_count(path) >= 2
    except media.FFmpegError:
        return False


def _stack(nstreams: int) -> str:
    """Combine the lens track(s) into one side-by-side dual-fisheye frame [df]."""
    return "[0:v:0][0:v:1]hstack[df];" if nstreams >= 2 else "[0:v:0]null[df];"


@op("stitch_proxy")
def op_stitch_proxy(ctx: OpContext, src: str, *, w: int = 960, h: int = 480,
                    fps: float = 4.0, ih_fov: float = IH_FOV) -> OpResult:
    """Stitch the fisheyes to a low-res equirectangular proxy for fast analysis."""
    out = ctx.storage.path("reframe", "equirect_proxy.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    n = video_stream_count(src)
    fc = _stack(n) + f"[df]v360=dfisheye:e:ih_fov={ih_fov}:iv_fov={ih_fov}:w={w}:h={h}[o]"
    media.run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[o]",
               "-r", str(fps), "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(out)])
    return OpResult(outputs={"path": str(out)}, artifacts={"proxy": str(out)},
                    message=f"equirect proxy {w}x{h}@{fps}")


def _column_interest(g_prev: np.ndarray, g_cur: np.ndarray, lat_w: np.ndarray) -> np.ndarray:
    """Per-yaw-column interest = motion (optical flow) + detail (Laplacian),
    latitude-weighted so sky/ground poles don't dominate. Returns len-W vector."""
    import cv2
    flow = cv2.calcOpticalFlowFarneback(g_prev, g_cur, None,
                                        0.5, 3, 15, 3, 5, 1.2, 0)
    mag = np.sqrt((flow ** 2).sum(-1))
    lap = np.abs(cv2.Laplacian(g_cur.astype(np.float32), cv2.CV_32F))

    def _n(a: np.ndarray) -> np.ndarray:
        m = float(a.max())
        return a / m if m > 1e-6 else a

    s = (_n(mag) + 0.5 * _n(lap)) * lat_w[:, None]
    return s.sum(axis=0)


@op("pick_view_360")
def op_pick_view_360(ctx: OpContext, proxy: str, *, sample_fps: float = 4.0,
                     max_deg_per_s: float = 40.0, smooth_s: float = 1.5) -> OpResult:
    """Auto-director: choose a smooth virtual-camera yaw path that follows the most
    salient motion in the panorama. Returns dense (t, yaw) keys + one median pitch."""
    import cv2  # noqa: F401 - ensures cv2 present; used in _column_interest
    frames = list(media.iter_frames_gray(proxy, target_fps=sample_fps, max_dim=256))
    if len(frames) < 2:
        return OpResult(outputs={"yaw_path": [(0.0, 0.0)], "pitch": 0.0},
                        message="360 view: clip too short, forward view")
    H, W = frames[0][1].shape
    lat_w = np.sin((np.arange(H) + 0.5) / H * np.pi)      # cos-latitude weight (peak at equator)
    B = 36                                                # yaw candidate bins (10° each)
    edges = np.linspace(0, W, B + 1).astype(int)
    times: list[float] = []
    pitches: list[float] = []
    sal = np.zeros((len(frames) - 1, B), dtype=np.float64)
    for i, ((_, g0), (t1, g1)) in enumerate(zip(frames[:-1], frames[1:])):
        col = _column_interest(g0, g1, lat_w)             # per-yaw-column interest (len W)
        for b in range(B):
            sal[i, b] = col[edges[b]:edges[b + 1]].sum()
        m = float(sal[i].max())
        if m > 1e-6:
            sal[i] /= m                                   # normalize per frame -> reward in [0,1]
        row_energy = (np.abs(cv2.Laplacian(g1.astype(np.float32), cv2.CV_32F))
                      * lat_w[:, None]).sum(axis=1)
        pitches.append(90.0 - (int(np.argmax(row_energy)) + 0.5) / H * 180.0)
        times.append(round(float(t1), 3))
    # ---- AutoCam-style DP: maximize saliency, penalize camera movement (circular) ----
    T = sal.shape[0]
    bins = np.arange(B)
    dist = np.abs(bins[:, None] - bins[None, :])
    dist = np.minimum(dist, B - dist)                     # shortest angular distance (wrap)
    move_cost = 0.10 * (dist.astype(np.float64) ** 2)     # λ·Δ² smoothness prior
    dp = -sal[0].copy()
    back = np.zeros((T, B), dtype=int)
    for t in range(1, T):
        trans = dp[:, None] + move_cost                   # trans[i,j] = come from i to j
        back[t] = np.argmin(trans, axis=0)
        dp = trans[back[t], bins] - sal[t]
    seq = [int(np.argmin(dp))]
    for t in range(T - 1, 0, -1):
        seq.append(int(back[t, seq[-1]]))
    seq = seq[::-1]
    # bin centers -> degrees; unwrap + gentle smoothing to soften the 10° steps
    deg = (np.asarray(seq) + 0.5) / B * 360.0 - 180.0
    deg = np.degrees(np.unwrap(np.radians(deg)))
    win = max(1, int(round(smooth_s * sample_fps)))
    kern = np.ones(win) / win
    deg = np.convolve(np.r_[[deg[0]] * win, deg, [deg[-1]] * win], kern, "same")[win:-win]
    path = [(t, round(((y + 180.0) % 360.0) - 180.0, 2)) for t, y in zip(times, deg)]
    pitch = float(np.clip(np.median(pitches), -25.0, 20.0))
    return OpResult(outputs={"yaw_path": path, "pitch": pitch},
                    metrics={"n_keys": float(len(path)), "pitch": pitch},
                    message=f"virtual cameraman (DP): {len(path)} yaw keys, pitch {pitch:.0f}")


@op("reframe_360")
def op_reframe_360(ctx: OpContext, src: str, *, yaw_path: list, pitch: float = 0.0,
                   ih_fov: float = IH_FOV, d_fov: float = D_FOV,
                   w: int = 1080, h: int = 1920, name: str = "reframed") -> OpResult:
    """Render a flat 9:16 view panning along `yaw_path` (v360 driven by sendcmd)."""
    out = ctx.storage.path("reframe", f"{name}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    yaw_path = list(yaw_path) or [(0.0, 0.0)]
    script = "".join(f"{float(t):.3f} v360 yaw {float(y):.2f};\n" for t, y in yaw_path)
    cmds = ctx.storage.write_text(script, "reframe", "yaw.cmds")
    cmds_esc = str(cmds).replace(":", "\\:").replace("'", "\\'")
    n = video_stream_count(src)
    y0 = float(yaw_path[0][1])
    fc = (_stack(n) +
          f"[df]sendcmd=f='{cmds_esc}',"
          f"v360=dfisheye:flat:ih_fov={ih_fov}:iv_fov={ih_fov}:d_fov={d_fov}:"
          f"yaw={y0}:pitch={pitch}:w={w}:h={h}[o]")
    try:
        has_audio = media.probe(src).has_audio
    except media.FFmpegError:
        has_audio = False
    cmd = ["ffmpeg", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[o]"]
    if has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
    media.run(cmd)
    return OpResult(outputs={"path": str(out)}, artifacts={"reframed": str(out)},
                    message=f"360->flat {w}x{h}, {len(yaw_path)} yaw keys, pitch {pitch:.0f}")


def reframe_if_360(ctx: OpContext, src: str, *, w: int = 1080, h: int = 1920) -> str:
    """If `src` is a 360 dual-fisheye feed, stitch + auto-reframe it to a flat
    vertical mp4 and return that path; otherwise return `src` unchanged."""
    if not is_360(src):
        return str(src)
    proxy = op_stitch_proxy(ctx, src).outputs["path"]
    view = op_pick_view_360(ctx, proxy)
    flat = op_reframe_360(ctx, src, yaw_path=view.outputs["yaw_path"],
                          pitch=view.outputs["pitch"], w=w, h=h).outputs["path"]
    ctx.ledger.update_run(ctx.run_id, "reframed_360")
    return flat
