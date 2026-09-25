# Godot engine guide

Stack: **Godot 4 (.NET / Mono build)**, **C#**. All Godot C# classes must be `partial`.

## Project shape

- `project.godot` — config, input actions, display, physics. **Match version-sensitive fields to the installed toolchain** (`config_version`, and in `.csproj` the `Godot.NET.Sdk/...` version + `TargetFramework`) — run `godot --version` / `dotnet --version` and don't hardcode values from memory; on an existing project preserve them. For 3D, set `3d/physics_engine="Jolt Physics"` and a fixed `physics_ticks_per_second`.
- `{ProjectName}.csproj` — name must match `assembly_name`; `<EnableDynamicLoading>true</EnableDynamicLoading>`.
- `scripts/*.cs` runtime behavior · `scenes/*.tscn` scenes · `assets/` **only** files the running game loads (keep generation inputs/refs outside it).
- Build gate: `dotnet build`, then `godot --headless --import` after asset changes, then `godot --headless --quit` (RID-leak warnings on headless exit are benign).

The user watches by running the project themselves (`godot --path .` or the editor) — keep it building and importing cleanly so each run reflects current state.

## Scenes are generated at build time, not by hand

Write scenes as **C# `SceneTree` scripts** that run once headless and emit a `.tscn`: `godot --headless --script scenes/BuildX.cs`. The builder runs from the compiled assembly — `dotnet build` first, or an edited builder silently re-emits the old scene. A builder builds the node hierarchy, sets properties, attaches scripts, packs, and `Quit()`s — it contains **no** runtime logic (no `_Ready`/`_Process`, signals, or game state). Build **leaf scenes first**, parents after.

The serialization rules below are silent-failure — they pass compilation and drop nodes or bloat files only in the saved `.tscn`:

- **Owner chain:** every node must have `Owner` set to the scene root or it won't serialize. After building, walk the tree and set `child.Owner = root` on all descendants — but **do not recurse into instantiated GLB/`.tscn` nodes** (those have a non-empty `SceneFilePath`). Recursing into a GLB inlines all its meshes as text → 100MB+ `.tscn`.
- **Validate the pack:** count nodes before packing, `Instantiate()` the `PackedScene` after, and compare counts; gate `ResourceSaver.Save()` on the match. A silent drop otherwise looks like success.
- **`SetScript()` disposes the C# wrapper** — set scripts *last*, after the hierarchy is built. For the root, add it under a temp `Node`, set the script, then re-fetch it via `temp.GetChild(0)` before packing.

Sketch of the shared save path:

```csharp
void PackAndSave(Node root, string path) {
    SetOwnerRecursive(root, root);               // skip nodes with SceneFilePath set
    int expected = CountNodes(root);
    var packed = new PackedScene();
    if (packed.Pack(root) != Error.Ok) { Quit(1); return; }
    var test = packed.Instantiate(); int got = CountNodes(test); test.Free();
    if (got < expected) { GD.PushError("nodes dropped"); Quit(1); return; }   // serialization failed silently
    ResourceSaver.Save(packed, path);
    Quit(0);
}
```

`tools/SceneKit.cs` implements this save path plus measured GLB placement (`Model`, `Place`, `Measure`, `Slab`) — use it rather than rewriting it per scene.

GLB models: instantiate the `PackedScene`, measure the `MeshInstance3D` AABB to scale, and use a **primitive** collision shape (Box/Sphere/Capsule) from the AABB — never `CreateTrimeshShape()`/`CreateConvexShape()` on imported meshes (drops to <1 FPS).

## Quirks worth knowing (silent-failure)

Most Godot behavior the model already knows; these few fail with no error:

- **On macOS a fatal error hangs instead of exiting.** Godot reports it in an `NSAlert` modal that `--headless` can't dismiss, so the process idles at 0% CPU forever (a missing main scene does it too). Run every `godot` call under `timeout`; exit 124 is the failure. Output ending at `.NET: Initializing module...` means `GodotSharp/` wasn't found — `godot` on `PATH` is a symlink rather than a wrapper script.
- **`ArrayMesh.GenerateNormals()`** is required for a procedural mesh to *receive* shadows. Without it (or with `CullMode.Disabled` as a "safety net"), shadows silently vanish — fix winding instead.
- **MultiMeshInstance3D + GLB** loses the mesh on pack/save; use individual instances. `MaterialOverride` on GLB-internal nodes also won't serialize (owner is skipped) — use a procedural `ArrayMesh` when a custom material is needed.
- **Raycasts don't reliably hit `ConcavePolygonShape3D`** (trimesh) — use a shape query or sample terrain height analytically.
- **`.gdignore`** in a directory makes the importer skip it silently — only `screenshots/` should have one, never `assets/`.
- **C# enum names:** training data is GDScript-biased, so guessed C# enum names are often wrong (`BGMode.Sky`, not `BGModeEnum.Sky`). Verify against the installed Godot — read the C# API in the Godot docs/assemblies rather than guessing.
- Frame-rate-independent damping: `speed *= Mathf.Exp(-rate * delta)`, not `speed *= (1 - drag)` per tick.

