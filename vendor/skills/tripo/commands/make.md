# tripo make

The magic command: input in, finished local 3D artifacts out. Blocking; exits when files are on disk.

```
tripo make <input...> [options]
```

## Before anything is spent: the plan card

`make` first prints a plan card on stderr — input, scenario, model, then **one numbered line per API call** (endpoint, what it does, its args), deliverables and cost notes:

```
── Plan ──────────────────────────
input: a medieval knight
scenario: game-mobile (Mobile game / low-poly)
model: P1-20260311 — scenario game-mobile
steps:
  1. text-to-model  POST /v3/generation/text-to-model — generate a 3D model from text
     model="P1-20260311" texture=true pbr=true texture_quality="standard" face_limit=15000
  2. texture  POST /v3/models/texture — regenerate textures / PBR materials
  3. convert  POST /v3/models/convert — convert format / texture size / orientation
     format="FBX" texture_size=2048
deliverables: FBX, GLB
──────────────────────────────────
```

In a TTY it then asks `Run this plan?`; answering no exits 0 with `cancelled; no credits spent`. `--yes` (auto-enabled when stdin/stdout are not TTYs, i.e. for agents and pipes) skips the question but still prints the card, so the log shows exactly what ran. `--quiet` hides it.

## Inputs (auto-detected)

| you pass | it runs |
| --- | --- |
| quoted text | text-to-model |
| one image (.png/.jpg/.jpeg/.webp/.bmp) or image URL | image-to-model |
| 2–4 images | multiview-to-model (filename hints front/back/left/right win; otherwise positional front,left,back,right; front required) |
| a model file (.glb/.gltf/.fbx/.obj/.stl) | import (add --then for processing) |
| task id / `@last` / `@name` | continue processing from that task (--then required) |

## Options

- `--for <scenario>` — `game-mobile` `game-pc` `film` `print` `ar-web` `anim` `toy`. Sets model+params+chain+format from the domain knowledge base.
- `--then <steps>` — processing chain, comma-separated. Steps: `refine texture stylize convert import rig-check rig retarget segment complete decimate smartsegment`. Args: `step:key=value,...`; bare value maps to the step's primary arg (`convert:fbx` → format, `stylize:lego` → style, `decimate:5000` → face_limit, `retarget:preset:walk` → animation). Overrides the scenario chain.
- `--model <m>` — force `tripo-v3.1` (high fidelity, default), `tripo-p1` (low-poly; face_limit 50–20000; quad/parts/geometry_quality unsupported and stripped) or `tripo-p2` (P-series preview; adds quad, face_limit 48–50000 tri / 48–25000 quad; never auto-selected). The CLI normalizes these aliases to the wire versions (`v3.1-20260211` / `P1-20260311` / `P2-20260801`) the server actually accepts. Full table with status (GA / Preview / Legacy) and official links: `tripo docs --topic commands/generate` → "Models & Versions".
- `-n, --candidates <n>` — up to 4 parallel candidates with different seeds (interactive pick when chaining).
- `--seed <n>` — fixed model_seed for reproducible geometry.
- `-p, --param key=value` — extra API parameter, repeatable. Common: `texture=false pbr=false` (bare geometry, cheaper), `texture_quality=detailed`, `face_limit=15000`, `quad=true` (forces FBX), `auto_size=true`, `negative_prompt=...`.
- `-o, --out <dir>` — artifact base dir (default `./tripo-out/<name>-<id8>/`).
- `--no-wait` — submit only, print `{"task_id"}` and exit (poll later with `tripo task watch`).
- `--no-download` — wait but skip downloads.
- `--name <name>` — history name for `@name` references.
- `--notify` — desktop notification when done.
- `--timeout <seconds>` — watch timeout (default 1800).
- `--yes` (global) — skip the plan-card confirmation; implied when headless.
- `--dry-run` — plan + validate only; nothing is uploaded or submitted, no credits spent. See below.

