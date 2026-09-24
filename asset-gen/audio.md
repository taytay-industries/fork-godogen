# Audio (ElevenLabs)

Voice lines, sound effects, music, and re-voiced performances, through `asset_gen.py`. Needs `ELEVENLABS_API_KEY`; run `asset_gen.py audio-status` first — it validates the key and prints credits left without showing the key. If it fails, ask the user to add the key to their environment file themselves (never paste it into chat), then re-run it.

```bash
T=${ASSET_GEN_SKILL_DIR}/tools/asset_gen.py
python3 $T voices --search "robot"                                   # one JSON line per voice: voice_id, name, labels, preview_url
python3 $T speech --voice <voice_id> --text "Welcome to Robot School!" -o ${RUNTIME_ASSET_DIR}/audio/vo/bolt_01.ogg
python3 $T sfx --prompt "heavy metal door rattles, locked" --duration 1.2 -o ${RUNTIME_ASSET_DIR}/audio/sfx/door_locked.ogg
python3 $T sfx --prompt "low electric hum of a charging station" --duration 6 --loop -o ${RUNTIME_ASSET_DIR}/audio/sfx/pod_hum.ogg
python3 $T music --prompt "playful lo-fi chiptune, curious, 90 bpm" --seconds 60 --instrumental -o ${RUNTIME_ASSET_DIR}/audio/music/lab.ogg
python3 $T voice-change --audio take.wav --voice <voice_id> -o ${RUNTIME_ASSET_DIR}/audio/vo/line.ogg
```

Every command prints `{"ok": true, "path", "seconds", "credits"}`; `credits` is what ElevenLabs billed for the call, so report that. `audio-status` reads the account's usage counter, which lags generation by minutes. Outputs are `.ogg` (default choice), `.wav`, or `.mp3` by extension.

## Voices

- `voices` searches only the voices in the account — the premade set plus any the user added from the ElevenLabs library — so a search for a character type ("robot") usually finds nothing; browse the list and judge by the labels and description.
- **Cast before scripting.** A voice is chosen once per character and every line depends on it: search, then generate one representative line in 2–3 candidates and let the user pick by listening. Record the chosen `voice_id`, model, and any `--stability/--style/--speed` in the README manifest — a later line in a different setting sounds like a different actor.
- **One file per line**, named by line id (`bolt_01.ogg`), generated from the script the game shows, so subtitles and audio can't drift apart. Pass the neighbouring lines as `--previous-text/--next-text` so a conversation keeps one delivery instead of resetting its intonation every line.
- `--stability` low (~0.3) for animated characters, high (~0.7) for narrators and system voices.
- **voice-change** keeps a recorded performance's timing and emotion and swaps the speaker — the way to get an exact read (a comic pause, a scream) that text can't direct. Input needs to be clean; `--denoise` if not.

## Sound effects

- One-shots: give `--duration` close to the real event (a click is 0.5 s, a door 1–2 s); otherwise the model picks the length.
- Continuous sounds (hums, engines, rain, room tone) use `--loop` — the result wraps without a click, including after the `.ogg` conversion. Set loop on the imported stream; everything else stays one-shot.
- Levels are not normalized: a hum can come back 15–20 dB louder than a door rattle. Set each sound's volume in the engine by ear against the others, never leave them all at 0 dB.
- Frequently repeated sounds (footsteps, hits, UI clicks) need 2–4 takes: one file played 50 times is the most recognizable tell of generated audio. Randomize take and pitch (±5%) at playback.

## Music

- `--instrumental` for anything that plays under dialogue or gameplay. Prompts can't name artists or copyrighted songs (the API refuses); describe genre, mood, instrumentation, and tempo instead.
- Tracks are not generated as seamless loops. Loop a background track with a crossfade at the loop point, or generate it longer than a typical play session segment.
