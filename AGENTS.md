# AGENTS.md — ReelForge handoff & continuity guide

**Read this first.** It's the single source of truth for any agent (or human) picking up ReelForge cold: what it is, what's built, how it's structured, the conventions you MUST follow, how to run/test, how to go live, and exactly what is NOT done. Nothing about the design, decisions, or remaining work should be lost — it's all here or linked from here.

---

## 1. What ReelForge is

A **generic, config-driven pipeline** that turns raw footage **or** a text brief into platform-ready **YouTube Shorts / Instagram Reels for any niche**. "Niche is data": you write one `ContentProfile` (YAML) and the same engine swaps sources, research signals, editing looks, voices, and publish targets. Three shipped example niches: **bike POV** (footage), **nursery rhymes** (generative), **TV-series talk** (hybrid).

Guiding principle (from the owner): **use AI where it earns its place.** Only ~5 tasks call an LLM (ideation/hooks, scripting, media-prompt writing, multimodal safety judgment, feedback synthesis) — everything else is deterministic OSS/classical. **Claude has zero native media generation**; it writes words/prompts, judges, and orchestrates. Pixels/audio come from specialist providers, ideally via an aggregator (fal.ai) so each is a swappable `model_id`.

- **Repo:** `git@github.com:nsteve2407/reelforge.git` (GitHub account `nsteve2407`, `gh` CLI is authed with `repo` scope).
- **Live site (GitHub Pages, from `main` / root):**
  - Pitch: https://nsteve2407.github.io/reelforge/  (`index.html`)
  - Deep dive + setup checklist: https://nsteve2407.github.io/reelforge/deep-dive.html (`deep-dive.html`, `styles.css`)
- **Working dir on this machine:** `/home/steve/Agent Lab/reelforge`

---

## 2. Current status (as of commit `e527845`)

**All 6 roadmap phases built + integration hardening. 81 tests green. Runs fully offline in dry-run.**

| Phase | Deliverable | State |
|---|---|---|
| 0 | Foundation: ContentProfile, storage, SQLite ledger, `@op` contract | ✅ |
| 1 | Footage MVP: multi-signal highlights → 9:16 draft → review gate | ✅ |
| 2 | Publish (YT/IG) behind approval + quota guard + scheduling + trend research | ✅ |
| 3 | Generative mode: script→voice→music→scenes→captions (+COPPA/AI-disclosure) | ✅ |
| 4 | Hybrid mode (voice + AI b-roll) + learning loop (bandit + scorer) | ✅ |
| 5 | Multi-channel batch + budget guardrails + local dashboard | ✅ |
| — | Hardening: YouTube OAuth helper, retry wrapper + optional Prefect, public-URL hosting | ✅ |

Docs that mirror this and MUST be kept in sync when you change scope: `README.md` (status line, roadmap table, quickstart, layout, test count), `index.html` (roadmap banner), `deep-dive.html` (learning "Built" note, `#setup` table, `#checklist`).

---

## 3. Environment (important gotchas)

- **System Python is 3.6.9** (Ubuntu 18.04) — too old for the stack. We provisioned **Python 3.12 in userspace via `uv`**. Always use the project venv: `/home/steve/Agent Lab/reelforge/.venv/bin/python`. Never the system `python3`.
- `uv` is at `~/.local/bin/uv` (`export PATH="$HOME/.local/bin:$PATH"`).
- **ffmpeg/ffprobe:** upgraded to a **static 7.0.2** build in `~/.local/bin` (was system 3.4.11). Code still uses 3.4-safe filters for portability (only widely-supported: scale, crop, eq, curves, colorbalance, hue, subtitles/libass, concat, volume, amix, anullsrc, sine, color, drawtext). If a shell shows 3.4.11, prepend `~/.local/bin` to PATH.
- **GPU: GTX 1060 6 GB.** Fine for the footage pipeline (faster-whisper small/medium + INT8). Production video/music generation needs cloud.
- `.venv/`, `.env`, `*.db`, `.rf_*/` runtime dirs are gitignored. Never commit them.

