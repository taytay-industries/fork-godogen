# tripo view / redo / ai / mcp

## tripo view [task|@last|file.glb]

Starts a local model-viewer page and opens the browser (humans). Headless callers should read `preview.png` from the artifact directory instead — the files are already local; the browser is optional. `--keep` holds the server until Ctrl+C.

## tripo redo [task|@last] [--seed N]

Re-submits the recorded request with a fresh `model_seed` (identical otherwise). Only works for tasks created by this CLI (history holds the payload). Result is a new task, downloaded like `make`.

## tripo ai [request...]

- Without an LLM configured: interactive wizard (3–4 questions) → plan card → confirm → run. Terminal required.
- With an LLM (`tripo config set llm.*`): natural-language planning by producer + domain-specialist agents → same plan card → confirm (`--yes` skips) → run.
- Agents: prefer `tripo make --for <scenario>` — it is deterministic and needs no LLM. `@task-name` references inside the request resolve to task ids.

## tripo mcp

MCP server on stdio for Cursor/Claude Desktop:

```json
{ "mcpServers": { "tripo": { "command": "tripo", "args": ["mcp"], "env": { "TRIPO_API_KEY": "tsk_..." } } } }
```

Tools: `tripo_make` (blocking generate+download), `tripo_task_get`, `tripo_task_wait`, `tripo_balance`, `tripo_history`.
