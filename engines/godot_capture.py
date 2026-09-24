#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""Record a Godot game with the movie writer and turn the clip into things a model can look at.

  record   build + import + record a deterministic clip, then review it (the usual entry point)
  review   probe + motion analysis + contact sheet + motion sheet + mp4 for an existing clip
  sheet    contact sheet of evenly spaced frames, labeled with frame number and time
  motion   per-frame motion score; flags frozen spans, dark spans, and pops; motion sheet
  frames   pull exact frames out at full resolution
  export   convert a clip to mp4 / webm / gif
  diff     highlight what changed between two images

A clip is a video file (.ogv/.avi/.mp4/...) or a directory of PNG frames.
Needs ffmpeg/ffprobe on PATH; `record` also needs godot (and xvfb-run on headless Linux).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont, ImageOps

SOFTWARE_RENDERERS = ("llvmpipe", "lavapipe", "swiftshader", "softpipe")
MOVIE_EXT = {"ogv": "ogv", "avi": "avi", "png": "png"}


# ---------------------------------------------------------------- helpers

def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def need(tool: str):
    if not shutil.which(tool):
        die(f"`{tool}` not found on PATH")


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def run_timed(cmd, limit: int, **kw) -> subprocess.CompletedProcess:
    """Run with a wall-clock limit; on expiry kill the whole process group (xvfb-run + godot), return 124."""
    proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, **kw)
    try:
        out, err = proc.communicate(timeout=limit)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        return subprocess.CompletedProcess(cmd, 124, out, err)


def font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def label(img: Image.Image, text: str, size: int = 18) -> Image.Image:
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    f = font(size)
    x0, y0, x1, y1 = d.textbbox((6, 4), text, font=f)
    d.rectangle((x0 - 4, y0 - 3, x1 + 4, y1 + 3), fill=(0, 0, 0))
    d.text((6, 4), text, font=f, fill=(255, 235, 60))
    return img