### First-time setup / rebuild the env
```bash
export PATH="$HOME/.local/bin:$PATH"
cd "/home/steve/Agent Lab/reelforge"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
.venv/bin/python -m pytest              # expect 86 passed
```

### Config layers
- **`reelforge.yaml`** (committed, non-secret): workspace prefs — `active_profile` (currently `bike_pov`), `profiles_dir`, `work_dir`, `auto_approve`, `enforce_budget`. Read by `reelforge config show` / `config set-profile <id>`. It's a convenience record + hint; it does NOT make `run` assume a profile (still explicit `--profile`).
- **`.env`** (gitignored; template `.env.example`): API keys/tokens. Auto-loaded at CLI startup (`core/config.load_dotenv`, `setdefault` semantics). Copy `.env.example` → `.env`, fill what you need, then `reelforge setup` shows readiness.

### Editable-install caveat (bit us once)
If code edits under `src/` don't take effect at runtime, the venv may hold a **copied** (non-editable) install. Fix + verify:
```bash
uv pip install --python .venv/bin/python -e . --reinstall
.venv/bin/python -c "import reelforge.cli; print(reelforge.cli.__file__)"   # must be under src/
```

---

## 4. Architecture & the op contract (MUST follow)

Layered, Prefect-ready. **Ops are pure single-responsibility functions**; flows compose them; the same code runs local → docker → cloud via env.

```
src/reelforge/
  core/     profile · storage · state(ledger:runs/assets/events/quota/bandit/post_metrics/spend)
            media(ffmpeg) · op(decorator+REGISTRY) · types · context
            publish · generate · learn · budget · report · credentials · oauth · orchestrate · hosting
  ops/      ingest · understand · build · review · publish · research · generate · learn   (one file per stage)
  adapters/ youtube · instagram · analytics (publish/insights) · fal · minimax (generate)  — CREDENTIAL-GATED, lazy-imported
  flows/    footage.py(run_footage,publish_run) · generative.py(run_generative) · hybrid.py(run_hybrid)
            batch.py(run_batch) · prefect_flow.py(optional Prefect wrappers)
  cli.py    typer: doctor/setup/profiles/ops/run/publish/learn{ingest,insights,train}/batch/report/auth{youtube,check}
tests/      one file per subsystem (14 files, 81 tests)
profiles/   bike_pov.yaml · nursery_rhymes.yaml · tv_series_talk.yaml   (the generic contract, examples)
index.html styles.css deep-dive.html   (GitHub Pages)
```

### The `@op` contract — every atomic task looks like this
```python
from ..core.context import OpContext
from ..core.op import op
from ..core.types import OpResult   # + Segment, SignalTrack, Highlight, Caption, MediaInfo

@op("name")                          # registers in core.op.REGISTRY, logs start/ok/err to ledger, times it
def op_name(ctx: OpContext, ...) -> OpResult:
    ...
    return OpResult(outputs={...}, artifacts={"kind": path}, metrics={...}, message="...")
```
Rules:
- **One op = one responsibility.** Ops MUST return `OpResult`.
- Write files under `ctx.storage.path(...)` (a `Storage` rooted at the per-run workdir). Put in-memory objects in `outputs`, file paths in `artifacts` (auto-registered as ledger assets).
- Use `core.media`: `run([...])` (raises `FFmpegError` w/ stderr), `probe`, `extract_audio_wav`, `read_wav_mono`, `iter_frames_gray`, `synth_test_clip`.
- Registry import chain: `ops/__init__.py` imports every op module so they self-register.

### Two golden design rules (keep these invariant)
1. **Dry-run-first / offline-testable.** Everything runs with NO credentials by default: publishers → `DryRunPublisher`, generators → `DryRunGenerator` (real ffmpeg placeholder media), providers/analytics → return `[]`/`{}`, LLM → deterministic fallback. Real behavior is opt-in via `--live` + creds. **Never break the offline path** — the whole test suite depends on it.
2. **Credential-gated, lazy adapters.** Real API SDKs (google-api-python-client, requests, fal_client, boto3, prefect, google_auth_oauthlib…) are imported INSIDE adapter methods, never at module top, so the package imports and tests run without them.

