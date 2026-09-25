# tripo model / anim / mesh — processing steps

All subcommands take input as: explicit argument (task id / @last / @name / file / URL) > piped stdin JSON > `@last`.
Shared options: `--json --yes -o --no-wait --no-download --timeout --name -p key=value`.
Any API parameter without a first-class flag can be passed with `-p key=value` (JSON values allowed: `-p 'part_names=["head","body"]'`).

## tripo model

```bash
tripo model refine [input]                  # only accepts text_to_model tasks
tripo model texture [input] --texture-quality detailed --texture-alignment geometry [-p pbr=true]
tripo model stylize [input] --style lego|voxel|voronoi|minecraft [--block-size 80]
tripo model convert [input] --format GLTF|USDZ|FBX|OBJ|STL|3MF \
    [--texture-size 2048] [--texture-format JPEG|PNG|OPEN_EXR|...] [--face-limit N] \
    [--quad] [--flatten-bottom] [--fbx-preset blender|3dsmax|mixamo] \
    [--export-orientation +x|-x|+y|-y] [--scale-factor 1.5] [--auto-size] \
    [--pivot-to-center-bottom] [--export-vertex-colors]
tripo model import <file-or-url>            # GLB/GLTF/FBX/OBJ/STL ≤150MB
```

| step | input accepted | params |
| --- | --- | --- |
| `refine` | successful `text_to_model` task only | `model` (default `tripo-v3.1`) |
| `texture` | task / file / URL (file/URL is imported implicitly) | `model` `v3.0-20250812` (default) / `v2.5-20250123`; `texture_quality` standard/detailed/extreme; `pbr` (default true); `texture_seed`; `texture_alignment` original_image/geometry |
| `stylize` | task / file (no URL) | `style` lego/voxel/voronoi/minecraft; `block_size` 32–128 (minecraft only, default 80) |
| `convert` | task / file | see table below; `format` required |
| `import` | file / URL | GLB / GLTF / FBX / OBJ / STL ≤150 MB. `.gltf` references external files, so it only works as a URL — upload `.glb` |

### convert parameters (full)

| group | param | default | notes |
| --- | --- | --- | --- |
| basic | `format` | — | `GLTF` `USDZ` `FBX` `OBJ` `STL` `3MF` (3MF = single colour) |
| mesh | `quad` | false | quad remesh; **cannot export GLTF** — use FBX/OBJ/USDZ |
| mesh | `force_symmetry` | false | only with `quad=true` |
| mesh | `face_limit` | keep original | target polycount |
| mesh | `flatten_bottom` / `flatten_bottom_threshold` | false / 0.01 | flat base for printing |
| texture | `texture_size` | 4096 | diffuse size in px |
| texture | `texture_format` | JPEG | `BMP` `DPX` `HDR` `JPEG` `OPEN_EXR` `PNG` `TARGA` `TIFF` `WEBP` |
| texture | `bake` | true | bake advanced materials into base textures |
| texture | `pack_uv` | false | pack all UVs into one layout |
| texture | `export_vertex_colors` | false | **OBJ / GLTF only** |
| export | `pivot_to_center_bottom` | false | pivot at bottom centre |
| export | `scale_factor` | 1 | uniform scale |
| export | `with_animation` | true | keep skeleton + animation data |
| export | `animate_in_place` | false | strip root motion |
| export | `part_names` | — | export only these parts (names from a segment task) |
| export | `export_orientation` | `+x` | forward axis `+x` / `-x` / `+y` / `-y` — set orientation **here**, as the last step (generation-time `export_orientation` is not inherited by other steps) |
| export | `fbx_preset` | blender | `blender` / `3dsmax` / `mixamo` (FBX only) |

Billing: any non-default convert option bills as "complex convert" (pricier than a plain format swap).

## tripo anim

```bash
tripo anim check [input]                    # rig-check: {"riggable":true,"rig_type":"biped"}; GLB input only
tripo anim rig [input] [--rig-type biped|quadruped|hexapod|octopod|avian|serpentine|aquatic] \
    [--spec tripo|mixamo] [--out-format glb|fbx]      # CLI defaults model=v2.5-20260210 (all body types)
tripo anim retarget [input] --animation preset:walk [preset:run ...] \
    [--out-format glb|fbx] [--animate-in-place]
```

