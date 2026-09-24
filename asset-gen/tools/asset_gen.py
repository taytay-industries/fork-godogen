#!/usr/bin/env python3
"""Asset Generator CLI - creates images and videos (Gemini / xAI Grok) and audio (ElevenLabs).

Subcommands:
  image         Generate a PNG from a prompt (Gemini 5-15¢ or Grok 6-8¢)
  video         Generate MP4 video from prompt + reference image (8-14¢/sec, Grok)
  speech        Text to speech in a chosen voice (ElevenLabs)
  sfx           Sound effect from a description, optionally a seamless loop (ElevenLabs)
  music         Music track from a description (ElevenLabs)
  voice-change  Re-voice a recorded performance in another voice (ElevenLabs)
  voices        Search ElevenLabs voices
  audio-status  Check the ElevenLabs key and remaining credits

3D models come from the `tripo` CLI (see SKILL.md), not from here.

Output: JSON to stdout. Progress to stderr.
"""

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import xai_sdk
from google import genai
from google.genai import types
from PIL import Image

TOOLS_DIR = Path(__file__).parent

VIDEO_MODEL = "grok-imagine-video-1.5"
VIDEO_COSTS_PER_SEC = {"480p": 8, "720p": 14}  # cents, +1¢ for the start frame; xAI's billed cost_usd is reported when present


def result_json(ok: bool, path: str | None = None, cost_cents: int = 0, error: str | None = None):
    d = {"ok": ok, "cost_cents": cost_cents}
    if path:
        d["path"] = path
    if error:
        d["error"] = error
    print(json.dumps(d))


# --- Image backends ---

GEMINI_MODEL = "gemini-3.1-flash-image"
GEMINI_SIZES = ["512", "1K", "2K", "4K"]
GEMINI_COSTS = {"512": 5, "1K": 7, "2K": 10, "4K": 15}
GEMINI_ASPECT_RATIOS = [
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
]

GROK_MODEL = "grok-imagine-image-2.0"
GROK_QUALITY = "medium"
GROK_SIZES = ["1K", "2K"]
GROK_COSTS = {"1K": 6, "2K": 8}  # medium quality; xAI's billed cost_usd is reported when present
GROK_ASPECT_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20", "auto",
]

ALL_SIZES = ["512", "1K", "2K", "4K"]
ALL_ASPECT_RATIOS = sorted(set(GEMINI_ASPECT_RATIOS + GROK_ASPECT_RATIOS))


def _mime_for_image(path: Path) -> str:
    """Detect image MIME type from file extension."""
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")


def _image_data_uri(image_path: Path) -> str:
    """Load image and return as base64 data URI."""
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    mime = _mime_for_image(image_path)
    return f"data:{mime};base64,{b64}"


def _billed_cents(resp, estimate: int) -> int:
    """Cost xAI reports for the request, else the price-table estimate."""
    usd = resp.cost_usd
    return round(usd * 100) if usd else estimate


def _default_backend() -> str | None:
    """Gemini when its key is set (faster, same quality), else Grok."""
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("XAI_API_KEY"):
        return "grok"
    return None


def _generate_gemini(args, output: Path, cost: int):
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            image_size=args.size,
            aspect_ratio=args.aspect_ratio,
        ),
    )

    contents = []
    if args.image:
        ref_path = Path(args.image)
        if not ref_path.exists():
            result_json(False, error=f"Reference image not found: {ref_path}")
            sys.exit(1)
        contents.append(types.Part.from_bytes(data=ref_path.read_bytes(), mime_type=_mime_for_image(ref_path)))
    contents.append(args.prompt)

    client = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )

    if response.parts is None:
        reason = "unknown"
        if response.candidates and response.candidates[0].finish_reason:
            reason = response.candidates[0].finish_reason
        result_json(False, error=f"Generation blocked (reason: {reason})")
        sys.exit(1)

    for part in response.parts:
        if part.inline_data is not None:
            # Re-encode as real PNG (Gemini may return JPEG data)
            img = Image.open(io.BytesIO(part.inline_data.data))
            img.save(output, format="PNG")
            print(f"Saved: {output}", file=sys.stderr)
            result_json(True, path=str(output), cost_cents=cost)
            return

    result_json(False, error="No image returned")
    sys.exit(1)


def _generate_grok(args, output: Path, cost: int):
    image_url = None
    if args.image:
        ref_path = Path(args.image)
        if not ref_path.exists():
            result_json(False, error=f"Reference image not found: {ref_path}")
            sys.exit(1)
        image_url = _image_data_uri(ref_path)

    try:
        client = xai_sdk.Client()
        resp = client.image.sample(
            prompt=args.prompt,
            model=GROK_MODEL,
            image_url=image_url,
            aspect_ratio=args.aspect_ratio,
            resolution=args.size.lower(),
            quality=GROK_QUALITY,
        )
        # xAI returns JPEG; convert to real PNG
        img = Image.open(io.BytesIO(resp.image))
        img.save(output, format="PNG")
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    result_json(True, path=str(output), cost_cents=_billed_cents(resp, cost))