### ContentProfile (the generic contract)
`core/profile.py`, pydantic v2, `extra="ignore"` (permissive/forward-compatible). Key fields: `source.mode` (footage|generative|hybrid), `audience`, `research`, `understand`, `edit` (aspect_ratio→`target_w_h`, length_s, captions, color_grade, music, voiceover), `generate` (script/music/voiceover/animation/broll), `publish` (platforms, schedule, daily_cap, approval, ai_disclosure, made_for_kids, hashtags), `budget.max_usd_per_video`. Load via `load_profile(id_or_path, profiles_dir)`.

---

## 5. How to run (all offline/dry-run by default)

```bash
V=".venv/bin/python -m reelforge.cli"
$V doctor                                             # env check
$V profiles ; $V ops                                  # list profiles / 33 registered ops
$V run --profile bike_pov --demo                      # footage (synth clip)
$V run --profile bike_pov --input ride.mp4            # footage (real)
$V run --profile nursery_rhymes --topic "sleepy stars"# generative
$V run --profile tv_series_talk --topic "finale" [--voice take.mp4]   # hybrid
$V run --profile bike_pov --demo --auto-approve --publish             # publish (DRY-RUN)
$V run --profile bike_pov --input ride.mp4 --vibe adrenaline           # pick a vibe (footage)
$V publish --run <id> --profile bike_pov              # publish an approved run
$V learn ingest --run <id> --hook hard_cut --views 5000 --watch 22 --length 28 --retention 0.75
$V learn insights ; $V learn train                    # bandit ranking / retrain scorer
$V batch --profiles nursery_rhymes,tv_series_talk --topic "night sky" --auto-approve --publish
$V report --html dashboard.html                       # spend/quota/bandit/status dashboard
$V setup                                              # go-live credential checklist w/ status
$V auth youtube --client-secrets cs.json --out yt_token.json   # mint YT OAuth token (interactive)
```
Flags: `--live` (real APIs, needs creds), `--enforce-budget` (trim generative scenes to `budget.max_usd_per_video`), `--vibe <name>` (footage: pick a mood from the profile's `vibes:` library — sets caption themes + trending keywords for Claude, the fal music prompt, and hashtags in one knob).

Pipeline flow: ingest → understand (multi-signal fuse: scenes+audio+motion+telemetry → scipy peaks → soft-NMS) → build (cut→reframe 9:16→captions→LUT→render) → **review gate (stops here unless auto-approve)** → publish (quota-guarded). Generative/hybrid: script→scenes/voice/music→mux→captions→grade→review→publish.

---

## 6. Testing & verification (do this, always)

- Run the suite with the venv: `.venv/bin/python -m pytest` (expect **81 passed**). Per-file: `... -m pytest tests/test_x.py -q`.
- Tests are offline: unit (pure fusion/selection/ASS/bandit/scorer/budget/estimate), real-ffmpeg integration (synth clips), e2e per mode, plus publish/research/credentials/learn/budget/batch/report/oauth/hosting/retry.
- `tests/conftest.py` provides `ctx` (tmp OpContext) and `sample_clip` (real 8s synth mp4).
- **When adding an op/flow: add its test, keep it offline (dry-run/injected providers), and run the FULL suite before committing.** Also smoke-test the actual CLI path, not just pytest.

---

## 7. Going live — credentials map (all optional)

Source of truth: `core/credentials.py` `CATALOG` (drives `reelforge setup` AND the site's `#setup` table — keep them consistent by editing the CATALOG, not hardcoding). `load_credentials(env)` builds a nested `{platform_or_provider: {...}}` map; ops pick their sub-keys. `--live` in the CLI loads it and passes it through.

| Component | Env vars | Without it |
|---|---|---|
| Claude (scripts/hooks) | `ANTHROPIC_API_KEY` | deterministic template fallback |
| fal.ai (gen media) | `FAL_KEY` (+ `REELFORGE_FAL_VIDEO_MODEL`/`_TTS_MODEL`/`_MUSIC_MODEL`) | dry-run placeholder media |
| MiniMax | `MINIMAX_API_KEY`, `MINIMAX_GROUP_ID` | uses fal / dry-run |
| YouTube research | `YOUTUBE_API_KEY` | that trend source empty |
| YouTube upload | `REELFORGE_YT_TOKEN_FILE` (or `_CLIENT_ID`/`_CLIENT_SECRET`/`_TOKEN`/`_REFRESH_TOKEN`) | publish dry-run |
| Instagram (Business) | `REELFORGE_IG_USER_ID`, `REELFORGE_IG_ACCESS_TOKEN`, + `REELFORGE_IG_MEDIA_URL` **or** `REELFORGE_HOST_S3_BUCKET`/`_GCS_BUCKET` | publish dry-run |

Helpers: `auth youtube` mints the YT token; IG auto-hosts the draft to a public URL when a host bucket is set (`core/hosting.py`); live publish calls get exponential-backoff retries (`core/orchestrate.py`). The full human checklist is the interactive list at `deep-dive.html#checklist`.

---

## 8. What is NOT done / honest boundaries (don't re-verify as "working")

- **No real live API calls have been executed here** (no accounts/keys on this machine): YouTube upload/analytics, Instagram publish, fal/MiniMax generation, S3/GCS hosting, Prefect runs. The code paths exist, are credential-gated, and are UNTESTED against real services. Treat them as `[INFERENCE]` until exercised with credentials.
- **Offline generative media is placeholder** (solid-color scenes + SILENT narration — there is no offline TTS on this box; music is a sine bed). Real visuals/voice require fal/MiniMax via `--live`.
- **Prefect wrapper** currently wraps the whole run as one `@flow` when Prefect is installed (fallback = in-process). Finer per-op `@task` granularity is a mechanical follow-up (ops are already pure).
- **Instagram** needs the draft at a public URL (Graph API fetches by URL) — wired via hosting, but end-to-end IG publish is unverified.
- Minor: `pastel_soft` LUT isn't a defined look preset → passes through (add it in `ops/build.py` `_LOOKS` if wanted). Hook (`select_hook`) is recorded in the footage flow return/meta; generative/hybrid pick a hook via the bandit too but keep leaner returns.
- All prices/model IDs (`core/budget.py`, provider tables, docs) are **directional mid-2026** — re-verify before real spend. **Sora is discontinued — never build on it.**

---

## 9. How to extend (playbook)

- **New atomic op:** add `op_x` in the right `ops/<stage>.py` with `@op("x")`, return `OpResult`, write a test, run full suite.
- **New provider (gen/publish/analytics/host):** add a credential-gated, lazy adapter in `adapters/`; wire it in the matching `core/*.get_*` factory; add its env vars to `credentials.CATALOG` + `load_credentials`; document in README + `deep-dive.html#setup`.
- **New niche/channel:** just add `profiles/<name>.yaml` (no code). Confirm it parses (`test_core.py` pattern).
- **New flow/mode:** add `flows/<mode>.py`, export in `flows/__init__.py`, route in `cli.py run` by `source.mode`, add e2e test + a `prefect_flow.py` wrapper.
- **Keep docs in sync:** any status/scope change → update README + the three HTML docs + this file's §2.

---

## 10. Git / workflow conventions

- Commit with explicit identity (no global git config assumed):
  ```bash
  git -c user.name="nsteve2407" -c user.email="nsteve2407@users.noreply.github.com" commit -q -m "..."
  git push -q origin main
  ```
- After pushing docs, GitHub Pages auto-rebuilds from `main`/root (~40–60s). Verify with `gh api repos/nsteve2407/reelforge/pages/builds/latest --jq .status` then `curl` the live URL (the builds API `.commit` field can lag; trust the live HTML).
- Conventional, scoped commit messages; keep the working tree clean of `.rf_*`/`*.db`/`.venv`.

---

## 11. Where the design rationale lives

- **`deep-dive.html`** is the full design/research writeup (LLM-usage map, atomic-task DAG, multi-signal clip detection incl. Insta360 telemetry, generative providers, MCP layer, learning loop, tech-stack rationale, go-live setup, and the human checklist).
- **`index.html`** is the pitch + roadmap.
- **`README.md`** is the developer quickstart + status.
- This **`AGENTS.md`** is the operational continuity contract. If you change how things work, update it.