| step | input accepted | params |
| --- | --- | --- |
| `check` (rig-check) | task / file / URL — **GLB only**, ≤150 MB | none. Output: `riggable` (bool) + recommended `rig_type` (one of the 7 below). Run it first: not riggable → stop before spending rig credits |
| `rig` | task / file | `model`: `rig-v2.0` (wire `v2.5-20260210`, **CLI default**, presets for all body types) / `rig-v1.0` (wire `v1.0-20240301`, server default, biped-only presets); `rig_type` biped/quadruped/hexapod/octopod/avian/serpentine/aquatic (default biped — use rig-check's value); `spec` tripo/mixamo; `out_format` glb/fbx |
| `retarget` | **rig task id only** | `animation` (one) or `animations` (list, ≤5, billed per animation); `out_format` glb/fbx; `bake_animation` (default true, glb only); `export_with_geometry` (default true); `animate_in_place` (default false) |

- Marketing names `rig-v1.0` / `rig-v2.0` are normalized to the wire versions automatically (sending them raw is a 400).
- Mixamo / Unity Humanoid → `--spec mixamo` (+ `--fbx-preset mixamo` at convert time).
- Game code drives movement → `--animate-in-place`.
- The preset set depends on **which rig model the upstream rig task used**.

### Presets for rig v2.0 / v2.5 (all rig types)

`preset:idle` `preset:walk` `preset:run` `preset:dive` `preset:climb` `preset:jump` `preset:slash` `preset:shoot` `preset:hurt` `preset:fall` `preset:turn`
Body-specific: `preset:quadruped:walk` `preset:hexapod:walk` `preset:octopod:walk` `preset:serpentine:march` `preset:aquatic:march`

### Presets for rig v1.0 (biped only, 90+)

All prefixed `preset:biped:`
- basic: `idle` `walk` `run` `run_upstairs` `turn` `jump` `jump_down` `jump_rope_01` `jump_rope_02` `fall` `climb` `dive` `swim` `surf` `flip` `sit` `standing_relax` `look_around` `wait` `swagger`
- dance: `dance_01` … `dance_06` `freaky`
- performance: `sing_01` … `sing_04` `cheer`
- emotion: `clap` `bow` `greet_01` … `greet_04` `wave_goodbye_01` `wave_goodbye_02` `agree` `heart_pose` `hug` `fold_arms` `laugh_01` `laugh_02` `cry` `sob` `afraid` `frightened` `scared_01` `scared_02` `angry_01` … `angry_03` `depressed` `frustrated_01` `frustrated_02` `complain_01` `complain_02` `victory_celebration` `defeat_02` `defeat_03`
- daily: `scratch` `make_a_call_01` `make_a_call_02` `play_mobile_game` `play_video_game` `dig` `chop` `shovel` `lift_heavy`
- sports: `warm_up` `press-up` `cross_body_crunch` `basketball_shot` `crossover_dribble` `dribble` `pitch_baseball` `golf` `volleyball` `football_catch` `football_save` `football_pass`
- combat: `box_01` … `box_03` `front_kick_01` `front_kick_02` `slash` `shoot` `fire` `cast_a_spell` `hurt` `hit_to_body_01` `hit_to_body_02` `hit_to_head` `hit_to_side` `hit_to_stomach` `flee_01` `flee_02`

## tripo mesh

```bash
tripo mesh segment [input] [--model v1.0-20250506|v2.0-20260430]
tripo mesh complete [input] [--completion-mode ai_completion|quick_cap]   # needs a segment task
tripo mesh decimate [input] --face-limit 5000 [--quad] [--no-bake]        # 500–20000 tri / 500–10000 quad
tripo mesh smartsegment <file-or-url> [--seg-type image|model] [--granularity coarse|medium|fine] [--hint "..."]
```

| step | input accepted | params |
| --- | --- | --- |
| `segment` | task / file / URL | `model` `v1.0-20250506` (default, geometry-based) / `v2.0-20260430` (Beta, semantic labels + geometry). **v2 only**: `segmentation_granularity` simple/balanced/detailed (default balanced), `split_by_connectivity` (default true), `ref_image` file_token/URL — when `ref_image` is set the other two are ignored; setting `ref_image` on v1 → `1004` |
| `complete` | **segment task only** | `completion_mode` `ai_completion` (AI diffusion, default) / `quick_cap` (fast hole-fill, no AI); `part_names` (default: all parts); `model` `v1.0-20250506` (only version) |
| `decimate` | task / file | `face_limit` (docs quote 1000–20000; CLI accepts 500–20000 tri / 500–10000 quad); `quad`; `bake` (default true — bake textures onto the low-poly, right for LODs); `part_names`. `-p model=v1.0`: up to 2,000,000 tri / 150,000 quad but `face_limit` becomes required and `bake`/`part_names` are unsupported |
| `smartsegment` | **file / URL only (no task ids)** | `seg_type` `image` (photo → auto-model → segment, **85 credits**) / `model` (existing **GLB only** → segment, **55 credits**; CLI default); `granularity` coarse/medium/fine (default medium); `hint` free text describing the parts; `transform` 4×4 column-major matrix required for `model` — the CLI auto-fills identity |

- `segment` vs `smartsegment`: segment only splits an existing model; smartsegment is the end-to-end pipeline (asset → auto modelling → segmentation).
- smartsegment output: `prompt` (comma-separated part labels), `mask_url` (PNG semantic mask), `seg_model_url` (segmented GLB), `seg_task_id` (inner segmentation task), `model_task_id` (inner image_to_model / import task). Task types: `smartsegment_image` / `smartsegment_model`.
- `mesh complete` only accepts segmentation tasks; segmented / completed parts can then be exported selectively via `convert -p 'part_names=[...]'`.
