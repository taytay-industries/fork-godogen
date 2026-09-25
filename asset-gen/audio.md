# Audio (ElevenLabs)

Voice lines, sound effects, music, and re-voiced performances come from the official `elevenlabs` CLI (`npm install -g @elevenlabs/cli`; reads `ELEVENLABS_API_KEY`). It mirrors the whole API — `elevenlabs <group> --help`, or `--schema` for a machine-readable version — so this page covers only what matters for games. Every generated file then goes through `tools/audio_prep.py`, which converts it for the engine and checks it.

```bash
elevenlabs user subscription get --format json --query '{tier: tier, used: character_count, limit: character_limit}'
```

That validates the key and shows credits. If it fails, ask the user to put the key in their environment file themselves — never paste it into chat. The usage counter lags generation by a few minutes: read it before a batch and again at the end, and report the difference as the spend.

## Generate, then prepare

The CLI saves the API's MP3 (`-o`; `--format json` prints `{"saved_file", "bytes"}`). Plans cap concurrent requests (Starter: 3) — more in parallel fail with `429 concurrent_limit_exceeded`, so batch at most 3 at a time. A failure exits 1 with a JSON `error` — read `error.details`; its `help` text may blame credentials when the key was fine. Keep raw MP3s outside the runtime asset folder and write the engine file with `audio_prep.py`:

```bash
P="python3 ${ASSET_GEN_SKILL_DIR}/tools/audio_prep.py"; E="python3 ${ASSET_GEN_SKILL_DIR}/tools/feed.py run --"   # feed: SKILL.md
$E elevenlabs text-to-speech convert --voice-id <id> --model-id eleven_v3 --text "Halt! Who goes there?" -o raw/guard_01.mp3
$P raw/guard_01.mp3 -o ${RUNTIME_ASSET_DIR}/audio/vo/guard_01.ogg --lufs -18

$E elevenlabs text-to-sound-effects convert --text "classroom door handle jiggled, door rattles against its lock" \
  --duration-seconds 1.2 --prompt-influence 0.6 -o raw/door_locked.mp3
$P raw/door_locked.mp3 -o ${RUNTIME_ASSET_DIR}/audio/sfx/door_locked.ogg

$E elevenlabs text-to-sound-effects convert --text "low electric hum of a charging station" --duration-seconds 6 --loop true -o raw/hum.mp3
$P raw/hum.mp3 -o ${RUNTIME_ASSET_DIR}/audio/sfx/hum.ogg --loop

$E elevenlabs music compose --prompt "playful lo-fi chiptune, curious, 95 bpm" --music-length-ms 60000 \
  --force-instrumental true --model-id music_v2 -o raw/theme.mp3
$P raw/theme.mp3 -o ${RUNTIME_ASSET_DIR}/audio/music/theme.ogg --lufs -16

$E elevenlabs speech-to-speech convert --audio take.wav --voice-id <id> --model-id eleven_multilingual_sts_v2 -o raw/line.mp3
```

`audio_prep.py` prints `seconds`, `peak_db`, `lufs`, what it trimmed, and `warnings` — act on the warnings before wiring the sound in:

- **One-shots and music:** leading silence is trimmed (a music track came back with 5 s of near-silence before the first note; a late one-shot reads as input lag). Trailing silence is reported, not cut.
- **Loops (`--loop`):** nothing is trimmed, and it reports `level_range_db`, the spread of loudness across the clip. `--loop true` makes the wrap seamless at the sample level, but the loudness inside the clip can still drift — a 6 s hum rose 3 dB over its last 2 s, which a listener hears as a swell into noise that cuts back every pass, while the seam itself measured clean. Over 1.5 dB it warns; `--flatten` divides out the envelope with a gain curve smoothed around the wrap (3.2 → 0.1 dB, seam intact). Prompting for "constant, even volume" did not help — one such take swung 6.8 dB — so generate 2–3 takes of an important loop and keep the steadiest.
- **Levels** are not normalized between generations (a hum came back ~18 dB louder than a door rattle). `--lufs` normalizes and caps peaks at -2 dBFS: about -16 for music, -18 for dialogue. Set SFX volumes in the engine by ear against each other.
- Output is `.ogg` (Vorbis; set loop on the imported stream), `.wav`, or `.mp3` by extension.

## Voices

