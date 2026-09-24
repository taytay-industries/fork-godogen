# Changelog

**2026-09-24 — Godot capture tool**
- Published Godot repos carry `tools/capture.py`, a uv script that records and reviews in one step: `record` builds, imports, and records with the movie writer, then prints the renderer, error lines, and a review — a labeled contact sheet, a motion sheet (motion graph plus changed pixels in red against 6 frames earlier), `FROZEN` / `DARK` / `POP` spans, `video.mp4`, and `report.json`. `frames`, `diff`, `review`, and `export` cover follow-up inspection.
- Capture records OGV by default: Godot encodes movie frames on the main thread, and at 1080p Theora takes ~20 ms/frame against ~230 ms for PNG on Godot 4.7, at no visible loss. The tool re-times clips to constant fps, since Theora's empty repeat packets otherwise hide frozen spans.
- Capture size comes from `--size` through a temporary `override.cfg` (`window_width_override`); `--resolution` never reached the movie writer.

**2026-09-24 — Audio (ElevenLabs)**
- `asset-gen` generates audio through ElevenLabs: `asset_gen.py speech` (text to speech, `eleven_v3` by default), `sfx` (sound effects, optionally seamless loops), `music` (`music_v2`, optionally instrumental), and `voice-change` (re-voice a recorded performance), plus `voices` to cast and `audio-status` to check the key and credits left. Outputs are `.ogg`, `.wav`, or `.mp3` by extension; each call reports the credits it actually used.
- `asset-gen/audio.md` covers casting a voice once per character, one file per dialogue line with neighbouring-line context, one-shot vs loop sound effects, take variation for repeated sounds, and music that plays under gameplay.
- `ELEVENLABS_API_KEY` is optional; the SDK is in `asset-gen/tools/requirements.txt`.

**2026-09-22 — Local image generation, current image models**
- Added local image generation: when `qwen-image` is on PATH, `asset-gen` runs Qwen-Image-2.1 on the machine's GPU for free, so simple images (textures, props, icons, UI, backgrounds, in-image text) go there before the paid APIs; `qwen-image rgba` outputs real alpha with no matting. `setup.md` carries a brief for building the command on each machine.
- Image generation uses Gemini 3.1 Flash Image and Grok Imagine Image 2.0 (medium quality) as equals — a side-by-side on a 3D-ready character and a dense composition came out even. `asset_gen.py` uses whichever key is set, Gemini by default for speed (~10 s vs 1–2 min); quality-critical assets are generated on both and the better kept.
- Sprite video uses `grok-imagine-video-1.5` without audio (14¢/s at 720p, 8¢/s at 480p). Grok results report the cost xAI actually billed; Grok requires `xai-sdk>=1.19`.
- Background removal preloads the CUDA libraries from the `nvidia-*` wheels and checks the provider the session actually runs on, so a mismatched `onnxruntime-gpu` build warns instead of silently running on CPU; requirements pull matching CUDA/cuDNN via `onnxruntime-gpu[cuda,cudnn]`. `rembg_matting.py --preview` no longer crashes.

**2026-09-22 — Custom character animation, Tripo CLI**
- Added custom humanoid animation through `asset-gen/motion.md`: move sets generated locally with [kimodo-practical](https://github.com/htdt/kimodo-practical) (NVIDIA Kimodo), baked to ordinary glTF clips plus `rootmotion.json`, so the game repo carries no motion tooling. Reached from the asset-gen skill when stock retarget presets aren't enough.
- `motion.md` covers the environment, the Tripo-rig → Kimodo and prebake → engine bridges, the authored-pose hybrid (game-authored key poses pinned as `fullbody` constraints), impact timing, numeric prop-relative gates, and a pitfalls index from shipped move sets.
- The animation stack is machine-level under `KIMODO_HOME` with a fixed layout (`kimodo-practical/`, `kimodo/`, `kimenv/`, `text_encoders/`); each project clones its motion workspace from the local reference. Install and verify steps in `setup.md`.
- 3D generation, rigging, and retargeting go through the `tripo` CLI (`npm install -g tripo-cli`, `TRIPO_API_KEY`), which owns submit/poll/download, credit pre-checks, and resume. Removed the in-repo `tripo3d.py` client and the `glb` / `rig` / `retarget` / `resume` subcommands from `asset_gen.py`; Tripo costs are reported in credits.
- Node.js 20+ is now needed for every engine (Tripo CLI); published repos ignore `/tripo-out`.

**2026-07-02 — Docs-only runtime**
- Replaced the multi-stage skill pipeline with a thin runtime: a single engine-agnostic manifest (`prompts/runtime.md`), a one-page per-engine guide, and the cross-engine `asset-gen` skill. The model plans, scaffolds, and decomposes the work itself.
- One runtime manifest covers delivery. The agent reads how the task is framed in-run: an open-ended direction gets the live game early and checkpoints at taste/scope/cost decisions; a finished brief runs on reasonable calls and closes with a 15–20s proof recording, watched back before done. Run/show/capture mechanics live in the engine guides and serve both paths.
- Dropped the planner/decomposer/architecture/scene/scaffold/quirks/capture skill docs, the Vite scaffold, the `godot-api` / `bevy-help` / `babylon-help` lookup skills, and all hooks. The engine-specific traps and capture recipes that survive a compile but fail at runtime moved into the engine guide.
- Trimmed asset docs to generation only; `asset-gen` is now the sole published skill.
- Reorganized the source tree: engine-agnostic runtime text lives in `prompts/runtime.md`, and the asset skill lives at top-level `asset-gen/`.
- Continues the 2026-04-26 "dropped Gemini verification" trajectory — removing guidance the current model no longer needs.

**2026-05-18 — Babylon.js support**
- Added Babylon.js as a first-class engine alongside Godot and Bevy
- Disposable TypeScript/Vite scaffold with scene-level hot reload through a custom Vite plugin (`godogen:scene-change`); engine and canvas persist across edits
- Browser capture through Playwright + Chrome/Chromium; hardware WebGL2 preferred, software-renderer fallback warns prominently but still produces media
- `babylon-help` skill uses installed npm package types as the primary local reference
- `publish.sh` extended to `--engine babylon`

**2026-04-26 — Bevy support**
- Added Bevy as a first-class engine alongside Godot
- Replaced the four Claude/Codex source trees with `shared/`, `godot/`, and `bevy/`
- Added one root `publish.sh` switcher: `--engine godot|bevy` × `--agent claude|codex`
- Dropped Gemini verification — Opus 4.7 / GPT 5.5 self-verify from captured frames; external pass added no signal; the stop hook pushes the latest proof video to Telegram

**2026-04-14 — Codex support**
- Added a parallel Codex source tree alongside the existing Claude Code one
- Each variant publishes to its own runtime layout (`.claude/skills/` vs `.agents/skills/`)

**2026-04-06 — C# migration**
- All skills and generated code migrated from GDScript to C# / .NET 9 ([comparison](docs/gdscript-vs-csharp.md))
- `dotnet build` replaces per-file validation loops

**2026-04-03 — Single-context architecture**
- Orchestrator and task execution merged into one main pipeline
- Added Godot API lookup and visual QA support flows

**2026-03-25 — xAI Grok video**
- Added Grok video generation for animated sprite workflows
- Background removal rewritten with BiRefNet multi-signal matting

**2026-03-09 — Initial release**
- Initial Godogen release with image generation, 3D conversion, screenshot QA, and video capture
