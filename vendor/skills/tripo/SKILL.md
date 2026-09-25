---
name: tripo
description: Generate, rig, animate, convert, and inspect 3D models with the tripo CLI (Tripo 3D). Full command, example, and error reference for the CLI that asset-gen uses for GLB models.
license: MIT
---

# Tripo CLI Skill

You (an AI coding agent) can generate production-ready 3D assets with the `tripo` CLI.
One command turns a text prompt or an image into local files: a 3D model (glb/fbx/stl/...), a `preview.png` render, and a `task.json` record.

## Install & auth

```bash
npm install -g tripo-cli        # or: npx tripo-cli ...
export TRIPO_API_KEY=tsk_...    # highest-priority auth; no interaction needed
                                # (PowerShell: $env:TRIPO_API_KEY = "tsk_...")
tripo doctor                    # verify key, network, balance
```

If there is no key, run the device login **yourself** — it works without a TTY:

```bash
tripo login --region ov      # ov = international, cn = China mainland
```

It prints a verification URL and a one-time code, then blocks until the human
approves in a browser (up to ~15 minutes — do not kill it early). Relay the URL
and code to the human and tell them: sign in on that page first if it asks
(sign-up gives free credits), enter the code, pick an API key if the account has
several (one is created automatically if there are none), click Authorize. The
key is then saved locally; never ask the human to paste a key into the chat. If
the code expires (exit 3), just run the same command again.

Regions (ov = international, cn = China mainland) share one CLI: `tripo login --key tsk_...` auto-detects which region the key belongs to. On exit code 3 (auth), run `tripo doctor` — it diagnoses key-vs-region mismatches and prints the exact fix (`tripo config set region cn|ov`).

## Behavior rules (read first)

1. **`tripo make` is synchronous and blocking.** It prints a plan card on stderr (one numbered line per API call: endpoint, purpose, args), then submits, polls, downloads artifacts, and exits. In a TTY it asks "Run this plan?" first; `--yes` (auto-enabled when headless) skips the prompt but still prints the card. Wait for the process to finish and read the final JSON from stdout. Do NOT re-implement polling, do NOT add your own timeout shorter than 15 minutes, do NOT stop just because you saw a task_id in the logs.
2. **stdout is the contract; stderr is commentary.** With `--json` (auto-enabled when piped), stdout carries exactly one final JSON line. Progress/logs go to stderr.
3. **Artifacts are local files.** The result JSON has `output_dir`, `model_file`, `preview`. Look at `preview.png` to judge quality; re-roll with `tripo redo` if needed.
4. **Exit codes are stable** — branch on them:
   - 0 success · 2 usage/params · 3 auth · 4 insufficient credits (tell the human to run `tripo topup`) · 5 content policy · 6 task failed (credits auto-refunded) · 7 network · 8 not found · 9 rate limit (retry with backoff)
5. **Never invent parameters.** Unknown `--param key=value` pairs pass through to the API; stick to documented ones. The full parameter/model/preset reference from the official API docs is bundled: `tripo docs --topic commands/generate` (3D + image generation) and `tripo docs --topic commands/process` (texture/convert/rig/retarget/mesh) — read those instead of browsing the website.
6. **Validate before spending: `--dry-run --json`.** Same command plus `--dry-run` prints the plan as JSON with zero network calls and no credits: the chosen `model`, the completed `steps[].payload` for every API call, `warnings` (auto-adjustments) and `errors` (blocking; exit 2). When `valid` is true, re-run without `--dry-run`. Details: `tripo docs --topic commands/make` § "Dry run".
7. **Don't pick legacy model versions.** The CLI auto-selects `tripo-v3.1` (high fidelity) or `tripo-p1` (low-poly, face budget ≤ 20000). Only override `--model` when the human asks (e.g. `--model tripo-p2` for the P-series **Preview** with quad support, or `tripo-v3.0` / `tripo-v2.5` for reproducing old projects). `tripo-*` names are CLI aliases — the CLI sends the dated wire value (`tripo-p2` → `P2-20260801`); the API rejects the alias itself with 1004. Alias ↔ wire ↔ status table: `tripo docs --topic commands/generate` ("Models & Versions").

## The one command you usually need

```bash
tripo make "a medieval knight, T-pose" --for game-mobile --json --yes
tripo make concept.png --for print --json --yes
tripo make front.png back.png --json --yes                # 2-4 views → multiview
tripo make hero.glb --then texture,rig --json --yes       # import + process
tripo make @last --then convert:fbx --json --yes          # continue from last task
```

- `--for` scenario presets: `game-mobile` `game-pc` `film` `print` `ar-web` `anim` `toy`
- `--then` chain steps: `refine texture stylize convert import rig-check rig retarget segment complete decimate smartsegment`
  - step args: `convert:format=FBX,texture_size=2048` (bare value = primary arg: `convert:fbx`, `stylize:lego`, `decimate:5000`)
- Output JSON: `{"task_id","type","status","credits_consumed","output_dir","files",["model_file"],["preview"],["chain"],["credits_breakdown"]}` — with `--then`, `credits_consumed` is the **total** for the run and `credits_breakdown` itemizes every task (`[{task_id,type,credits_consumed}]`, generation first)

## Pipes (composing steps yourself)

Downstream commands read the upstream task from stdin:

```bash
tripo make cat.png --json | tripo anim rig --json | tripo anim retarget --param animation=preset:walk --json
```

## Other commands

| command | purpose |
| --- | --- |
| `tripo task get/watch <id> --download` | inspect / block on / download an existing task |
| `tripo balance` / `tripo usage` | credits: `{"balance","frozen"}` / recent spend |
| `tripo redo [@last]` | same request, new seed |
| `tripo view [@last]` | (humans) open a local 3D preview; agents read `preview.png` instead |
| `tripo files upload <path>` | get a `file_token` |
| `tripo batch run manifest.yaml` | bulk jobs, resumable |
| `tripo mcp` | run as an MCP server (tools: tripo_make, tripo_task_get, tripo_task_wait, tripo_balance, tripo_history) |
| `tripo docs --topic commands/<name>` | print detailed docs for any command |

## Detailed docs in this package

- `commands/` — one file per command with every flag and parameter
  - model versions · H series (`tripo-v3.x`) · P series (`tripo-p1`, `tripo-p2` Preview) · alias → wire value · GA / Preview / Legacy status · quad → `commands/generate` § "Models & Versions" (also the P Series endpoint entry points)
- `examples/` — copy-paste recipes per scenario (game/print/animation/...)
- `common-errors.md` — error table with fixes

Print any of them: `tripo docs --topic examples/game-asset`.
