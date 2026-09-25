# Recipe: game assets

## Mobile / low-poly (P1, clean topology, FBX)

```bash
tripo make "a stylized barbarian axe" --for game-mobile --json --yes
# → P1, face_limit 15000, 2K textures, convert to FBX
```

Tighter budget and Unity delivery:

```bash
tripo make "a health potion bottle" --for game-mobile \
  -p face_limit=3000 --then convert:format=FBX,texture_size=1024 --json --yes
```

## PC / console (v3.1, detailed PBR)

```bash
tripo make "an ornate treasure chest, fantasy style" --for game-pc --json --yes
```

## LODs from one high-poly

```bash
tripo make "a stone golem" --for game-pc --then decimate:5000 --json --yes   # bakes normals by default
tripo make @last --then decimate:1500,convert:fbx --json --yes               # next LOD from the same source
```

## Character with animations (see also examples/animation.md)

```bash
tripo make "a knight in full armor, T-pose, standing straight" --for anim --json --yes
# chain: rig-check → rig(v2.5 rig) → retarget(idle+walk)
```
