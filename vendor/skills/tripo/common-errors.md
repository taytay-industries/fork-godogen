# Common errors & fixes

| exit | api code | meaning | fix |
| --- | --- | --- | --- |
| 3 | 1002 | authentication failed (invalid/missing API key) | set `TRIPO_API_KEY` or run `tripo login`; check the key wasn't revoked |
| 3 | 1005 | forbidden (no permission for this resource) | check account permissions |
| 2 | 1003/1004 | malformed request / invalid parameter | check spelling against `tripo docs --topic commands/<cmd>`; the CLI already strips illegal P1 params. Classic 1004s: `generate_parts=true` with texture/pbr on, `ref_image` on segment v1, `quad=true` on P1, non-GLB input to smartsegment `model` / rig-check. `invalid model`: the API only accepts dated wire values (`P2-20260801`, `v3.1-20260211`…) — pass the CLI alias (`--model tripo-p2`) and let the CLI normalize, or the wire value itself; never `tripo-*` straight to the API. Table: `commands/generate` § "Models & Versions" |
| 9 | 1007 | per-API-key rate limit | wait and retry with backoff; honour `Retry-After` / `X-RateLimit-Reset` headers |
| 9 | 2000 | per-account concurrency pool full (see table below) | wait for a task in that category to finish, or lower `--concurrency` in batch; other categories are unaffected |
| 8 | 2001 | task not found | task ids are account-scoped — same key that created it? right region (ov/cn)? |
| 2 | 2003 | empty input file / unreachable URL | verify the file isn't empty and the URL is publicly accessible |
| 2 | 2004 | unsupported file type | images: PNG/JPEG/WebP/BMP/TIFF ≤20MB; models: GLB/FBX/OBJ/STL ≤150MB (.gltf not uploadable — use .glb or a URL) |
| 2 | 2005/2006/2007 | upstream task wrong type / not successful | the chain needs a successful task of the right type (the CLI validates locally first) |
| 5 | 2008 | content policy violation | change the prompt/image |
| 2 | 2009 | prompt contains invalid characters | remove unusual characters from the prompt |
| 4 | 2010 | insufficient credits | `tripo topup` (human action); `tripo balance` to check |
| 2 | 2011/2012 | animation chain input invalid | rig-check needs a model-producing task; retarget needs a rig task |
| 2 | 2015/2016/2017 | version/type deprecated or invalid | drop the explicit `--model`; the CLI default is current |
| 2 | 2018 | too complex to remesh | lower `face_limit` or simplify the input model |
| 8 | 2019 | file not found (token expired?) | re-upload; file tokens are short-lived |
| 2 | 2020/2021/2022 | bad image URL / file too large / image too large | fix the URL or shrink the file |
| 7 | 1000/1001 | server-side error | 1000 auto-retries; if persistent, contact support with the `request_id` |
| 6 | — | task failed server-side | frozen credits auto-refund; `tripo redo` often succeeds with a new seed |
| 7 | — | network/5xx | auto-retried 3×; check `tripo doctor`; region mismatch (ov/cn) is a common cause |

## Concurrency pools (default per account; error 2000 when full)

| category | task types | default concurrency |
| --- | --- | --- |
| 3D generation — H series | text/image/multiview-to-model on `tripo-v3.x` / `v2.5` | 10 |
| 3D generation — P series | text/image/multiview-to-model on `tripo-p1` / P2 | 5 |
| image generation | text-to-image, image-to-image, image-to-multiview, edit-multiview | **1** |
| animation | rig-check, rig, retarget | 10 |
| model processing | texture, convert, refine | 5 |
| mesh operations | segment, complete, decimate | 10 |

Pools are independent: a full H-series pool does not block P-series or image tasks. Image generation is serial by default — do not fan out text-to-image jobs. Higher limits are granted on request via support.

## Frequent local validations (caught before spending credits)

- `refine` only accepts a successful `text_to_model` task
- `complete` only accepts a `segment` task; `retarget` only accepts a `rig` task
- quad + GLTF export → rejected (quads cannot be stored in glTF); use FBX/OBJ/USDZ
- P1 + face_limit outside 50–20000 → rejected with a suggestion to use v3.1
- multiview without a front view → rejected (name a file "front" or pass it first)
- `-n` with `--then` needs an interactive terminal (pick the winner first, then chain)

All of these surface in `tripo make ... --dry-run --json` as `errors` (blocking) or `warnings` (auto-adjusted) before anything is uploaded or submitted.

## Weird-but-normal

- `model_url` in task output points to a file that may be named `pbr_model` etc. — normal, just download it (the CLI does).
- Output URLs expire in ~5 minutes — never cache them; re-run `tripo task get <id> --download`.
- `frozen` balance = holds for running tasks; it settles or refunds automatically.
- `credits_consumed` / `balance` / `frozen` are decimals (e.g. `48.00`) — parse as float, never as int.
- Task status can also be `banned` (content policy — change the input) or `expired` (output files gone — regenerate); the CLI treats both as terminal failures.
- A downstream step after a generation that used `export_orientation` succeeds but comes out **wrongly oriented** — no error is raised. Set the orientation on the final `convert` step instead.
- `generate_parts` with `smart_low_poly=true` silently produces no parts (smart_low_poly wins); with `quad=true` the parts are triangles.
- `image-to-splat` yields a `.splat`, not a mesh — texture / rig / convert steps cannot follow it.
