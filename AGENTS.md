# Godogen Source Repo

This repository is not a published game repo. It is the source that `publish.sh` renders into a runtime game repo for a chosen engine and host agent.

## Source Layout

- `prompts/runtime.md` — the engine-agnostic runtime manifest text
- `asset-gen/` — the asset-generation skill (CLI tools + docs, the asset feed, the key drop page)
- `engines/babylon.md`, `engines/godot.md`, `engines/bevy.md` — per-engine guides (stack, project sketch, capture recipe, silent-failure traps)
- `engines/<engine>_tools/` — an engine's tools, published into the game's `tools/` (Godot: `capture.py` record + review, `AnimLab.cs` rigged-clip lab and fixer, `Facing.cs` model facing check, `SceneKit.cs` scene-builder helpers)
- `skills/` — further skills every published repo carries (`game-design-critique`)
- `vendor/skills/` — the vendors' own skills for the CLIs asset-gen drives (ElevenLabs, Tripo); refresh with `vendor/sync.sh`, never edit by hand
- `publish.sh` — renders a runtime repo with `--engine {godot,bevy,babylon}`, `--agent {claude,codex}`
- `scripts/` — render helpers: `render_dir.py` (token substitution), `generate_codex_metadata.py` (Codex `openai.yaml`)

## Editing Rules

- Do not create or maintain `.claude/skills/` or `.agents/skills/` in this source repo.
- Don't give obvious guidance. The agent is a highly capable LLM, and the deliverable (a recorded video, or a live URL the user watches) surfaces its own mistakes — so keep the guides to what the model can't infer or discover fast.
- When you change or remove a feature, describe the new state on its own terms. Name the new thing as if it were always the design.