def cmd_image(args):
    backend = args.model or _default_backend()
    size = args.size

    if backend is None:
        result_json(False, error="No image API key: set GEMINI_API_KEY (or GOOGLE_API_KEY) or XAI_API_KEY")
        sys.exit(1)

    if backend == "gemini":
        if size not in GEMINI_SIZES:
            result_json(False, error=f"Gemini does not support size {size}. Use: {', '.join(GEMINI_SIZES)}")
            sys.exit(1)
        cost = GEMINI_COSTS[size]
    else:
        if size not in GROK_SIZES:
            result_json(False, error=f"Grok does not support size {size}. Use: {', '.join(GROK_SIZES)}")
            sys.exit(1)
        cost = GROK_COSTS[size]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    label = f"{backend} {size} {args.aspect_ratio}"
    if args.image:
        label += " (image-to-image)"
    print(f"Generating image ({label})...", file=sys.stderr)

    if backend == "gemini":
        _generate_gemini(args, output, cost)
    else:
        _generate_grok(args, output, cost)


def cmd_video(args):
    cost = args.duration * VIDEO_COSTS_PER_SEC[args.resolution] + 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    image_path = Path(args.image)
    if not image_path.exists():
        result_json(False, error=f"Reference image not found: {image_path}")
        sys.exit(1)

    print(f"Generating {args.duration}s video ({args.resolution})...", file=sys.stderr)
    image_url = _image_data_uri(image_path)

    try:
        client = xai_sdk.Client()
        resp = client.video.generate(
            prompt=args.prompt,
            model=VIDEO_MODEL,
            image_url=image_url,
            duration=args.duration,
            aspect_ratio="1:1",
            resolution=args.resolution,
            generate_audio=False,
        )
        # Download MP4
        print("  Downloading video...", file=sys.stderr)
        dl = requests.get(resp.url, timeout=120)
        dl.raise_for_status()
        output.write_bytes(dl.content)
    except Exception as e:
        result_json(False, error=str(e))
        sys.exit(1)

    print(f"Saved: {output}", file=sys.stderr)
    result_json(True, path=str(output), cost_cents=_billed_cents(resp, cost))


# --- Audio (ElevenLabs) ---
# Every command reports `credits` — the `character-cost` ElevenLabs returns with the audio, which is what it
# bills. (The account's usage counter lags by minutes, so a before/after difference reads 0.)

TTS_MODEL = "eleven_v3"
SFX_MODEL = "eleven_text_to_sound_v2"
MUSIC_MODEL = "music_v2"
STS_MODEL = "eleven_multilingual_sts_v2"
AUDIO_FORMATS = {".mp3", ".ogg", ".wav"}   # what Godot imports; the API returns MP3, converted by ffmpeg


def audio_json(ok: bool, **fields):
    print(json.dumps({"ok": ok, **{k: v for k, v in fields.items() if v is not None}}))


def _audio_fail(error: str):
    audio_json(False, error=error)
    sys.exit(1)


def _eleven():
    if not os.environ.get("ELEVENLABS_API_KEY"):
        _audio_fail("ELEVENLABS_API_KEY is not set")
    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        _audio_fail("elevenlabs package missing: pip install elevenlabs")
    return ElevenLabs()


def _audio_seconds(path: Path) -> float | None:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return round(float(p.stdout.strip()), 2)
    except ValueError:
        return None


def _save_audio(chunks, output: Path) -> None:
    """Write the API's MP3 stream to `output`, converting to OGG Vorbis or WAV by extension."""
    output.parent.mkdir(parents=True, exist_ok=True)
    ext = output.suffix.lower()
    if ext not in AUDIO_FORMATS:
        _audio_fail(f"output must end in {', '.join(sorted(AUDIO_FORMATS))}")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        for chunk in chunks:
            f.write(chunk)
        tmp = Path(f.name)
    if ext == ".mp3":
        shutil.move(tmp, output)
        return
    codec = ["-c:a", "libvorbis", "-q:a", "6"] if ext == ".ogg" else ["-c:a", "pcm_s16le"]
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), *codec, str(output)], capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if p.returncode:
        _audio_fail(f"ffmpeg conversion failed: {p.stderr.strip()}")


def _run_audio(label: str, output: Path, generate, **extra):
    """Call `generate(client)` → a raw audio response, save the audio, and report path, length and credits."""
    client = _eleven()
    print(f"Generating {label}...", file=sys.stderr)
    try:
        with generate(client) as resp:
            cost = resp.headers.get("character-cost")
            _save_audio(resp.data, output)
    except SystemExit:
        raise
    except Exception as e:
        _audio_fail(str(getattr(e, "body", None) or e))
    credits = int(cost) if cost and cost.isdigit() else None
    print(f"Saved: {output}", file=sys.stderr)
    audio_json(True, path=str(output), seconds=_audio_seconds(output), credits=credits, **extra)


