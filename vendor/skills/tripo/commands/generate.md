# tripo generate — deterministic endpoint access

Use `tripo make` unless you need exact endpoint control. All subcommands accept the shared task options (`--json --yes -o --no-wait --no-download --timeout --name -p key=value`).
Everything below is the full parameter reference from the official API docs — you should not need to consult the website.

## 3D

```bash
tripo generate text-to-model "a ceramic teapot" [--model tripo-v3.1|tripo-p1|tripo-p2] [-p face_limit=15000] ...
tripo generate image-to-model photo.png [-p texture_alignment=original_image] [-p orientation=align_image]
tripo generate multiview-to-model front.png back.png [left.png right.png]
```

### P Series (`tripo-p1` / `tripo-p2`) — same endpoints, different model

The P series (low-poly, clean topology) uses the **same three endpoints**; only the `model` value changes. The official docs document it as a separate "P Series" tab on each generation page — this is the direct entry point:

```bash
tripo generate text-to-model "a low poly knight" --model tripo-p1 -p face_limit=8000          # → model: P1-20260311
tripo generate image-to-model photo.png --model tripo-p2 -p quad=true -p face_limit=12000      # → model: P2-20260801 (Preview)
tripo generate multiview-to-model front.png back.png --model tripo-p1
```

| endpoint | H series (standard) page | P series page |
| --- | --- | --- |
| `POST /v3/generation/text-to-model` | `…/docs/generation-text-to-model/standard` | <https://developers.tripo3d.ai/en/docs/generation-text-to-model/p> |
| `POST /v3/generation/image-to-model` | `…/docs/generation-image-to-model/standard` | <https://developers.tripo3d.ai/en/docs/generation-image-to-model/p> |
| `POST /v3/generation/multiview-to-model` | `…/docs/generation-multiview-to-model/standard` | <https://developers.tripo3d.ai/en/docs/generation-multiview-to-model/p> |

(cn: replace `developers.tripo3d.ai/en` with `developers.tripo3d.com/zh`.) P-series constraints — face_limit ranges, unsupported params, P2's `quad` — are in the table below; the CLI enforces them locally.

### 3D models (`--model`) — Models & Versions

Keywords: model versions · H series (v3.x) · P series (P1 / P2) · Preview · quad · alias → wire value.

| alias (what you type) | wire value (what the API receives) | status | positioning | notes |
| --- | --- | --- | --- | --- |
| `tripo-v3.1` (default) | `v3.1-20260211` | GA | latest high-precision; AAA / 3D printing | full feature set |
| `tripo-p1` | `P1-20260311` | GA | best low-poly; games / UGC / mobile | face_limit 48–20000 (CLI enforces ≥50); **no** `quad` `smart_low_poly` `generate_parts` `geometry_quality`; ~2s mesh; extra `export_uv` |
| `tripo-p2` | `P2-20260801` | **Preview** (2026-08) | P1 upgrade (P series) | adds `quad` (forces FBX); face_limit 48–50000 tri / 48–25000 quad (validated locally); still **no** `smart_low_poly` `generate_parts` `geometry_quality` (stripped with a warning); credits 100 (no texture) / 110 / 120 / 130 for standard / detailed / extreme. Explicit `--model` only — the CLI never auto-selects it |
| `tripo-v3.0` / `tripo-v2.5` | `v3.0-20250812` / `v2.5-20250123` | Legacy | previous generations | only when the human asks |

**Alias vs wire value.** `tripo-*`, `p1`, `p2`, `v3.1` … are CLI-side aliases; the CLI always sends the dated wire value in the `model` field (`--model tripo-p2` → `"model": "P2-20260801"`). The v3 server whitelist accepts wire values only — sending an alias straight to the API returns 1004 `invalid model` with the allowed list. `task.json` records the wire value that was actually used. `tripo-turbo` / `tripo-v2.0` appear in some docs but are **not** on the v3 whitelist (400).

Official docs (ov / cn):
- Models & Versions: <https://developers.tripo3d.ai/en/docs/models-and-versions> · <https://developers.tripo3d.com/zh/docs/models-and-versions>
- P Series model detail: <https://developers.tripo3d.ai/en/models/p1> · <https://developers.tripo3d.com/zh/models/p1>
- P Series endpoints: `…/docs/generation-text-to-model/p`, `…/docs/generation-image-to-model/p`, `…/docs/generation-multiview-to-model/p` (the `/standard` tab on each page is the H-series version)

### Parameters (text / image / multiview-to-model)

| param | default | applies to | notes |
| --- | --- | --- | --- |
| `prompt` | — | text | ≤1024 chars |
| `negative_prompt` | — | text | ≤255 chars |
| `input` | — | image | `file_` token, `http(s)://` URL or `task_` id (e.g. a text-to-image task) — the CLI uploads local files for you |
| `inputs` | — | multiview | see "multiview inputs" below |
| `model_seed` / `image_seed` / `texture_seed` | random | all | geometry / text-to-image stage / texture seeds — the key to reproducibility (`task.json` records them) |
| `face_limit` | adaptive | all | max polycount; P1 48–20000, P2 48–50000 |
| `texture` | `true` | all | set `false` for bare geometry (print / re-texture later) — saves credits |
| `pbr` | `true` | all | PBR maps; **forces `texture=true`** |
| `texture_quality` | `standard` | all | `standard` / `detailed` / `extreme` (price tiers) |
| `geometry_quality` | `standard` | v3.x | `detailed` = Ultra mode (extra HD credit) |
| `auto_size` | `false` | all | scale to real-world metres |
| `quad` | `false` | v3.x, P2 | quad mesh; **forces FBX output** (quads cannot live in GLB) |
| `smart_low_poly` | `false` | v3.x | hand-crafted-style low-poly; face_limit 500–20000 tri / 500–10000 quad |
| `generate_parts` | `false` | v3.x | editable segmented parts — see rules below |
| `compress` | — | v3.x | `geometry` = meshopt compression |
| `export_orientation` | `+x` | all | forward axis `+x` / `-x` / `+y` / `-y` — see warning below |
| `export_uv` | `true` | P series only | `false` = faster, smaller file (no UV unwrap) |
| `enable_image_autofix` | `false` | image | auto-repair low-quality inputs |
| `texture_alignment` | `original_image` | image, multiview | `original_image` (match the picture) / `geometry` (match the mesh) |
| `orientation` | `default` | image, multiview | `align_image` = align the model to the input viewpoint |

