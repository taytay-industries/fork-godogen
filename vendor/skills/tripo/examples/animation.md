# Recipe: character animation

## One shot (generate → rig → animate)

```bash
tripo make "a cartoon fox character, T-pose" --for anim --json --yes
# rig-check gates the chain: if not riggable it stops early (no credits wasted)
```

## Step by step with pipes

```bash
tripo make "a robot soldier, T-pose" --json --yes \
  | tripo anim check --json \
  | tripo anim rig --spec mixamo --out-format fbx --json \
  | tripo anim retarget --animation preset:idle preset:walk preset:run --json
```

## Animate an existing model file

```bash
tripo make hero.glb --then rig-check,rig,retarget:preset:walk --json --yes
```

## T-pose image first (better rigging on tricky subjects)

```bash
tripo generate text-to-image "full-body front view of a ninja" -p template=t_pose --json --yes
tripo generate image-to-model @last --json --yes                          # image task id works as input
tripo make @last --then rig-check,rig,retarget:preset:run --json --yes
```

Rules: retarget needs a rig task (≤5 animations, billed per animation); the v2.5 rig (CLI default) covers all 7 body types; Unity Humanoid → `--spec mixamo`; in-game locomotion → `--animate-in-place`.
