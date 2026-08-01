# ReelForge

**A generic, config-driven pipeline that turns raw footage _or_ a text brief into platform-ready YouTube Shorts & Instagram Reels — for any niche.**

> Status: **Phases 0–5 built (all roadmap phases complete).** Footage / generative / hybrid modes → review gate → quota-guarded publish (YT/IG); trend research + hook ideation; a learning loop (Thompson bandit + pre-publish scorer); **budget guardrails**, **multi-channel batch**, and a **local dashboard**. All dry-run/offline by default; add `--live` + credentials to go real. **71 tests green.** The site (`index.html` / `deep-dive.html`) is the design/research.

📄 **Live pitch / plan → [GitHub Pages site](https://nsteve2407.github.io/reelforge/)**  ·  🔬 **[Deep dive: LLM-usage map, atomic tasks, providers, learning loop & stack](https://nsteve2407.github.io/reelforge/deep-dive.html)**

## Use AI where it earns its place

Of ~40 atomic tasks, only **5** genuinely need an LLM (ideation, scripting, media-prompt writing, multimodal safety judgment, feedback synthesis) — and each is profile-gated. Everything else is **deterministic OSS / classical**: ingest, scene detection, transcription, audio/motion/telemetry signals, highlight fusion, cutting, reframing, captions, color grade, upload, analytics, bandit selection, scoring, attribution. **Claude has zero native media generation** — it writes words/prompts, judges, and orchestrates; pixels & audio come from specialist models via an aggregator (fal.ai). See the deep dive for the full per-task table.

**MCP layer:** Claude reaches the generators as tools via Model Context Protocol — **fal.ai MCP** (`mcp.fal.ai`, 1,000+ models) as the default aggregator surface, plus official **MiniMax** (voice/image/video/music), **ElevenLabs** (voice), and **Gemini/Veo** MCPs, and **TwelveLabs MCP** for semantic video-understanding in the clip-detection stage. MCP drives the *agentic* loop; deterministic Prefect ops call the same providers directly via thin adapters for reproducible batch runs. Unofficial MCPs (e.g. Suno) are flagged off the commercial path.

---

## The idea in one line

Every short-form workflow is the same seven moves in a different costume. So ReelForge treats **niche as data**: you write one `ContentProfile`, and the same engine swaps sources, trend signals, editing looks, voices, and publishing targets. Bike POV today, kids' nursery rhymes tomorrow, TV-series hot takes next week.

## What it does

1. **Ingest** — pull new media from Insta360 Cloud / Google Drive / Dropbox / S3 / local (via `rclone`), or trigger a pure-generative run.
2. **Research & ideate** — blend YouTube / Google Trends / TikTok Creative Center / IG signals; Claude ranks angles and drafts hooks, titles, descriptions.
3. **Understand clips** — PySceneDetect for cuts, Whisper for transcripts, a vision LLM to score the interesting/safe/usable moments.
4. **Build the short** — *footage mode* cuts & auto-reframes highlights to 9:16; *generative mode* turns a script into voiced, scored, animated scenes. Then captions + LUT color grade + music.
5. **Review gate** — a draft + preview link hits Telegram/Slack/email; you approve, edit, or reject. **Nothing posts silently.**
6. **Publish** — YouTube Data API v3 + Instagram Graph API, quota-aware, scheduled at high-engagement times.
7. **Learn** — pull analytics, attribute wins to hooks/formats/lengths, auto-tune the next run.

## Two creation modes

| Mode | Source | Example | Cost |
|------|--------|---------|------|
| **Footage** | your real clips | bike POV | low (mostly OSS) |
| **Generative** | text brief only | nursery rhymes | higher (video-gen credits) |
| **Hybrid** | your voice + AI b-roll | TV-series talk | medium |

## The generic contract

Launching a new channel = writing one `ContentProfile` (see [`profiles/`](profiles/)). No code changes. Everything you control — topic, channel, audience, captions, color grade, voice, music, platforms, schedule, compliance flags — is a field.

```yaml
id: bike_pov
source: { mode: footage, connectors: [insta360_cloud, gdrive, local] }
audience: { segment: enthusiast_hobbyist, age: "18-34", tone: high_energy }
edit:
  captions: { enabled: true, style: karaoke_bold }
  color_grade: { lut: teal_orange_punch, look: vivid_action }
publish: { platforms: [youtube_shorts, instagram_reels], approval: required }
```

## Recommended stack (researched mid-2026)

- **Orchestration:** Python core + **Prefect** (or Temporal); n8n only for notify/approval glue.
- **OSS core:** `rclone`, FFmpeg/MoviePy, PySceneDetect, Whisper.
- **AI reasoning:** **Claude** (ideation, scripting, multimodal highlight/safety scoring, tool-use).
- **Auto-clip/captions (buy for speed):** OpusClip / Vizard / Reap / CapCut.
- **Generative video:** **Veo 3.1** & **Kling 3.0** (native audio), Runway, Luma, Pika, LTX. *(Sora is being discontinued in 2026 — don't build on it.)* Kids-turnkey: Atlabs / Steve AI.
- **Voice:** Inworld / Murf / Cartesia / ElevenLabs; OSS Kokoro / Chatterbox.
- **Music:** **Stable Audio** for clean commercial licensing (Suno/Udio have RIAA licensing uncertainty).

## Platform limits & compliance (design constraints)

- **YouTube:** 10k quota/day, upload = 1,600 units → ~6 uploads/day; per-channel ~10/24h; verified OAuth project.
- **Instagram:** **Business** account required; ~1–3 quality Reels/day; 9:16, 5–90s; container→publish flow.
- **Compliance:** COPPA `made_for_kids`, AI-content disclosure, clean music licensing, fair-use for commentary, human-review gate + modest caps to avoid spam/authenticity enforcement.

## Roadmap

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 0 | Profile schema, storage, state ledger, op contract | ✅ **built** |
| 1 | Footage MVP (bikes) → multi-signal highlights → 9:16 draft → review card | ✅ **built** |
| 2 | Publish (YT/IG) behind approval gate + quota guard + scheduling + trend research | ✅ **built** (dry-run + credential-gated live) |
| 3 | Generative mode (script→voice→music→scenes→captions) + COPPA/AI-disclosure | ✅ **built** (dry-run media; credential-gated fal/MiniMax) |
| 4 | Hybrid mode (voice + AI b-roll) + learning loop (bandit + scorer) | ✅ **built** |
| 5 | Multi-channel batch + budget guardrails + local dashboard | ✅ **built** |

## Quickstart (footage MVP)

Local-first. Needs `ffmpeg`/`ffprobe` and Python 3.10+ (a `.venv` via [uv](https://astral.sh/uv) is easiest).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .

.venv/bin/python -m reelforge.cli doctor            # check ffmpeg/opencv/scenedetect
.venv/bin/python -m reelforge.cli profiles          # list ContentProfiles
.venv/bin/python -m reelforge.cli run --profile bike_pov --demo   # footage: synth a clip & run
.venv/bin/python -m reelforge.cli run --profile bike_pov --input ride.mp4
.venv/bin/python -m reelforge.cli run --profile nursery_rhymes --topic "sleepy stars"  # generative
.venv/bin/python -m reelforge.cli run --profile tv_series_talk --topic "finale" [--voice take.mp4]  # hybrid

# publish (DRY-RUN by default; no accounts needed):
.venv/bin/python -m reelforge.cli run --profile bike_pov --demo --auto-approve --publish
.venv/bin/python -m reelforge.cli publish --run <run_id> --profile bike_pov  # after approval
#   add --live (+ creds via env) to hit the real YouTube/Instagram/fal/MiniMax APIs

# learning loop:
.venv/bin/python -m reelforge.cli learn ingest --run <id> --hook hard_cut --views 5000 --watch 22 --length 28 --retention 0.75
.venv/bin/python -m reelforge.cli learn insights   # ranked hook bandit + scorer status
.venv/bin/python -m reelforge.cli learn train      # retrain pre-publish scorer

# multi-channel + budget + dashboard:
.venv/bin/python -m reelforge.cli batch --profiles nursery_rhymes,tv_series_talk --topic "night sky" --auto-approve --publish
.venv/bin/python -m reelforge.cli report --html dashboard.html   # spend/quota/bandit/status
#   generative runs accept --enforce-budget to trim scenes to profile.budget.max_usd_per_video

.venv/bin/python -m pytest                          # 71 tests
```

A run ingests → detects scenes / audio-energy / motion (+ action-cam telemetry if present) → **fuses signals classically** (normalize → weight → `scipy` peaks → soft-NMS) → cuts the top highlights → reframes to 9:16 → color-grades → (optional captions) → renders a draft → writes a **review card** and stops at the approval gate. Nothing publishes without approval. Captions need the optional `faster-whisper` extra; absent, they're skipped gracefully.

## Going live (credentials)

Everything above runs **offline in dry-run/fallback with zero keys.** Each external component is optional — set its env vars to make that piece live, then add `--live`. Run **`reelforge setup`** for this checklist with live set/missing status ([full table on the site](https://nsteve2407.github.io/reelforge/deep-dive.html#setup)).

| Component | Env vars | Where to get it | Without it |
|-----------|----------|-----------------|------------|
| Claude (scripts/hooks) | `ANTHROPIC_API_KEY` | console.anthropic.com | template fallback |
| fal.ai (gen media) | `FAL_KEY` | fal.ai → Keys | dry-run placeholders |
| MiniMax (alt gen) | `MINIMAX_API_KEY`, `MINIMAX_GROUP_ID` | platform.minimax.io | uses fal / dry-run |
| YouTube research | `YOUTUBE_API_KEY` | Google Cloud console | that source empty |
| YouTube upload (OAuth) | `REELFORGE_YT_TOKEN_FILE` (or client id/secret/token) | GCP OAuth (scope `youtube.upload`, audit ~2–4 wks) | publish dry-run |
| Instagram (Business) | `REELFORGE_IG_USER_ID`, `REELFORGE_IG_ACCESS_TOKEN`, `REELFORGE_IG_MEDIA_URL` | Meta app + IG business account | publish dry-run |

```bash
export ANTHROPIC_API_KEY=... FAL_KEY=... REELFORGE_YT_TOKEN_FILE=~/yt.json
reelforge run --profile bike_pov --input ride.mp4 --auto-approve --publish --live
```

## Repo layout

```
index.html  styles.css  deep-dive.html   # GitHub Pages pitch + deep dive
profiles/                 # ContentProfile configs (bike_pov, nursery_rhymes, tv_series_talk)
pyproject.toml
src/reelforge/
  core/     # profile · storage · state · media · publish · generate · learn · budget · report · credentials · op · types
  ops/      # atomic ops: ingest · understand · build · review · publish · research · generate · learn
  adapters/ # credential-gated, lazy: youtube · instagram · analytics · fal · minimax
  flows/    # footage.py · generative.py · hybrid.py · batch.py (multi-channel) · publish_run
  cli.py    # typer CLI: doctor / setup / profiles / ops / run / publish / learn{…} / batch / report
tests/      # 71 tests: pure-unit + real-ffmpeg integration + e2e all modes + publish/research/creds/learn/budget/batch
```

> Orchestration note: ops are pure functions composed by `flows/footage.py`; each maps 1:1 onto a Prefect `@task` when moving to a durable orchestrator — that's the only change. Storage is a local backend behind an fsspec-shaped interface (S3/GCS drop in later).

---

*This is a plan to be argued with, then built. Tooling figures are directional (mid-2026) and should be re-verified before implementation.*
