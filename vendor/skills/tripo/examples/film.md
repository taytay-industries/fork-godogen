# Recipe: film / offline rendering

Quads for subdivision, maximum quality, DCC handoff.

```bash
tripo make "an antique brass telescope" --for film --json --yes
# → v3.1, quad=true (FBX out), geometry+texture detailed, 4K PBR
```

USD pipeline handoff:

```bash
tripo make @last --then convert:format=USDZ,texture_format=PNG --json --yes
```

HDR textures for compositing:

```bash
tripo make @last --then "convert:format=OBJ,texture_format=OPEN_EXR,texture_size=4096" --json --yes
```

Notes: quad topology cannot live in GLB — deliverables are FBX/OBJ/USD; `geometry_quality=detailed` bills an extra HD credit; non-default convert options bill as complex convert.