class Clip:
    """A video file or a directory of PNG frames, addressed by frame index."""

    def __init__(self, path: str | Path, fps: float | None = None):
        self.path = Path(path)
        if not self.path.exists():
            die(f"{self.path} does not exist")
        self.is_dir = self.path.is_dir()
        if self.is_dir:
            self.files = sorted(glob.glob(str(self.path / "*.png")))
            if not self.files:
                die(f"no PNG frames in {self.path}")
            self.fps = fps or 30.0
            with Image.open(self.files[0]) as im:
                self.width, self.height = im.size
            self.frames = len(self.files)
            self.has_audio = False
        else:
            need("ffprobe")
            p = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(self.path)])
            if p.returncode:
                die(f"ffprobe failed on {self.path}: {p.stderr.strip()}")
            info = json.loads(p.stdout)
            streams = info.get("streams", [])
            v = next((s for s in streams if s.get("codec_type") == "video"), None)
            if not v:
                die(f"no video stream in {self.path}")
            num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").partition("/")
            self.fps = fps or (float(num) / float(den or 1) if float(den or 1) else 30.0)
            self.width, self.height = int(v["width"]), int(v["height"])
            # Count from duration, not packets: Theora stores a repeated frame as an empty packet that
            # decoders skip, so a frozen span would otherwise vanish from the frame count.
            duration = float(v.get("duration") or info.get("format", {}).get("duration") or 0)
            self.frames = round(duration * self.fps) if duration else int(v.get("nb_frames") or 0)
            self.has_audio = any(s.get("codec_type") == "audio" for s in streams)

    @property
    def seconds(self) -> float:
        return self.frames / self.fps if self.fps else 0.0

    def cfr(self) -> str:
        """Filter prefix giving one decoded frame per frame index (re-inserts held frames)."""
        return "" if self.is_dir else f"fps={self.fps},trim=end_frame={self.frames},"

    def ffmpeg_input(self) -> list[str]:
        if self.is_dir:
            return ["-framerate", str(self.fps), "-pattern_type", "glob", "-i", str(self.path / "*.png")]
        return ["-i", str(self.path)]

    def grab(self, indices: list[int]) -> dict[int, Image.Image]:
        """Return {index: RGB image} for the requested frame indices."""
        want = sorted({min(max(0, i), self.frames - 1) for i in indices})
        if self.is_dir:
            return {i: Image.open(self.files[i]).convert("RGB") for i in want}
        need("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            sel = "+".join(f"eq(n\\,{i})" for i in want)
            p = run(["ffmpeg", "-v", "error", "-y", *self.ffmpeg_input(), "-vf", f"{self.cfr()}select={sel}",
                     "-fps_mode", "passthrough", f"{tmp}/f%06d.png"])
            if p.returncode:
                die(f"ffmpeg frame extraction failed: {p.stderr.strip()}")
            got = sorted(glob.glob(f"{tmp}/f*.png"))
            return {i: Image.open(f).convert("RGB") for i, f in zip(want, got)}


def spaced(n_frames: int, count: int) -> list[int]:
    if n_frames <= count:
        return list(range(n_frames))
    return sorted({round(i * (n_frames - 1) / (count - 1)) for i in range(count)})


def tile(images: list[Image.Image], cols: int, gap: int = 4, bg=(24, 24, 24)) -> Image.Image:
    w, h = images[0].size
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap), bg)
    for k, im in enumerate(images):
        sheet.paste(im, ((k % cols) * (w + gap), (k // cols) * (h + gap)))
    return sheet


def thumb(img: Image.Image, width: int) -> Image.Image:
    return img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def stamp(clip: Clip, i: int) -> str:
    return f"#{i}  {i / clip.fps:.2f}s"


# ---------------------------------------------------------------- analysis

def change_mask(a: Image.Image, b: Image.Image, threshold: int) -> Image.Image:
    """L-mode mask: 255 where the frames differ by more than `threshold` (0-255 luma)."""
    d = ImageChops.difference(a, b).convert("L")
    return d.point(lambda v: 255 if v > threshold else 0)


def highlight(base: Image.Image, mask: Image.Image) -> Image.Image:
    """Dim, desaturated base with changed pixels painted red."""
    dim = ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.35)).enhance(0.6)
    red = Image.new("RGB", base.size, (255, 40, 40))
    return Image.composite(red, dim, mask)


def motion_scores(clip: Clip) -> tuple[list[float], list[float]]:
    """Per-frame (YDIF, YAVG): mean luma change from the previous frame, and mean luma. 0-255."""
    need("ffmpeg")
    # stats go to stdout: a file target is truncated whenever ffmpeg rebuilds the filter graph
    p = run(["ffmpeg", "-v", "error", *clip.ffmpeg_input(), "-vf",
             f"{clip.cfr()}signalstats,metadata=print:file='pipe\\:1'", "-f", "null", "-"])
    if p.returncode:
        die(f"ffmpeg signalstats failed: {p.stderr.strip()}")
    text = p.stdout
    ydif = [float(x) for x in re.findall(r"signalstats\.YDIF=([0-9.]+)", text)]
    yavg = [float(x) for x in re.findall(r"signalstats\.YAVG=([0-9.]+)", text)]
    return ydif, yavg


def spans(flags: list[bool], min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    return out


def analyze(clip: Clip, freeze_below: float, freeze_min_s: float, dark_below: float, pop_factor: float) -> dict:
    ydif, yavg = motion_scores(clip)
    moving = ydif[1:] or [0.0]  # frame 0 has no predecessor
    median = statistics.median(moving)
    fps = clip.fps
    freezes = spans([i > 0 and v < freeze_below for i, v in enumerate(ydif)], max(2, round(freeze_min_s * fps)))
    darks = spans([v < dark_below for v in yavg], max(1, round(0.25 * fps)))
    pop_at = max(median * pop_factor, median + 4.0)
    pops = [i for i, v in enumerate(ydif) if i > 0 and v > pop_at]
    return {
        "frames": len(ydif),
        "fps": fps,
        "motion": {"median": round(median, 3), "mean": round(statistics.fmean(moving), 3),
                   "max": round(max(moving), 3), "max_frame": 1 + moving.index(max(moving))},
        "frozen": [{"from": a, "to": b, "seconds": round((b - a + 1) / fps, 2)} for a, b in freezes],
        "dark": [{"from": a, "to": b, "seconds": round((b - a + 1) / fps, 2)} for a, b in darks],
        "pops": [{"frame": i, "score": round(ydif[i], 2)} for i in pops],
        "ydif": [round(v, 3) for v in ydif],
        "yavg": [round(v, 2) for v in yavg],
    }


def motion_graph(report: dict, width: int, marks: list[int], height: int = 150) -> Image.Image:
    ydif, n = report["ydif"], report["frames"]
    img = Image.new("RGB", (width, height), (18, 18, 22))
    d = ImageDraw.Draw(img)
    pad_l, pad_r, pad_t, pad_b = 8, 8, 30, 18
    gw, gh = width - pad_l - pad_r, height - pad_t - pad_b
    top = max(max(ydif[1:] or [1.0]), 1e-6)
    x = lambda i: pad_l + gw * i / max(1, n - 1)
    y = lambda v: pad_t + gh * (1 - min(v, top) / top)
    for s in report["frozen"]:
        d.rectangle((x(s["from"]), pad_t, x(s["to"]), pad_t + gh), fill=(40, 70, 140))
    for s in report["dark"]:
        d.rectangle((x(s["from"]), pad_t + gh - 6, x(s["to"]), pad_t + gh), fill=(120, 120, 120))
    for m in marks:
        d.line((x(m), pad_t, x(m), pad_t + gh), fill=(70, 70, 70))
    pts = [(x(i), y(v)) for i, v in enumerate(ydif) if i > 0]
    if len(pts) > 1:
        d.line(pts, fill=(90, 220, 120), width=2)
    for p in report["pops"]:
        d.ellipse((x(p["frame"]) - 5, y(p["score"]) - 5, x(p["frame"]) + 5, y(p["score"]) + 5), outline=(255, 60, 60), width=2)
    m = report["motion"]
    d.text((pad_l, 6), f"motion (luma change / frame)  median {m['median']}  max {m['max']} @#{m['max_frame']}   "
           f"blue = frozen  red = pop  grey = dark", font=font(15), fill=(220, 220, 220))
    d.text((pad_l, height - 16), "#0", font=font(12), fill=(160, 160, 160))
    d.text((width - pad_r - 40, height - 16), f"#{n - 1}", font=font(12), fill=(160, 160, 160))
    return img


# ---------------------------------------------------------------- commands

def make_sheet(clip: Clip, out: Path, count: int, cols: int, width: int) -> Path:
    idx = spaced(clip.frames, count)
    frames = clip.grab(idx)
    tiles = [label(thumb(frames[i], width), stamp(clip, i)) for i in idx]
    tile(tiles, min(cols, len(tiles))).save(out)
    return out


def make_motion_sheet(clip: Clip, report: dict, out: Path, count: int, cols: int, width: int, gap: int, threshold: int) -> Path:
    idx = [i for i in spaced(clip.frames, count) if i >= gap] or [clip.frames - 1]
    # also show each pop against the frame before it, where the model most needs to look
    pop_idx = [p["frame"] for p in report["pops"]][:cols]
    pairs = [(i - gap, i) for i in idx] + [(i - 1, i) for i in pop_idx]
    frames = clip.grab([i for pair in pairs for i in pair])
    tiles = []
    for a, b in pairs:
        t = highlight(frames[b], change_mask(frames[a], frames[b], threshold))
        tag = "POP " if (b - a == 1 and b in pop_idx) else ""
        tiles.append(label(thumb(t, width), f"{tag}#{b} vs #{a}"))
    grid = tile(tiles, min(cols, len(tiles)))
    graph = motion_graph(report, grid.width, idx)
    sheet = Image.new("RGB", (grid.width, graph.height + 4 + grid.height), (24, 24, 24))
    sheet.paste(graph, (0, 0))
    sheet.paste(grid, (0, graph.height + 4))
    sheet.save(out)
    return out


def export(clip: Clip, out: Path, fmt: str, width: int | None) -> Path:
    need("ffmpeg")
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if width:
        even = f"scale={width}:-2"
    if fmt == "mp4":
        args = ["-vf", even, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart"]
        args += ["-c:a", "aac", "-b:a", "128k"] if clip.has_audio else ["-an"]
    elif fmt == "webm":
        args = ["-vf", even, "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1"]
        args += ["-c:a", "libopus"] if clip.has_audio else ["-an"]
    elif fmt == "gif":
        w = width or min(640, clip.width)
        args = ["-vf", f"fps=15,scale={w}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
                       f"[b][p]paletteuse=dither=bayer:bayer_scale=4", "-an"]
    else:
        die(f"unknown export format {fmt}")
    p = run(["ffmpeg", "-v", "error", "-y", *clip.ffmpeg_input(), *args, str(out)])
    if p.returncode:
        die(f"ffmpeg export failed: {p.stderr.strip()}")
    return out


def review(clip: Clip, outdir: Path, a) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    report = analyze(clip, a.freeze_below, a.freeze_min, a.dark_below, a.pop_factor)
    sheet = make_sheet(clip, outdir / "sheet.png", a.count, a.cols, a.width)
    msheet = make_motion_sheet(clip, report, outdir / "motion.png", a.count, a.cols, a.width, a.gap, a.threshold)
    files = {"sheet": str(sheet), "motion": str(msheet)}
    if not a.no_mp4:
        files["mp4"] = str(export(clip, outdir / "video.mp4", "mp4", None))
    summary = {
        "clip": str(clip.path), "frames": clip.frames, "fps": clip.fps, "seconds": round(clip.seconds, 2),
        "size": f"{clip.width}x{clip.height}", "audio": clip.has_audio, "files": files,
        **{k: report[k] for k in ("motion", "frozen", "dark", "pops")},
    }
    (outdir / "report.json").write_text(json.dumps({**summary, "ydif": report["ydif"], "yavg": report["yavg"]}, indent=1))
    summary["files"]["report"] = str(outdir / "report.json")
    return summary


def print_review(s: dict):
    print(f"clip   {s['clip']}  {s['size']}  {s['frames']} frames @ {s['fps']:g} fps = {s['seconds']}s"
          f"{'  +audio' if s['audio'] else ''}")
    m = s["motion"]
    print(f"motion median {m['median']}  mean {m['mean']}  max {m['max']} at #{m['max_frame']}")
    for f in s["frozen"]:
        print(f"FROZEN #{f['from']}-#{f['to']} ({f['seconds']}s)")
    for f in s["dark"]:
        print(f"DARK   #{f['from']}-#{f['to']} ({f['seconds']}s)")
    for p in s["pops"]:
        hint = "  (first frame differs from the rest: pre-position / warm up before capture)" if p["frame"] == 1 else ""
        print(f"POP    #{p['frame']} score {p['score']}{hint}")
    if not (s["frozen"] or s["dark"] or s["pops"]):
        print("no frozen, dark, or popping spans")
    for k, v in s["files"].items():
        print(f"{k:<6} {v}")


# ---------------------------------------------------------------- record

def parse_size(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)", s)
    if not m:
        die(f"--size must look like 1920x1080, got {s!r}")
    return int(m[1]), int(m[2])


def override_block(a, w: int, h: int) -> str:
    lines = ["", "; --- capture.py (temporary) ---", "[display]",
             f"window/size/window_width_override={w}", f"window/size/window_height_override={h}", "window/size/mode=0",
             "[editor]", f"movie_writer/video_quality={a.quality}"]
    if a.ogv_speed is not None:
        lines.append(f"movie_writer/ogv/encoding_speed={a.ogv_speed}")
    if a.keyframe_interval is not None:
        lines.append(f"movie_writer/ogv/keyframe_interval={a.keyframe_interval}")
    return "\n".join(lines) + "\n"


def cmd_record(a):
    need("godot")
    project = Path(a.project).resolve()
    if not (project / "project.godot").exists():
        die(f"no project.godot in {project}")
    outdir = Path(a.out) if Path(a.out).is_absolute() else project / a.out
    outdir.mkdir(parents=True, exist_ok=True)
    w, h = parse_size(a.size)
    frames = max(1, round(a.seconds * a.fps))
    godot = a.godot or "godot"
    tlimit = a.timeout or max(600, frames * 3)

    use_xvfb = sys.platform.startswith("linux") and not a.window
    if a.window and sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        die("--window needs a display (DISPLAY / WAYLAND_DISPLAY)")
    if use_xvfb:
        need("xvfb-run")
    wrap = ["xvfb-run", "-a", "-s", f"-screen 0 {max(w, 1920)}x{max(h, 1080)}x24"] if use_xvfb else []

    steps = {}
    if not a.no_build and list(project.glob("*.csproj")):
        need("dotnet")
        t = time.time()
        p = run(["dotnet", "build", "-nologo", "-v", "q"], cwd=project)
        steps["build_s"] = round(time.time() - t, 1)
        if p.returncode:
            print(p.stdout[-4000:], p.stderr[-2000:], sep="\n")
            die("dotnet build failed")
    if not a.no_import:
        t = time.time()
        p = run_timed([godot, "--headless", "--path", str(project), "--import"], 600)
        steps["import_s"] = round(time.time() - t, 1)
        if p.returncode == 124:
            die("godot --import timed out (600s)")

    # movie target; clear what a previous run left so frames never mix
    if a.format == "png":
        target = outdir / "frames" / "frame.png"
        shutil.rmtree(target.parent, ignore_errors=True)
        target.parent.mkdir(parents=True)
        # keep frame PNGs out of Godot's importer
        (outdir / ".gdignore").touch()
    else:
        target = outdir / f"movie.{MOVIE_EXT[a.format]}"
        target.unlink(missing_ok=True)
        (outdir / ".gdignore").touch()

    cfg = project / "override.cfg"
    original = cfg.read_text() if cfg.exists() else None
    cfg.write_text((original or "") + override_block(a, w, h))
    cmd = [*wrap, godot, "--path", str(project), "--write-movie", str(target),
           "--fixed-fps", str(a.fps), "--quit-after", str(frames)]
    if a.driver:
        cmd += ["--rendering-driver", a.driver]
    if a.script:
        cmd += ["--script", a.script]
    if a.scene:
        cmd.append(a.scene)
    cmd += a.godot_args
    print("recording:", " ".join(cmd), file=sys.stderr)
    t = time.time()
    try:
        p = run_timed(cmd, tlimit, cwd=project)
    finally:
        if original is None:
            cfg.unlink(missing_ok=True)
        else:
            cfg.write_text(original)
    steps["record_s"] = round(time.time() - t, 1)
    log = p.stdout + p.stderr
    (outdir / "godot.log").write_text(log)

    device = next((m[1] for m in re.finditer(r"(?:Vulkan|OpenGL API|Metal|D3D12)[^\n]*? - (?:Forward\+|Mobile|Compatibility) - Using Device[^:]*: (.+)", log)), None)
    errors = [ln for ln in log.splitlines() if ln.startswith(("ERROR:", "SCRIPT ERROR:", "USER ERROR:"))
              and "RID" not in ln and "leaked" not in ln]
    timing = {k: m[1] for k, rx in {"gpu_ms_per_frame": r"GPU render time: [0-9.]+ seconds \(average: ([0-9.]+) ms",
                                     "encode_ms_per_frame": r"Encoding time: [0-9.]+ seconds \(average: ([0-9.]+) ms"}.items()
              if (m := re.search(rx, log))}
    print(f"renderer {device or 'unknown (see godot.log)'}")
    if device and any(s in device.lower() for s in SOFTWARE_RENDERERS):
        print("WARNING software renderer: motion and effects may be wrong or slow; treat the clip as stills")
    print(f"timing   {json.dumps({**steps, **timing})}")
    if errors:
        print(f"{len(errors)} error line(s) in godot.log, first: {errors[0][:300]}")
    if p.returncode == 124:
        die(f"recording timed out after {tlimit}s (godot.log has the output)")
    clip_path = target.parent if a.format == "png" else target
    if a.format == "png" and not list(target.parent.glob("*.png")) or a.format != "png" and not target.exists():
        die(f"godot exited {p.returncode} without writing {clip_path} (see {outdir / 'godot.log'})")
    print_review(review(Clip(clip_path, a.fps), outdir, a))


def cmd_review(a):
    print_review(review(Clip(a.clip, a.fps), Path(a.out or Path(a.clip).parent), a))


def cmd_sheet(a):
    clip = Clip(a.clip, a.fps)
    print(make_sheet(clip, Path(a.out), a.count, a.cols, a.width))


def cmd_motion(a):
    clip = Clip(a.clip, a.fps)
    report = analyze(clip, a.freeze_below, a.freeze_min, a.dark_below, a.pop_factor)
    out = make_motion_sheet(clip, report, Path(a.out), a.count, a.cols, a.width, a.gap, a.threshold)
    print_review({"clip": str(clip.path), "frames": clip.frames, "fps": clip.fps, "seconds": round(clip.seconds, 2),
                  "size": f"{clip.width}x{clip.height}", "audio": clip.has_audio, "files": {"motion": str(out)},
                  **{k: report[k] for k in ("motion", "frozen", "dark", "pops")}})


def cmd_frames(a):
    clip = Clip(a.clip, a.fps)
    if a.at:
        idx = []
        for tok in a.at.split(","):
            tok = tok.strip()
            idx.append(round(float(tok[:-1]) * clip.fps) if tok.endswith("s") else int(tok))
    else:
        idx = spaced(clip.frames, a.count)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, im in clip.grab(idx).items():
        p = out / f"frame{i:05d}.png"
        (thumb(im, a.width) if a.width else im).save(p)
        print(p)


def cmd_export(a):
    clip = Clip(a.clip, a.fps)
    print(export(clip, Path(a.out), Path(a.out).suffix.lstrip(".").lower(), a.width))


def cmd_diff(a):
    ia, ib = Image.open(a.a).convert("RGB"), Image.open(a.b).convert("RGB")
    if ia.size != ib.size:
        ib = ib.resize(ia.size, Image.LANCZOS)
    mask = change_mask(ia, ib, a.threshold)
    changed = sum(mask.histogram()[255:]) / (mask.width * mask.height)
    diff = ImageChops.difference(ia, ib).convert("L")
    stat = diff.getextrema()[1]
    rms = math.sqrt(sum(v * v * c for v, c in enumerate(diff.histogram())) / (diff.width * diff.height))
    w = a.width or min(ia.width, 960)
    panels = [label(thumb(ia, w), "A"), label(thumb(ib, w), "B"),
              label(thumb(highlight(ib, mask), w), f"changed {changed:.1%}"),
              label(thumb(ImageOps.autocontrast(diff), w), "|A-B| (auto-contrast)")]
    tile(panels, 2).save(a.out)
    print(f"changed {changed:.2%} of pixels (> {a.threshold}/255)  rms {rms:.2f}  max {stat}  -> {a.out}")


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def view_opts(p, count=12):
        p.add_argument("--count", type=int, default=count, help="frames sampled across the clip")
        p.add_argument("--cols", type=int, default=4)
        p.add_argument("--width", type=int, default=480, help="tile width in px")

    def motion_opts(p):
        p.add_argument("--gap", type=int, default=6, help="motion sheet compares frame n with n-gap")
        p.add_argument("--threshold", type=int, default=12, help="luma change (0-255) that counts as changed")
        p.add_argument("--freeze-below", type=float, default=0.02, help="YDIF under this counts as no motion (a frozen capture scores 0)")
        p.add_argument("--freeze-min", type=float, default=0.5, help="seconds of no motion to report as frozen")
        p.add_argument("--dark-below", type=float, default=16, help="mean luma under this counts as dark")
        p.add_argument("--pop-factor", type=float, default=8, help="YDIF this many x the median is a pop")

    def clip_arg(p):
        p.add_argument("clip", help="video file or directory of PNG frames")
        p.add_argument("--fps", type=float, help="frame rate for a PNG directory (default 30)")

    p = sub.add_parser("record", help="build, import, record, review")
    p.add_argument("--project", default=".")
    p.add_argument("--out", default="screenshots/capture", help="output dir (relative to the project)")
    p.add_argument("--script", help="SceneTree capture script, e.g. test/Presentation.cs")
    p.add_argument("--scene", help="scene to run instead of the main scene, e.g. res://scenes/Level.tscn")
    p.add_argument("--seconds", type=float, default=15)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--size", default="1920x1080", help="capture resolution (window size; base viewport unchanged)")
    p.add_argument("--format", choices=["ogv", "png", "avi"], default="ogv")
    p.add_argument("--quality", type=float, default=0.75, help="ogv/avi quality 0-1")
    p.add_argument("--ogv-speed", type=int, help="Theora encoding speed (movie_writer/ogv/encoding_speed)")
    p.add_argument("--keyframe-interval", type=int, help="Theora keyframe interval")
    p.add_argument("--driver", help="--rendering-driver for godot (vulkan, opengl3, ...)")
    p.add_argument("--window", action="store_true", help="record in a visible window instead of xvfb")
    p.add_argument("--timeout", type=int, help="seconds before the recording is killed")
    p.add_argument("--godot", help="godot binary (default: godot on PATH)")
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--no-import", action="store_true")
    p.add_argument("--no-mp4", action="store_true")
    p.add_argument("godot_args", nargs=argparse.REMAINDER, help="after --: extra godot arguments")
    view_opts(p); motion_opts(p)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("review", help="analyze an existing clip: report, sheets, mp4")
    clip_arg(p); p.add_argument("--out", help="output dir (default: next to the clip)")
    p.add_argument("--no-mp4", action="store_true")
    view_opts(p); motion_opts(p)
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("sheet", help="contact sheet of evenly spaced frames")
    clip_arg(p); p.add_argument("-o", "--out", default="sheet.png")
    view_opts(p)
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("motion", help="motion analysis + motion sheet")
    clip_arg(p); p.add_argument("-o", "--out", default="motion.png")
    view_opts(p); motion_opts(p)
    p.set_defaults(fn=cmd_motion)

    p = sub.add_parser("frames", help="extract exact frames")
    clip_arg(p); p.add_argument("-o", "--out", default="frames")
    p.add_argument("--at", help="comma list of frame numbers or seconds (e.g. 0,150,7.5s)")
    p.add_argument("--count", type=int, default=6, help="evenly spaced frames when --at is omitted")
    p.add_argument("--width", type=int, help="resize to this width (default: full size)")
    p.set_defaults(fn=cmd_frames)

    p = sub.add_parser("export", help="convert to mp4 / webm / gif (by output extension)")
    clip_arg(p); p.add_argument("out", help="output file: .mp4, .webm or .gif")
    p.add_argument("--width", type=int, help="scale to this width")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("diff", help="highlight what changed between two images")
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("-o", "--out", default="diff.png")
    p.add_argument("--threshold", type=int, default=12)
    p.add_argument("--width", type=int)
    p.set_defaults(fn=cmd_diff)

    a = ap.parse_args()
    if getattr(a, "godot_args", None) and a.godot_args[0] == "--":
        a.godot_args = a.godot_args[1:]
    a.fn(a)


if __name__ == "__main__":
    main()
