---
name: game-design-critique
description: Critique a game the way a professional game designer would, from captured frames and video — camera framing, readability, feedback/juice, HUD, pacing, fairness — and turn each finding into a concrete, numeric fix. Use when the user asks for a design review, "what would a game designer say", polish passes, or after a capture when the game works but may not feel good.
---

# Game design critique

Review what the player actually sees, not the code. A game can be bug-free and still read as amateur; this pass finds that gap and fixes it.

## Gather evidence first

- If the repo has `tools/capture.py` (godogen), record with it and read `sheet.png`, then `motion.png`. Otherwise record gameplay any way the project supports and sample ~12 evenly spaced frames.
- Contact-sheet tiles are ~1/4 scale and their labels cover the top-left corner. **Judge framing, HUD, and small detail from full-size frames** (`capture.py frames <clip> --at 82,300`), at least one early, one mid-action, one at the player's movement extremes.
- Before/after every fix, compare the same moment (`capture.py diff a.png b.png`); seed randomness in the capture so frames line up.

## What a designer looks at, with the numbers they use

**Camera and framing**
- The player's avatar should be clearly readable: for a chase/rail camera ~18–25% of screen width; top-down/side-view avatars ≥5% of screen height. Under ~12% reads as "too far away".
- Chase/rail shooters place the avatar in the lower third, leaving the top two-thirds for threats. Centered avatars cover the play.
- At the avatar's movement extremes it must stay fully in frame and clear of HUD — check the frames where it's at each bound. A camera that follows too loosely lets it slide off-screen; too tightly and motion stops reading.
- Nothing should fly through the lens and fill the screen — despawn/fade objects before the near plane.

**Readability**
- Silhouette and value contrast: threats, pickups, and the player must separate from the background when squinted at (or when the frame is desaturated/blurred). Same-value clutter is the most common problem.
- Scale consistency: generated assets arrive at arbitrary scales and orientations — verify the avatar faces its direction of travel and props sit at believable relative sizes.
- Particle and effect density must never hide the avatar or incoming threats.
- Extreme roll/pitch on banking turns a model edge-on — keep roll ≲25° unless it's a deliberate maneuver.

**Feedback ("juice")**
- Every player action gets a response within ~100 ms (≈3 frames at 30 fps): muzzle flash, recoil, sound, hit flash.
- Hits need 2–3 layered cues (flash + particles + shake/hitstop/sound); taking damage needs a louder, distinct cue than dealing it.
- Screen shake scales with event size and decays fast (≲0.3 s); constant shake is noise.

**HUD and UI**
- Keep critical HUD inside a ~5% safe margin; score/lives should be readable at a glance from full-size frames.
- Control hints fade after the first few seconds or once used; persistent hints clutter the frame.
- HUD must not overlap where the avatar or threats spend time.

**Pacing and difficulty**
- No dead time: something meaningful should be happening in the first second (use `motion.png` — flat stretches are boredom, not just bugs).
- Intensity should build and breathe (tension → release), not stay flat or spike randomly.
- Fairness: threats are telegraphed and visible long enough to react (~0.5 s minimum); player hitboxes are slightly *smaller* than the visual, enemy hitboxes slightly *larger* for shots.
- A demo/autopilot that never takes damage hides the fail state — the capture should show damage feedback at least once.

## Output

A short, prioritized list — most noticeable to a player first. For each finding:
- **What** — the issue in designer terms, with the frame numbers that show it.
- **Why it matters** — the player-facing effect.
- **Fix** — concrete and numeric (camera from 10 m to 6 m, roll 0.06→0.03 rad/(m/s), hint alpha 0 after 5 s), not "consider improving".

Then apply fixes when the user wants them, re-capture, and show the before/after diff of the same moment. Stop at the few changes that move the needle; a critique of twenty nits gets none fixed.