## Dry run (agents: validate before spending)

`tripo make ... --dry-run --json` runs the whole planning stage with **zero network calls** and prints the plan as the result on stdout: the model the dual-model rule picked, the completed request body for every call (scenario defaults merged, aliases normalized to wire values, illegal params stripped, step defaults filled in), and the outcome of every local validation. Works without an API key.

```bash
tripo make concept.png --for game-mobile --then rig,convert:fbx --dry-run --json
```

```json
{"dry_run":true,"valid":true,
 "input":"concept.png","scenario":"game-mobile",
 "model":"P1-20260311","model_reason":"explicit --model",
 "steps":[
   {"name":"image-to-model","endpoint":"/v3/generation/image-to-model","task_type":"image_to_model",
    "payload":{"input":"<upload:concept.png>","model":"P1-20260311","texture":true,"pbr":true,"texture_quality":"standard","face_limit":15000}},
   {"name":"rig","endpoint":"/v3/animations/rig","task_type":"animate_rig","payload":{"input":"<upstream>","model":"v2.5-20260210"}},
   {"name":"convert","endpoint":"/v3/models/convert","task_type":"convert_model","payload":{"input":"<upstream>","format":"FBX"}}],
 "pending_uploads":["concept.png"],
 "deliverables":["FBX","GLB"],
 "candidates":1,
 "warnings":["--then overrides the default game-mobile processing chain"],
 "errors":[],
 "cost_notes":[]}
```

- `valid` / `errors` — `errors` are blocking (illegal chain order, out-of-range `face_limit`, quad + GLTF, missing `animation` for retarget, ...). The real run would exit 2 on them before spending anything; the dry run exits 2 too, so branch on the exit code or on `valid`.
- `warnings` — adjustments the CLI applies automatically (e.g. `P1 does not support quad (removed)`); safe to proceed, but check they match your intent.
- `steps[].payload` — the exact body that would be POSTed. Local files show as `<upload:path>` (also listed in `pending_uploads`); chain steps use `<upstream>` for the task id that does not exist yet.
- A bare task id with no local history entry cannot have its type checked offline: chain legality is reported as unverified in `warnings` and checked by the real run.
- Without `--json` the same plan card as the real run is printed on stdout, followed by the warnings/errors and a verdict line.

Typical agent loop: dry-run → fix `errors` / adjust params → dry-run again until `valid` → drop `--dry-run` and run for real.

## Output (stdout, --json)

```json
{"task_id":"...","type":"convert_model","status":"success",
 "credits_consumed":145,
 "credits_breakdown":[
   {"task_id":"<generation>","type":"text_to_model","credits_consumed":110},
   {"task_id":"<texture>","type":"texture_model","credits_consumed":30},
   {"task_id":"<convert>","type":"convert_model","credits_consumed":5}],
 "output_dir":"tripo-out/knight-1a2b3c4d","files":["model.fbx","preview.png","task.json"],
 "model_file":".../model.fbx","preview":".../preview.png",
 "source_task_id":"<generation>",
 "chain":[{"task_id":"<texture>","type":"texture_model","credits_consumed":30},{"task_id":"<convert>","type":"convert_model","credits_consumed":5}]}
```

- Single task (no `--then`): `credits_consumed` is that task's spend; no `credits_breakdown`.
- Chained run: `credits_consumed` is the **total** across generation + every step, and `credits_breakdown` lists each task in run order (generation first). Human mode prints the same as `credits consumed (total): 145` followed by one indented line per task.

Exit codes: 0 ok · 2 params · 3 auth · 4 credits · 5 content policy · 6 task failed · 7 network · 9 rate limit.

## Cost behavior

The plan card shows every call before anything is submitted; balance is pre-checked before submitting; failed tasks auto-refund frozen credits. After the run, `credits_consumed` / `credits_breakdown` report what was actually billed per task. `texture=false pbr=false` skips texture credits entirely (right for 3D printing).