def _resolve_voice(client, voice: str) -> str:
    """A voice_id passes through; otherwise the best name match among the account's voices."""
    try:
        found = client.voices.search(search=voice, page_size=10).voices
    except Exception as e:
        _audio_fail(f"voice lookup failed: {e}")
    for v in found:
        if voice in (v.voice_id, v.name) or v.name.lower().startswith(voice.lower()):
            return v.voice_id
    if len(voice) >= 20 and voice.isalnum():
        return voice   # looks like an id the search didn't return (e.g. a library voice)
    _audio_fail(f"no voice matching {voice!r}; list them with: asset_gen.py voices --search <text>")


def _voice_settings(args):
    fields = {k: getattr(args, k) for k in ("stability", "similarity", "style", "speed") if getattr(args, k) is not None}
    if not fields:
        return None
    from elevenlabs import VoiceSettings
    if "similarity" in fields:
        fields["similarity_boost"] = fields.pop("similarity")
    return VoiceSettings(**fields)


def cmd_speech(args):
    output = Path(args.output)
    text = Path(args.text_file).read_text().strip() if args.text_file else args.text
    if not text:
        _audio_fail("pass --text or --text-file")
    client = _eleven()
    voice_id = _resolve_voice(client, args.voice)
    _run_audio(f"speech ({len(text)} chars)", output, lambda c: c.text_to_speech.with_raw_response.convert(
        voice_id=voice_id, text=text, model_id=args.model, voice_settings=_voice_settings(args),
        seed=args.seed, previous_text=args.previous_text, next_text=args.next_text,
        output_format="mp3_44100_128"), voice_id=voice_id)


def cmd_sfx(args):
    _run_audio("sound effect", Path(args.output), lambda c: c.text_to_sound_effects.with_raw_response.convert(
        text=args.prompt, duration_seconds=args.duration, prompt_influence=args.influence,
        loop=args.loop, model_id=SFX_MODEL, output_format="mp3_44100_128"))


def cmd_music(args):
    _run_audio(f"{args.seconds}s music", Path(args.output), lambda c: c.music.with_raw_response.compose(
        prompt=args.prompt, music_length_ms=int(args.seconds * 1000), model_id=MUSIC_MODEL,
        force_instrumental=args.instrumental or None, seed=args.seed))


def cmd_voice_change(args):
    source = Path(args.audio)
    if not source.exists():
        _audio_fail(f"audio not found: {source}")
    client = _eleven()
    voice_id = _resolve_voice(client, args.voice)

    _run_audio("voice change", Path(args.output), lambda c: c.speech_to_speech.with_raw_response.convert(
        voice_id=voice_id, audio=source.read_bytes(), model_id=STS_MODEL, voice_settings=_voice_settings(args),
        remove_background_noise=args.denoise, seed=args.seed, output_format="mp3_44100_128"), voice_id=voice_id)


def cmd_voices(args):
    client = _eleven()
    try:
        found = client.voices.search(search=args.search, page_size=args.limit).voices
    except Exception as e:
        _audio_fail(str(e))
    for v in found:
        print(json.dumps({"voice_id": v.voice_id, "name": v.name, "category": v.category,
                          "labels": v.labels, "description": v.description, "preview_url": v.preview_url}))


def cmd_audio_status(args):
    client = _eleven()
    try:
        client.user.get()
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 401 and "permission" in str(getattr(e, "body", "")).lower():
            audio_json(True, key="valid (no user-read permission, so credits can't be shown)")
            return
        _audio_fail(f"key rejected ({status}): {getattr(e, 'body', None) or e}")
    sub = client.user.subscription.get()
    audio_json(True, key="valid", tier=sub.tier, credits_used=sub.character_count, credits_limit=sub.character_limit,
               credits_left=sub.character_limit - sub.character_count)


def _add_voice_settings(p):
    p.add_argument("--stability", type=float, help="0-1; lower = more expressive, higher = steadier")
    p.add_argument("--similarity", type=float, help="0-1 similarity boost to the source voice")
    p.add_argument("--style", type=float, help="0-1 style exaggeration")
    p.add_argument("--speed", type=float, help="speaking rate, 1.0 = normal")


