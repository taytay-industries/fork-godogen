# tripo batch run

Bulk production from a YAML manifest with concurrency, retries, and resume.

```bash
tripo batch run assets.yaml [--concurrency 2] [--retries 1] [--fresh]
```

## Manifest

```yaml
concurrency: 2
defaults:
  for: game-mobile
  then: "texture,convert:fbx"
  out: ./assets
jobs:
  - input: "a bronze sword"
  - input: "a wooden shield"
    name: shield            # names become @references and state keys
  - input: cat.png
    for: print
    then: "convert:stl,flatten_bottom=true"
  - inputs: [hero-front.png, hero-back.png]
    name: hero
    params: { texture_quality: detailed }
```

## Behavior

- State is saved next to the manifest (`assets.yaml.state.json`) after every job. Re-running the same command **skips succeeded jobs** (resume). `--fresh` starts over.
- Failed jobs retry up to `--retries` times, then are reported; exit code 6 if any job stays failed.
- Final stdout JSON: `{"total","success","failed","state_file","jobs":{...}}`.