- `voices search` covers only the account's voices (the premade set plus any the user added). The public library is `voices get_shared --search "<character type>"` — a search for "robot" found retro-computer, AI-assistant, and robot-character voices — and a shared `voice_id` works in `text-to-speech convert` directly, without adding it to the account.
- **Cast before scripting.** Generate one representative line in 2–3 candidate voices and let the user pick by listening (send MP3 copies: `.ogg` doesn't play on iOS). Record the chosen `voice_id`, model, and `--voice-settings` in the README manifest — a later line with different settings sounds like a different actor.
- **One file per line**, named by line id (`guard_01`), generated from the script the game shows so subtitles and audio can't drift apart. Pass the neighbouring lines as `--previous-text` / `--next-text` so a conversation keeps one delivery instead of resetting its intonation every line.
- `--voice-settings '{"stability": 0.35}'` for animated characters, ~0.7 for narrators and system voices.
- **Acting on `eleven_v3`** is directed with free-form bracketed tags before the words they color — `[dictating, bored]`, `[sleepy] [whispers to herself]`, `[flat, reading from a script, unenthusiastic]`, `[in a deep, dramatic movie-trailer narrator voice]`, `[gasps] [surprised]`, `[relieved, laughing]` — plus `...` for hesitation. Voices differ a lot in how many directions they honor, so audition the widest-range lines, not a neutral one. A tag alone won't make one character imitate another (a robot, an accent): `[in a stilted robot voice]` barely changed the read, while adding the words that signal the impression — `[mockingly impersonating a robot] Beep boop. Maybe it…` — made it land. Post-processing the phrase (ring modulation) sounded like the robot speaking rather than her imitating it. Voice metadata doesn't mark v3 suitability (`high_quality_base_model_ids` never lists `eleven_v3`); library voices built for it say so in their description — search `voices get_shared --search v3`.
- **speech-to-speech** (voice changer) keeps a recorded performance's timing and emotion and swaps the speaker — the way to get an exact read (a comic pause, a scream) that text can't direct. Input must be clean; `--remove-background-noise true` if not.
- **Conversations** (overheard chatter, banter, cutscenes) render in one call with `text-to-dialogue convert --json -` and a body `{"model_id": "eleven_v3", "inputs": [{"text", "voice_id"}, ...]}` (≤2,000 characters per request): the model times the turns, overlaps, and reactions itself, which sounds far more natural than stitching single lines. Keep the script as data in the repo and build the body from it. Inline v3 tags (`[sighs]`, `[gasps]`, `[whispers]`, `[laughs]`, `[chuckles]`) and a mid-sentence `—` for an interruption are performed, not read aloud; render the same script in two voice pairs and let the user pick.
- **Check a take you can't listen to** by transcribing it: `speech-to-text convert --model-id scribe_v1 --file take.mp3 --tag-audio-events true --format json` returns the words plus bracketed sound events — a tag that was spoken aloud, a skipped line, or a missing reaction shows up there.
- The CLI can also design a new voice from a description (`text-to-voice design`).

## Sound effects and music

- One-shots: give `--duration-seconds` close to the real event (a click 0.5 s, a door 1–2 s); otherwise the model picks the length.
- Frequently repeated sounds (footsteps, hits, UI clicks) need 2–4 takes: one file played 50 times is the most recognizable tell of generated audio. Randomize take and pitch (±5%) at playback.
- `--force-instrumental true` for anything under dialogue or gameplay. Prompts can't name artists or copyrighted songs; describe genre, mood, instrumentation, and tempo. Music is not generated as a seamless loop — loop a background track with a crossfade, or make it longer than a typical stretch of play.

## Costs

Credits come from the plan's monthly quota. Measured: speech costs 0.5 credits per character on `eleven_v3` and `eleven_multilingual_v2` (0.25 on `eleven_flash_v2_5`), and **v3 direction tags are billed as characters** — a 35-character line costs 18, or 35 with `[mumbling to herself, unimpressed]` in front. Retakes cost the same as the first take, so auditioning 10 deliveries of a short line is ~300 credits. Sound effects cost 10 credits per second (0.5 s → 5, 1.2 s → 12); a 3 s voice-changer take cost 29. The per-request cost is the `character-cost` response header, but the CLI shows headers only with `--format http`, which prints the audio to stdout instead of saving it — so account for spend with the before/after usage read above.