Only valid when `model >= tripo-v3.0`: `texture_quality` `geometry_quality` `auto_size` `quad` `smart_low_poly` `generate_parts` `compress`.

**`generate_parts` rules (server-enforced):**
- `texture=true` or `pbr=true` (including simply omitting `texture`, which defaults to true) → request rejected with `1004`. The CLI flips both to `false` for you and warns; re-texture afterwards with `tripo model texture`.
- `quad=true` → quad is ignored; parts come back as triangle meshes.
- `smart_low_poly=true` → smart_low_poly wins and **no parts are produced**.

**`export_orientation` warning:** it applies to this generation only. Downstream tasks (texture, rig, retarget, convert, …) do **not** inherit it — they read the model in default orientation and produce a wrongly-oriented result while still reporting `success`. If you will post-process, leave it unset and set `export_orientation` on the final `convert` step instead.

### Multiview inputs

The API accepts three `inputs` shapes (never mix them):
- **view-key (recommended)**: `[{"front":…},{"back":…}]` with keys `front/left/back/right`; `front` required, ≥2 views, order irrelevant.
- **legacy positional**: exactly 4 strings `[front, left, back, right]`, `""` skips a slot.
- **task_id**: `[{"task_id":"<image-to-multiview or edit-multiview task>"}]` to reuse a 4-view sheet (source task must be `success`).

The CLI builds view-key payloads from your files: filename hints (`front|back|left|right`, or 正面/背面/左/右) win; otherwise positional order front, left, back, right. A front view is mandatory.

## Images (2D pipeline before 3D)

```bash
tripo generate text-to-image "front view of a knight, T-pose" [-p template=t_pose] [--model seedream_v4]
tripo generate image-to-image sketch.png --prompt "make it look like clay" [--model seedream_v5]
tripo generate image-to-multiview photo.png     # 1 image → 4-view sheet
tripo generate edit-multiview <multiview-task-id> -p 'prompts=[{"view":"front","prompt":"add a sword"}]'
tripo generate image-to-splat photo.png         # gaussian splat
```

### Image models (`--model`)

| model | provider | status | notes |
| --- | --- | --- | --- |
| `seedream_v4` | ByteDance | GA | text-to-image default (balanced); **not accepted by image-to-image** |
| `seedream_v5` | ByteDance | GA | image-to-image default; higher quality |
| `gemini-2.5-flash` / `gemini-3-pro` / `gemini-3.1-flash` | Google | GA | fast / high quality / latest fast. Backend aliases `banana` / `banana_pro` / `banana2` are also accepted |
| `chat_image_1` / `chat_image_1.5` | OpenAI | retiring 2026-10-23 / 2026-12-01 | GPT image; 1.5 = higher quality — move to `chat_image_2` |
| `chat_image_2` | OpenAI | GA | GPT latest |

Image model ids are sent as-is (no alias normalization). Full list with retirement dates: <https://developers.tripo3d.ai/en/docs/models-and-versions>.

### Image parameters

| param | default | endpoint | notes |
| --- | --- | --- | --- |
| `prompt` | — | t2i (required), i2i | ≤1024 chars; i2i: required unless `template` is set |
| `input` | — | i2i, i2mv, edit-mv, splat | `file_` token / URL (i2i also accepts a `task_` id) |
| `inputs` | — | i2i | multiple reference images: seedream ≤4, gemini ≤10 (gpt ≤16); reference them in the prompt as `[image 1]`, `[image 2]`… |
| `template` | — | t2i, i2i | `asset_extraction` `character_completion` `t_pose` `head_extraction` `3d_enhance` `variants` `print_clay` `figure` |
| `t_pose` | `false` | t2i, i2i | boolean shortcut: convert the subject to a T-pose |
| `sketch_to_render` | `false` | t2i, i2i | turn a sketch into a rendered image |
| `model_seed` | random | splat | same seed + same image = repeatable `.splat` |

- `template=t_pose` (or `t_pose=true`) is the golden pre-step for the animation pipeline; `3d_enhance` cleans a photo before image-to-model; `print_clay` previews a single-colour print look.
- Sizes are billed in 1K / 2K / 4K tiers; `aspect_ratio` is only honoured by the gemini family.
- `image-to-multiview` output: `front_view_url` `left_view_url` `back_view_url` `right_view_url` — feed them (or the task id, see above) to `multiview-to-model`.
- `edit-multiview` takes a successful `image-to-multiview` task; `prompts` is 1–4 `{view, prompt}` objects.
- `image-to-splat` returns a `.splat` file in `output.model_url` (not a mesh — no texture / rig / convert downstream). Fixed **30 credits**, ~4 minutes. Input PNG / JPEG / WebP ≤20 MB, ≥256×256 px, subject clear and centred. Use image-to-model when you need an editable mesh.
