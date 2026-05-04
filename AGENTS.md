# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

## BLOCKED commands — do NOT attempt these

### curl / wget — BLOCKED
Any shell command containing `curl` or `wget` will be intercepted and blocked by the context-mode plugin. Do NOT retry.
Instead use:
- `context-mode_ctx_fetch_and_index(url, source)` to fetch and index web pages
- `context-mode_ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — BLOCKED
Any shell command containing `fetch('http`, `requests.get(`, `requests.post(`, `http.get(`, or `http.request(` will be intercepted and blocked. Do NOT retry with shell.
Instead use:
- `context-mode_ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### Direct web fetching — BLOCKED
Do NOT use any direct URL fetching tool. Use the sandbox equivalent.
Instead use:
- `context-mode_ctx_fetch_and_index(url, source)` then `context-mode_ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Shell (>20 lines output)
Shell is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `context-mode_ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `context-mode_ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### File reading (for analysis)
If you are reading a file to **edit** it → reading is correct (edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `context-mode_ctx_execute_file(path, language, code)` instead. Only your printed summary enters context.

### grep / search (large results)
Search results can flood context. Use `context-mode_ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `context-mode_ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `context-mode_ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `context-mode_ctx_execute(language, code)` | `context-mode_ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `context-mode_ctx_fetch_and_index(url, source)` then `context-mode_ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `context-mode_ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `upgrade` MCP tool, run the returned shell command, display as checklist |

---

# Project: Isaac Sim Industrial Safety SDG Pipeline

## Execution Model — CRITICAL

**Development happens locally. Execution happens on a RunPod GPU container.**
- You CANNOT SSH into or run commands on the RunPod. You write code locally; the user runs it on the pod.
- When you need to test or verify Isaac Sim code, guide the user to run it on their pod. Provide exact commands.
- `/workspace` on the pod is slow persistent storage. `/tmp` is fast NVMe.
- Always write Replicator output to `/tmp/dataset`, then `tar -czf` to `/workspace/` for persistence.

## RAG System — Your First Stop for Isaac Sim APIs

When you need help with Isaac Sim / Omniverse APIs, Replicator, USD, or any Isaac Sim function:
1. Query the RAG system: `python -m rag_system.query "your question about the API"`
2. Or build the index first if needed: `python -m rag_system.build_index`
3. The RAG contains crawled Isaac Sim 5.1 docs, curated knowledge base, and project source code.
4. Use RAG context to inform your code — do NOT guess Isaac Sim API signatures.

## Two Python Environments

| Component | Python | Location |
|-----------|--------|----------|
| LLM Pipeline (schemas, generator) | System `python3` | `llm_pipeline/` |
| Isaac Sim Backend (Replicator, USD) | `/isaac-sim/python.sh` | `isaac_backend/` |
| Post-processing scripts | System `python3` | `scripts/` |
| RAG System | System `python3` | `rag_system/` |

**CRITICAL:** In ALL Isaac Sim scripts, `SimulationApp({"headless": True})` MUST be instantiated BEFORE any `omni.*` or `pxr.*` imports. See `isaac_backend/main.py:11-12`.

## Main Pipeline Orchestration

Run on RunPod: `./scripts/run_pipeline.sh "your prompt"`

This executes exactly 8 steps:
1. `python3 llm_pipeline/generator.py` → LLM extracts SceneConfig JSON (requires `GEMINI_API_KEY`)
2. `rm -rf /tmp/dataset` → Clear old data
3. `/isaac-sim/python.sh isaac_backend/main.py` → Isaac Sim generates dataset
4. `python3 scripts/coco_to_yolo.py --dir /tmp/dataset --masks` → Convert COCO to YOLO
5. `python3 scripts/gen_dataset_yaml.py` → Generate `dataset.yaml`
6. `python3 scripts/class_balance.py` → Report class distribution
7. `./scripts/make_video.sh` → Generate video from frames
8. `tar -czf /workspace/dataset_<timestamp>.tar.gz` → Archive to persistent storage

The pipeline patches `/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py` to fix a `None` `submodule_search_locations` bug. Do not remove this patch.

## Environment Variables

- `DROPLET_API_KEY` — Bearer token for API auth (`Authorization: Bearer <key>`). Leave empty to disable auth in dev.
- `ACCEPT_EULA` — Set to `Y` for Isaac Sim headless runs.
- `NIM_API_KEY` — NVIDIA NIM API key. Passed at runtime via `X-NIM-API-Key` request header; injected into the subprocess env by `api/server.py`. Never stored in `.env`.

See `.env.example` for the minimal env file. Frontend integration contract: `docs/FRONTEND_INTEGRATION.md`.

## Key Architecture

```
llm_pipeline/
  schemas.py      — Pydantic models: SceneConfig, Entity, HazardZone, WorkerBehavior, BehaviorCommand
  generator.py    — Instructor + Gemini: text → SceneConfig JSON

isaac_backend/
  main.py             — Entry point: SimulationApp bootstrap, scene assembly, Replicator loop
  config_loader.py    — Loads SceneConfig JSON + asset library
  warehouse.py        — Thin dispatch into layouts/ package
  layouts/            — Procedural layout package (presets, geometry, racks, docks, props, markings, materials, realism)
  spawner.py          — Geofenced entity spawner
  camera.py           — Camera positioning and orbit distributions
  lighting.py         — Lighting setup
  semantics.py        — USD semantic label application (maps variant assets to canonical COCO classes)
  workers.py          — Worker (character) spawning
  ira_setup.py        — IRA extension load, biped baking, behavior attachment, anim graph linking
  command_injection.py — IRA AgentManager command injection (GoTo / Idle / LookAround)
  vehicle_animation.py — Forklift / vehicle motion paths
  navmesh_utils.py    — Navmesh queries + target snapping
  layout_planner.py   — Layout selection helpers

assets/
  library.json    — Asset registry: worker, forklift, pallet, rack, zone, box, box_small, box_large, barrel, drum, cone, crate
  layouts.json    — 8 layout presets: standard_warehouse, narrow_aisle, open_floor, cross_dock, cold_storage, loading_dock, maintenance_bay, storage_yard
```

## Data Flow

1. User prompt → LLM → `configs/current_scene.json` (Pydantic-validated SceneConfig)
2. SceneConfig + `assets/library.json` → Isaac Sim → `/tmp/dataset/` (COCO format: RGB + bbox + segm + instance segm)
3. COCO → YOLO `.txt` files + `dataset.yaml`
4. Archive: `/tmp/dataset/` → `/workspace/dataset_<ts>.tar.gz`

## Isaac Sim Gotchas

- Use `CocoWriter` (not `BasicWriter`) for COCO output with explicit `coco_categories`. Do NOT write directly to `/workspace`.
- After generation, wait for writer flush — `main.py` polls for `bounding_box_2d_tight_*.npy` files with a 60s timeout.
- Teardown order: `rep.orchestrator.stop()` → `writer.detach()` → `world.clear()` → `simulation_app.close()` → `os._exit(0)`.
- `omni.timeline.get_timeline_interface().play()` must be called before character animations work.
- Warehouse USD zone is loaded from `asset_library["zone"]` via `rep.create.from_usd()`.
- DLSS must be set to Quality mode (`/rtx/post/dlss/execMode = 2`) to avoid rendering artifacts at low resolutions.
- `rep.orchestrator.set_capture_on_play(False)` is required — manual `step()` controls capture.
- Pass `--/exts/isaacsim.core.throttling/enable_async=false` to prevent frame skipping during Replicator runs.
- Worker animation uses IRA's built-in character_behavior.py (Omni.Anim.People). Commands injected via AgentManager (`isaac_backend/command_injection.py`).
- IRA behavior attachment: Phase 1 (before play) = attach built-in script via CharacterUtil (`ira_setup.py`). Phase 2 (after play) = inject GoTo/Idle/LookAround via AgentManager.inject_command() (`command_injection.py`).
- Import `World` from `isaacsim.core.api`, NOT `omni.isaac.core`.
- Layout assets map to COCO categories via `SEMANTIC_MAP` in `isaac_backend/layouts/`: box_small/box_large/crate → "box", drum → "barrel". All other assets map 1:1.
- Rack shelf population: `_populate_rack_shelves()` places 2 items per shelf level (at z=0.15, 0.85, 1.55) with fill probability controlled by `rack_fill` param (empty=0%, sparse=30%, medium=60%, full=90%).
- Pallets are spawned loaded: 50% chance of box/crate stack, 25% chance barrel/drum, 25% bare pallet.
- Dock areas: when `dock_area=true` in layout params, a cluster of loaded pallets + extra props spawns near the warehouse entrance (negative-Y wall).
- Layout presets in `assets/layouts.json` override default `_resolve_params()` values. Each preset can specify `rack_fill`, `dock_area`, and `clutter_zones`.

## Validation

- Syntax check: `python3 -m py_compile <file>` for any Python file
- Schema check: Run `python3 llm_pipeline/generator.py --prompt "test" --output /dev/null` (will fail without API key but validates imports)
