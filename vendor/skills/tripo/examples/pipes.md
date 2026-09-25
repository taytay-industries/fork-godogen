# Recipe: shell pipelines & batch

## NDJSON pipes

stdout of every task command is a single JSON line when piped; downstream commands read it from stdin:

```bash
tripo make cat.png --json | tripo model texture --texture-quality detailed --json | tripo model convert --format FBX --json
```

Grab fields with jq:

```bash
dir=$(tripo make "a mug" --json --yes | jq -r .output_dir)
open "$dir/preview.png"
```

## Multi-candidate exploration

```bash
tripo make "a cute dragon hatchling" -n 4 --json --yes   # 4 seeds in parallel
# pick the best preview.png, then:
tripo make <winning-task-id> --then texture,convert:fbx --json --yes
```

## Reproducibility

Every artifact dir contains `task.json` (request + seeds + credits). Re-create the same geometry:

```bash
seed=$(jq -r '.input.model_seed' tripo-out/mug-*/task.json)
tripo make "a mug" --seed "$seed" --json --yes
```

## Bulk

```bash
tripo batch run assets.yaml --concurrency 3      # resumable; see commands/batch.md
```
