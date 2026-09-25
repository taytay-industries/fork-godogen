# Build ${ENGINE_NAME} game from a description

- Keep durable project status in `README.md`: what is built, what is left, and an asset table.
- Generate visual and audio assets with `${ASSET_SKILL_COMMAND}`. Confirm the spend with the user before the first paid generation. Generated files are committed through Git LFS (set up at publish), so a paid asset is never regenerated just to rebuild the repo.
- Read `${ENGINE_GUIDE_FILE}` for engine guidance: stack, project layout, how to run, and how to capture.

## Delivery

Judge progress from the running game, never from a clean build: verify the structural things yourself (it loads, no errors, assets present) and let what you see drive the next iteration.

Decide from how the task is framed how to work. A task that invites collaboration — open-ended, exploratory, phrased as a direction rather than a spec — gets the live game early: checkpoint at decisions of taste, scope, or cost, and build freely in between. A task handed over as a finished brief to execute gets reasonable calls and steady progress, no blocking. Either way the result is proven, not claimed — if the user hasn't seen it running, finish with a 15–20s video of the game in action, and watch it back before you call the work done. Once a capture runs clean, review it with the `game-design-critique` skill and fix what it finds before presenting. Show results rather than describe them: send the video, the contact sheet, or the asset feed.