## Generated models and characters

- **Facing:** `tools/Facing.cs` renders every GLB in a folder unrotated, seen from +Z (`FACING_DIR=res://assets/props uv run tools/capture.py record --script tools/Facing.cs --seconds 0.2 --format png --out screenshots/facing`). Set each model's yaw from that frame before placing a batch.
- **Rigged clips:** `tools/AnimLab.cs` puts one character on a treadmill stage, samples each clip from the skeleton, and reports root drift, loop seam pops, freezes, foot slide, heading, and gait as PASS/WARN/FAIL (FAILs land in `godot.log`, so `capture.py` lists them). Record it to see the problem the way the game would:

  ```bash
  uv run tools/capture.py record --script tools/AnimLab.cs --seconds 8 --out screenshots/animlab -- ++ \
      --model res://assets/hero.glb --anim res://assets/hero_walk.glb --clip walk --cycles 3 --height 1.2
  ```

  Then bake the fixes into a clean GLB the game loads with no fix-up code, and re-check it with **no** fix flags — it must pass:

  ```bash
  godot --headless --path . --script tools/AnimLab.cs ++ --model res://assets/hero.glb --anim res://assets/hero_walk.glb \
      --anim res://assets/hero_idle.glb --clip walk,idle --cycles 0 --strip-root --fix-loop --height 1.2 --export res://assets/clean/hero.glb
  godot --headless --import
  uv run tools/capture.py record --script tools/AnimLab.cs --seconds 8 --out screenshots/animlab_clean -- ++ \
      --model res://assets/clean/hero.glb --clip walk --game-forward +Z
  ```

  The export merges the clips, turns the model so travel is +Z, scales it, and writes `hero.json` (clip lengths, authored ground speed — drive `SpeedScale` from it). `godot --path . --script tools/AnimLab.cs ++ … --loop` keeps a live window cycling the clips; it restarts itself when the project is rebuilt. Strip root motion in the hip's *parent* frame (what `--strip-root` does); stripping in hip-local space fakes a side-to-side sway with sliding feet.
- Whole-frame capture review misses small things popping — a character snapping back each loop reads as a few pixels. For anything small that moves, record its world position per frame in the capture script and `GD.PushError` on a jump, so the review lists it.

## Capture (proof video)

Hardware **Vulkan** (Metal on macOS) gives correct rendering and is required for video; software Vulkan (`llvmpipe`/`lavapipe`) can still do stills but skip video and report it. On WSL, hardware Vulkan is Mesa's `dzn` (see `setup.md`), and it renders SSAO as a regular dot grid — a driver bug, not the scene. macOS has no `xvfb`, so capture runs in a real window there — adding `--headless` to `--write-movie` aborts (`Parameter "t" is null`).

Capture deterministically with Godot's movie writer from a dedicated capture `SceneTree` script under `test/`, through `tools/capture.py` (a uv script — `uv run tools/capture.py …`):

```bash
uv run tools/capture.py record --script test/Presentation.cs --seconds 15   # → screenshots/capture/
```

`record` runs `dotnet build` and `--import`, records at `--fixed-fps 30` (under `xvfb-run` on Linux; `--window` for a visible window), then prints the renderer, any error lines from `godot.log`, and a review of the clip:

- `sheet.png` — 12 evenly spaced frames labeled `#frame time`. Look at this first.
- `motion.png` — a per-frame motion graph over each sample compared with 6 frames earlier, changed pixels in red. Shows what actually moves, which stills can't.
- `FROZEN` / `DARK` / `POP` lines — spans with no motion, near-black spans, and single-frame jumps. `POP #1` means the first frame differs from the rest: the first movie frame renders before `_Process`, so pre-position the camera and settle warm-up effects (fog, exposure) in the builder/`_Initialize`.
- `video.mp4` — the deliverable; `report.json` — the numbers.

Then pull what the sheet makes you doubt at full size — `frames <clip> --at 212,7.5s` — and compare before/after renders with `diff a.png b.png`. `review <clip>` re-runs the review on an existing clip; `export <clip> out.webm|.gif` converts.

- **The capture size is the window size** (`--size`, default 1920×1080). `--resolution` doesn't reach the movie writer; the tool sets `window_width_override` through a temporary `override.cfg`, leaving the base viewport and UI layout alone.
- **OGV is the default format.** Godot encodes on the main thread, one frame at a time: at 1080p PNG costs ~230 ms/frame on Godot 4.7 (4.8 writes movie PNGs with fast compression, ~4× faster) against ~20 ms for OGV, at no visible loss. Use `--format png` only when judging pixel-exact detail. Theora stores a repeated frame as an empty packet that decoders skip, so a frozen span vanishes from a plain `ffmpeg` frame dump — extract frames through the tool, which re-times to constant fps.

Drive capture-time input from the script, not live keys. The clip must show the behavior progressing across the whole window — no dead time, no single looped frame.
