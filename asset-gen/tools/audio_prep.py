#!/usr/bin/env python3
"""Prepare a generated audio file for a game engine, and check it.

    audio_prep.py raw.mp3 -o assets/audio/sfx/door.ogg            # one-shot: trim leading silence
    audio_prep.py raw.mp3 -o assets/audio/sfx/hum.ogg --loop      # loop: keep every sample, check steadiness
    audio_prep.py raw.mp3 -o assets/audio/sfx/hum.ogg --loop --flatten   # + even out swells, seam preserved
    audio_prep.py raw.mp3 -o assets/audio/music/theme.ogg --lufs -18

Output format follows the extension (.ogg Vorbis, .wav 16-bit, .mp3). Prints one JSON line:
  seconds, peak_db, lufs, lead_trimmed_ms, tail_silence_ms, and for --loop: level_range_db (spread of
  0.5 s loudness across the clip) and seam_step (sample jump at the wrap vs the clip's p99 step).
`warnings` lists what to listen for or regenerate. Needs ffmpeg and numpy.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 44100
SILENCE_DB = -45.0          # below this a 10 ms window counts as silent
LOOP_RANGE_WARN_DB = 1.5    # a loop whose 0.5 s loudness spreads wider than this audibly swells each pass
TAIL_WARN_MS = 400
CODECS = {".ogg": ["-c:a", "libvorbis", "-q:a", "6"], ".wav": ["-c:a", "pcm_s16le"], ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"]}


def ffmpeg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)


def load(path: Path, mono: bool = True) -> np.ndarray:
    """Samples at SR; mono for envelope analysis, or interleaved channels as stored (for true peaks —
    a stereo-to-mono downmix reads ~3 dB hot)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", *(["-ac", "1"] if mono else []),
                          "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def window_db(x: np.ndarray, size: int) -> np.ndarray:
    n = len(x) // size
    return np.array([db(float(np.sqrt(np.mean(x[i * size:(i + 1) * size] ** 2)))) for i in range(n)])


def lufs(path: Path) -> float | None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


def flatten(x: np.ndarray, out: Path, window_s: float = 0.4) -> Path:
    """Divide out the loudness envelope. The envelope is smoothed circularly, so the gain at the last sample
    meets the gain at the first and the loop's wrap stays continuous."""
    n = int(SR * window_s)
    power = np.convolve(np.concatenate([x[-n:], x, x[:n]]) ** 2, np.ones(n) / n, mode="same")[n:-n]
    env = np.sqrt(np.maximum(power, 1e-12))
    target = float(np.sqrt(np.mean(x ** 2)))
    y = np.clip(x * (target / np.maximum(env, target * 0.1)), -1, 1).astype(np.float32)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-c:a", "pcm_s16le", str(out)], input=y.tobytes(), capture_output=True)
    if p.returncode:
        sys.exit(json.dumps({"ok": False, "error": p.stderr.decode().strip()}))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--loop", action="store_true", help="seamless loop: no trimming, check level steadiness")
    ap.add_argument("--flatten", action="store_true",
                    help="loops only: even out loudness swells with a slow gain curve computed around the wrap")
    ap.add_argument("--no-trim", action="store_true", help="keep leading silence on a one-shot")
    ap.add_argument("--lufs", type=float, help="normalize integrated loudness to this target (e.g. -18)")
    a = ap.parse_args()

    src, out = Path(a.input), Path(a.output)
    if out.suffix.lower() not in CODECS:
        sys.exit(json.dumps({"ok": False, "error": f"output must end in {', '.join(CODECS)}"}))
    x = load(src)
    if not len(x):
        sys.exit(json.dumps({"ok": False, "error": f"could not decode {src}"}))

    # Leading silence: generators often open music with seconds of near-silence, and a one-shot that starts
    # late reads as input lag. Loops keep every sample so the wrap stays where it was generated.
    env = window_db(x, SR // 100)
    loud = np.nonzero(env > SILENCE_DB)[0]
    lead_ms = 0 if a.loop or a.no_trim or not len(loud) else max(0, int(loud[0]) * 10 - 10)
    tail_ms = 0 if not len(loud) else (len(env) - 1 - int(loud[-1])) * 10

    if a.flatten and not a.loop:
        sys.exit(json.dumps({"ok": False, "error": "--flatten is for --loop clips"}))

    filters = []
    if lead_ms:
        filters.append(f"atrim=start={lead_ms / 1000},asetpts=PTS-STARTPTS")
    if a.lufs is not None:
        filters.append(f"loudnorm=I={a.lufs}:TP=-1.5:LRA=11")
    if a.lufs is not None and not a.loop:
        # Raising loudness can push peaks past full scale; cap at -2 dBFS. Not on loops: the limiter's
        # lookahead shifts the signal and breaks the seam.
        filters.append("alimiter=limit=0.79:level=0:attack=2:release=60")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if a.flatten:
            src = flatten(x, Path(tmp) / "flat.wav")
        stage = Path(tmp) / f"stage{out.suffix}"
        args = ["-i", str(src)] + (["-af", ",".join(filters), "-ar", str(SR)] if filters else []) + CODECS[out.suffix.lower()] + [str(stage)]
        p = ffmpeg(*args)
        if p.returncode:
            sys.exit(json.dumps({"ok": False, "error": p.stderr.strip()}))
        shutil.move(stage, out)   # tmp may be on another filesystem

    y = load(out)
    report = {"ok": True, "path": str(out), "seconds": round(len(y) / SR, 2), "peak_db": round(db(float(np.max(np.abs(load(out, mono=False))))), 1),
              "lufs": lufs(out), "lead_trimmed_ms": lead_ms, "tail_silence_ms": tail_ms}
    warnings = []
    if report["peak_db"] > -0.3:
        warnings.append("peak at full scale: likely clipping, lower the level or pass --lufs")
    if a.loop:
        half = window_db(y, SR // 2)
        rng = float(half.max() - half.min()) if len(half) else 0.0
        step = float(abs(y[0] - y[-1]))
        p99 = float(np.percentile(np.abs(np.diff(y)), 99))
        report.update(level_range_db=round(rng, 1), seam_step=round(step, 4), seam_step_p99=round(p99, 4))
        if rng > LOOP_RANGE_WARN_DB:
            fix = "generate another take" if a.flatten else "try --flatten, or another take"
            warnings.append(f"loudness varies {rng:.1f} dB across the loop: it will swell and drop every pass — {fix}")
        if step > 2 * p99:
            warnings.append("sample jump at the wrap: the loop will click")
        if tail_ms > 50:
            warnings.append("silence before the wrap: the loop will gap")
    elif tail_ms > TAIL_WARN_MS:
        warnings.append(f"{tail_ms} ms of silence at the end (fine unless the game waits for the sound to finish)")
    report["warnings"] = warnings
    print(json.dumps(report))


if __name__ == "__main__":
    main()