def main():
    parser = argparse.ArgumentParser(description="Asset Generator — images and videos (Gemini / xAI Grok), audio (ElevenLabs)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_img = sub.add_parser("image", help="Generate a PNG image (Gemini 5-15¢ or Grok 6-8¢)")
    p_img.add_argument("--prompt", required=True, help="Full image generation prompt")
    p_img.add_argument("--model", choices=["gemini", "grok"], default=None,
                       help="Backend: gemini (5-15¢, ~10s) or grok (6-8¢, 1-2 min); same quality. "
                            "Default: gemini if GEMINI_API_KEY/GOOGLE_API_KEY is set, else grok.")
    p_img.add_argument("--size", choices=ALL_SIZES, default="1K",
                       help="Resolution. Grok: 1K, 2K. Gemini: 512, 1K, 2K, 4K. Default: 1K.")
    p_img.add_argument("--aspect-ratio", choices=ALL_ASPECT_RATIOS, default="1:1",
                       help="Aspect ratio. Default: 1:1")
    p_img.add_argument("--image", default=None, help="Reference image for image-to-image edit")
    p_img.add_argument("-o", "--output", required=True, help="Output PNG path")
    p_img.set_defaults(func=cmd_image)

    p_vid = sub.add_parser("video", help="Generate MP4 video from prompt + reference image (8¢/sec 480p, 14¢/sec 720p)")
    p_vid.add_argument("--prompt", required=True, help="Video generation prompt")
    p_vid.add_argument("--image", required=True, help="Reference image path (starting frame)")
    p_vid.add_argument("--duration", type=int, required=True, help="Duration in seconds (1-15)")
    p_vid.add_argument("--resolution", choices=["480p", "720p"], default="720p",
                       help="Video resolution. Default: 720p")
    p_vid.add_argument("-o", "--output", required=True, help="Output MP4 path")
    p_vid.set_defaults(func=cmd_video)

    p_tts = sub.add_parser("speech", help="Text to speech (ElevenLabs credits)")
    p_tts.add_argument("--text", help="Line to speak")
    p_tts.add_argument("--text-file", help="Read the line from a file instead")
    p_tts.add_argument("--voice", required=True, help="voice_id or voice name (see `voices`)")
    p_tts.add_argument("--model", default=TTS_MODEL, help=f"Default {TTS_MODEL}; eleven_multilingual_v2, eleven_flash_v2_5 ...")
    p_tts.add_argument("--seed", type=int, help="Seed for repeatable takes")
    p_tts.add_argument("--previous-text", help="Line spoken before this one (keeps delivery continuous)")
    p_tts.add_argument("--next-text", help="Line spoken after this one")
    _add_voice_settings(p_tts)
    p_tts.add_argument("-o", "--output", required=True, help="Output .ogg / .wav / .mp3")
    p_tts.set_defaults(func=cmd_speech)

    p_sfx = sub.add_parser("sfx", help="Sound effect from a description (ElevenLabs credits)")
    p_sfx.add_argument("--prompt", required=True, help="What it sounds like")
    p_sfx.add_argument("--duration", type=float, help="0.5-30 s; default: the model chooses")
    p_sfx.add_argument("--influence", type=float, help="0-1 prompt adherence (API default 0.3)")
    p_sfx.add_argument("--loop", action="store_true", help="Seamlessly looping sound (ambience, hums, engines)")
    p_sfx.add_argument("-o", "--output", required=True, help="Output .ogg / .wav / .mp3")
    p_sfx.set_defaults(func=cmd_sfx)

    p_mus = sub.add_parser("music", help="Music track from a description (ElevenLabs credits)")
    p_mus.add_argument("--prompt", required=True, help="Genre, mood, instruments, tempo; no artist names")
    p_mus.add_argument("--seconds", type=float, required=True, help="Length, 3-600 s")
    p_mus.add_argument("--instrumental", action="store_true", help="Guarantee no vocals")
    p_mus.add_argument("--seed", type=int)
    p_mus.add_argument("-o", "--output", required=True, help="Output .ogg / .wav / .mp3")
    p_mus.set_defaults(func=cmd_music)

    p_sts = sub.add_parser("voice-change", help="Re-voice a recording in another voice (ElevenLabs credits)")
    p_sts.add_argument("--audio", required=True, help="Recorded performance (wav/mp3/ogg...)")
    p_sts.add_argument("--voice", required=True, help="Target voice_id or name")
    p_sts.add_argument("--denoise", action="store_true", help="Remove background noise from the input first")
    p_sts.add_argument("--seed", type=int)
    _add_voice_settings(p_sts)
    p_sts.add_argument("-o", "--output", required=True, help="Output .ogg / .wav / .mp3")
    p_sts.set_defaults(func=cmd_voice_change)

    p_vs = sub.add_parser("voices", help="Search ElevenLabs voices (one JSON line each)")
    p_vs.add_argument("--search", help="Name, accent, description text")
    p_vs.add_argument("--limit", type=int, default=20)
    p_vs.set_defaults(func=cmd_voices)

    p_st = sub.add_parser("audio-status", help="Check the ElevenLabs key and credits left")
    p_st.set_defaults(func=cmd_audio_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
