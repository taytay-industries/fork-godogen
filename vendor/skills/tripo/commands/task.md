# tripo task / files / history

## tripo task get <id|@last|@name>

Fetch one task. `--step` adds pipeline step details. `--download` fetches artifacts (output URLs expire in ~5 minutes, so the CLI always re-queries before downloading).

```bash
tripo task get @last --download --json
```

## tripo task watch <id>

Block until the task finishes. In `--json` mode, progress streams as NDJSON events on stdout (`{"event":"progress",...}` lines) and the final task detail is the last line. `--download` grabs artifacts on success. `--timeout <seconds>` (default 1800).

Rules for agents: treat `watch` as synchronous; read lines until process exit; exit code 6 means the task failed (credits refunded).

## tripo task list [ids...]

Batch query. With no ids, shows the most recent local history entries (server-refreshed). JSON output is `{"tasks":[...],"missed":[id,...]}` — `missed` lists ids the server could not find (wrong account/region).

## tripo files upload <path>

Upload an image (≤20MB, PNG/JPEG/WebP/BMP/TIFF) or model (≤150MB, GLB/FBX/OBJ/STL). Prints `{"file_token":"file_..."}` — pass it anywhere an input is accepted. `.gltf` is not uploadable (it references external files) — export as `.glb` or pass a URL instead.

## tripo history

Local task history with `@name` references: `{"task_id","type","name","status","output_dir"}`.
