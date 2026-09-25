#!/usr/bin/env bash
# Refresh vendor/skills/ from the vendors' own agent skills. publish.sh installs them next to asset-gen.
#
#   ElevenLabs: github.com/elevenlabs/skills (MIT) — the skills a game uses, renamed elevenlabs-*
#   Tripo:      the skill bundled in the tripo-cli npm package (MIT), given a SKILL.md header
set -euo pipefail
cd "$(dirname "$0")"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
OUT=skills
rm -rf "$OUT"; mkdir -p "$OUT"

git clone -q --depth 1 https://github.com/elevenlabs/skills.git "$TMP/el"
EL_REV=$(git -C "$TMP/el" rev-parse --short HEAD)
for s in text-to-speech sound-effects music voice-changer speech-to-text setup-api-key; do
    cp -r "$TMP/el/$s" "$OUT/elevenlabs-$s"
    sed -i "0,/^name: .*/s//name: elevenlabs-$s/" "$OUT/elevenlabs-$s/SKILL.md"
done
cp "$TMP/el/LICENSE" "$OUT/LICENSE-elevenlabs"

(cd "$TMP" && npm pack -s tripo-cli >/dev/null && tar xzf tripo-cli-*.tgz)
TRIPO_VER=$(node -p "require('$TMP/package/package.json').version")
cp -r "$TMP/package/skill" "$OUT/tripo"
{
    printf -- '---\nname: tripo\n'
    printf 'description: Generate, rig, animate, convert, and inspect 3D models with the tripo CLI (Tripo 3D). Full command, example, and error reference for the CLI that asset-gen uses for GLB models.\n'
    printf 'license: MIT\n---\n\n'
    cat "$TMP/package/skill/SKILL.md"
} > "$OUT/tripo/SKILL.md"
printf 'MIT License — tripo-cli %s (npm). See https://www.npmjs.com/package/tripo-cli\n' "$TRIPO_VER" > "$OUT/LICENSE-tripo"

printf 'elevenlabs/skills %s\ntripo-cli %s\n' "$EL_REV" "$TRIPO_VER" > "$OUT/VERSIONS"
echo "vendor/skills: elevenlabs/skills@$EL_REV, tripo-cli@$TRIPO_VER"
