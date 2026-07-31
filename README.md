# ReelForge

**A generic, config-driven pipeline that turns raw footage _or_ a text brief into platform-ready YouTube Shorts & Instagram Reels — for any niche.**

> Status: **plan & elevator pitch (pre-implementation).** This repo is the design + research. Code comes next, phase by phase.

📄 **Live pitch / plan → [GitHub Pages site](https://nsteve2407.github.io/reelforge/)**  ·  🔬 **[Deep dive: LLM-usage map, atomic tasks, providers, learning loop & stack](https://nsteve2407.github.io/reelforge/deep-dive.html)**

## Use AI where it earns its place

Of ~40 atomic tasks, only **5** genuinely need an LLM (ideation, scripting, media-prompt writing, multimodal safety judgment, feedback synthesis) — and each is profile-gated. Everything else is **deterministic OSS / classical**: ingest, scene detection, transcription, audio/motion/telemetry signals, highlight fusion, cutting, reframing, captions, color grade, upload, analytics, bandit selection, scoring, attribution. **Claude has zero native media generation** — it writes words/prompts, judges, and orchestrates; pixels & audio come from specialist models via an aggregator (fal.ai). See the deep dive for the full per-task table.

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

| Phase | Deliverable |
|-------|-------------|
| 0 | Profile schema, connectors, state store, orchestrator skeleton |
| 1 | Footage MVP (bikes) → draft + notify + manual upload |
| 2 | Auto-publish (YT/IG APIs) + scheduling + trend research |
| 3 | Generative mode (kids) with COPPA + disclosure + mandatory review |
| 4 | Hybrid mode (TV talk) + analytics feedback loop |
| 5 | Multi-channel scale, budget guardrails, dashboards |

## Repo layout

```
index.html      # GitHub Pages pitch site
styles.css
profiles/       # example ContentProfile configs (the generic contract)
  bike_pov.yaml
  nursery_rhymes.yaml
  tv_series_talk.yaml
```

---

*This is a plan to be argued with, then built. Tooling figures are directional (mid-2026) and should be re-verified before implementation.*
