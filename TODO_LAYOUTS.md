# Phase 6: Parameterized Procedural Layouts

## Overview

Replace the single hardcoded warehouse layout in `isaac_backend/warehouse.py` with a parameterized procedural engine.
Users can select from 8 presets, override individual parameters, or define fully custom layouts via natural language.

**Architecture:** JSON metadata (`assets/layouts.json`) → LLM extracts `layout` + `layout_params` → Procedural generator (`isaac_backend/layouts.py`) builds the scene.

---

## Task 6.1: Layout Metadata Registry

**File:** `assets/layouts.json` (new)

Define 8 layout presets. Each entry contains:

```json
{
  "<preset_name>": {
    "description": "<human-readable description for LLM prompt injection>",
    "keywords": ["<keyword1>", "<keyword2>"],
    "rack_pattern": "rows|grid|L-shape|perimeter|clusters|none",
    "rack_rows": <int>,
    "rack_cols": <int>,
    "aisle_width": <float>,
    "bounds_min": [<float>, <float>],
    "bounds_max": [<float>, <float>],
    "clutter_density": "low|medium|high",
    "clutter_zones": [
      {"area": "<zone_name>", "bounds_min": [<f>,<f>], "bounds_max": [<f>,<f>], "density": "low|medium|high", "types": ["box","barrel","cone","pallet"]}
    ],
    "pallet_rows": <int>,
    "pallet_cols": <int>
  }
}
```

### Presets to define:

| Key | Description |
|-----|-------------|
| `standard_warehouse` | Default 5-row warehouse with moderate aisles and scattered clutter |
| `narrow_aisle` | Cramped high-density storage with 7 rack rows and tight passages |
| `open_floor` | Sparse layout with 2 perimeter rack rows, wide open areas |
| `cross_dock` | L-shaped rack arrangement with wide truck corridor |
| `cold_storage` | Dense grid layout with heavy barrel clustering |
| `loading_dock` | Minimal racks, heavy pallet staging, truck bay area |
| `maintenance_bay` | No racks, open service area with cone-marked safety zones |
| `storage_yard` | 4 rack clusters with wide lanes, outdoor-style yard |

**Conventions:**
- All `bounds_min`/`bounds_max` values must fit within the warehouse USD footprint (±7m X, ±7m Y per `camera.py:WAREHOUSE_INTERIOR_X/Y`)
- `clutter_zones` is optional; if empty or absent, clutter is distributed globally
- `keywords` must include synonyms the LLM might encounter (e.g., "cramped", "tight", "dense" for `narrow_aisle`)

---

## Task 6.2: Schema Extension

**File:** `llm_pipeline/schemas.py`

Current state (line 35-60): `SceneConfig` has `entities`, `hazard_zones`, `camera_angles`, `camera_mode`, `camera_position`, `lighting_conditions`, `worker_behaviors`.

Add two new Pydantic models and extend `SceneConfig`:

### New Model: `ClutterZone`
```python
class ClutterZone(BaseModel):
    area: str
    bounds_min: tuple[float, float]
    bounds_max: tuple[float, float]
    density: Literal["low", "medium", "high"] = "medium"
    types: List[str] = Field(default_factory=lambda: ["box", "barrel", "cone", "pallet"])
```

### New Model: `LayoutParams`
```python
class LayoutParams(BaseModel):
    rack_pattern: Literal["rows", "grid", "L-shape", "perimeter", "clusters", "none"] = "rows"
    rack_rows: int = 5
    rack_cols: int = 1
    aisle_width: float = 2.0
    bounds_min: tuple[float, float] = (-5.0, -5.0)
    bounds_max: tuple[float, float] = (5.0, 5.0)
    clutter_density: Literal["low", "medium", "high"] = "medium"
    clutter_zones: List[ClutterZone] = Field(default_factory=list)
    pallet_rows: int = 2
    pallet_cols: int = 1
```

### Extend `SceneConfig` (after line 60):
```python
layout: str = Field(default="standard_warehouse", description="Layout preset name or 'custom'")
layout_params: Optional[LayoutParams] = Field(default=None, description="Parameter overrides for custom or preset-based layouts")
```

**Conventions:**
- `layout` defaults to `"standard_warehouse"` for backward compatibility
- `layout_params` is `None` when using preset defaults; populated when user requests changes
- Field descriptions must be explicit so the LLM understands valid ranges

---

## Task 6.3: LLM Layout Selection Prompt

**File:** `llm_pipeline/generator.py`

Current state: `system_prompt` (lines 29-66) covers entities, PPE, hazard zones, camera, lighting, worker behaviors. No layout awareness.

### Changes:

1. **Load layout metadata at prompt-build time:**
   ```python
   LAYOUTS_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "layouts.json")
   with open(LAYOUTS_PATH) as f:
       layouts = json.load(f)
   ```

2. **Inject layout descriptions into system prompt dynamically:**
   Build a section listing each preset's `description` and `keywords` so the LLM knows all options. Insert this into the existing `system_prompt` string before the RULES section.

3. **Add layout selection rules to system prompt:**
   ```
   LAYOUT SELECTION RULES:
   - If the user mentions a specific layout by name or description, choose the matching preset.
   - If the user specifies custom dimensions (e.g. "10 rack rows", "3m aisles"), set layout="custom"
     and populate layout_params with the exact values.
   - You can also use a preset as a base and override specific params via layout_params.
   - If no layout is implied, default to "standard_warehouse".
   - Match keywords: "cramped/tight/dense" → narrow_aisle, "open/spacious" → open_floor,
     "loading/truck/shipping" → loading_dock, "maintenance/repair" → maintenance_bay,
     "yard/outdoor/container" → storage_yard, "cold/freezer" → cold_storage,
     "cross-dock/transfer" → cross_dock.
   ```

4. **Add layout_params extraction rules:**
   ```
   LAYOUT PARAMS RULES:
   - rack_rows: number of rack rows (1-12). Default 5.
   - rack_cols: number of rack columns (1-3). Default 1.
   - aisle_width: distance between rack rows in meters (1.0-5.0). Default 2.0.
   - bounds_min/bounds_max: overall layout footprint in meters. Must fit within ±7m X, ±7m Y.
   - clutter_density: "low" (0-5 props), "medium" (6-12 props), "high" (13-20 props).
   - clutter_zones: optional list of area-specific clutter overrides.
     Each zone needs: area name, bounds_min, bounds_max, density, and types list.
     Types must be from: "box", "barrel", "cone", "pallet".
   - pallet_rows/pallet_cols: pallet staging grid size. Default 2x1.
   ```

**Conventions:**
- Read `layouts.json` relative to the project root, not CWD
- If `layouts.json` fails to load, fall back to hardcoded layout list (graceful degradation)
- Do NOT remove any existing prompt rules (camera, PPE, hazard zones, behaviors)

---

## Task 6.4: Procedural Layout Generator

**File:** `isaac_backend/layouts.py` (new)

### Structure:

```python
LAYOUTS = { ... }  # loaded from assets/layouts.json at module init

def generate_layout(layout_name: str, layout_params: dict | None, asset_library: dict, stage) -> tuple[tuple[float,float], tuple[float,float]]:
    """Generate a warehouse layout and return (bounds_min, bounds_max)."""
```

### Internal Functions (all private, use `_` prefix):

| Function | Purpose |
|----------|---------|
| `_resolve_params(layout_name, layout_params, layouts)` | Merge preset defaults with user overrides. Returns final params dict. |
| `_place(asset_id, x, y, z, rot_z, asset_library, stage, idx)` | Shared helper: creates USD reference, sets transform, applies semantics via `apply_usd_semantics`. Returns updated idx counter. |
| `_spawn_racks(params, asset_library, stage, idx)` | Procedural rack placement based on `rack_pattern`, `rack_rows`, `rack_cols`, `aisle_width`. |
| `_spawn_pallets(params, asset_library, stage, idx)` | Pallet staging based on `pallet_rows`, `pallet_cols`, positioned relative to rack layout. |
| `_spawn_clutter(params, asset_library, stage, idx)` | Scatter props based on `clutter_density` and optional `clutter_zones`. |
| `_count_clutter_for_density(density)` | Maps density string to prop count: low→5, medium→12, high→20. |

### Rack Pattern Algorithms:

| Pattern | Algorithm |
|---------|-----------|
| `rows` | `rack_rows` parallel lines along X axis, spaced by `aisle_width` along Y |
| `grid` | `rack_rows` × `rack_cols` grid, spaced by `aisle_width` in both axes |
| `L-shape` | Two perpendicular row groups: horizontal rows + vertical rows forming L |
| `perimeter` | Racks along the 4 edges of `bounds_min/max`, leaving center open |
| `clusters` | `rack_cols` groups of `rack_rows`, each cluster separated by 2× `aisle_width` |
| `none` | Skip rack spawning entirely |

### Clutter Zone Logic:

1. If `clutter_zones` is non-empty: spawn clutter per-zone using zone-specific bounds, density, and types
2. If `clutter_zones` is empty: scatter clutter uniformly across `bounds_min/max`
3. Each clutter prop gets a random position within its zone bounds and random Z rotation

### Return Value:

Returns `(bounds_min, bounds_max)` from the resolved params so `main.py` can use them for geofenced entity spawning.

**Conventions:**
- Use `apply_usd_semantics` from `isaac_backend.semantics` (NOT `apply_semantics` — was renamed)
- Use `omni.kit.commands.execute("CreateReferenceCommand", ...)` for USD references (same as `warehouse.py:28-34`)
- Use `UsdGeom.XformCommonAPI` for transforms (same as `warehouse.py:38-40`)
- Print `[INFO]` messages for spawned counts (e.g., `[INFO] Spawned 15 racks, 8 pallets, 12 clutter props.`)
- Use `random.uniform()` for all randomization; no hardcoded positions

---

## Task 6.5: Warehouse Dispatcher Refactor

**File:** `isaac_backend/warehouse.py`

Current state (line 16-73): Single `spawn_warehouse_layout(asset_library, stage)` with hardcoded rack positions, pallet staging, and clutter scatter.

### Changes:

1. Replace the entire function body with a dispatcher:
   ```python
   def spawn_warehouse_layout(scene_config: dict, asset_library: dict, stage):
       layout_name = scene_config.get("layout", "standard_warehouse")
       layout_params = scene_config.get("layout_params", None)
       bounds_min, bounds_max = generate_layout(layout_name, layout_params, asset_library, stage)
       return bounds_min, bounds_max
   ```

2. Keep `hide_driver_prims(stage)` unchanged (lines 76-85).

3. Update imports: replace the inline placement logic with `from isaac_backend.layouts import generate_layout`.

4. Remove the old `place()` closure and all hardcoded coordinate loops (lines 18-73).

**Conventions:**
- Function signature changes from `(asset_library, stage)` to `(scene_config, asset_library, stage)`
- Returns `(bounds_min, bounds_max)` tuple for downstream use
- `hide_driver_prims` signature unchanged

---

## Task 6.6: Main.py Integration

**File:** `isaac_backend/main.py`

Current state:
- Line 295: `spawn_warehouse_layout(asset_library, stage)` — old signature
- Line 324: `b_min, b_max = (-5, -2), (5, 2)` — hardcoded bounds for entity spawning

### Changes:

1. **Line 295:** Update `spawn_warehouse_layout` call to pass `scene_config` and capture bounds:
   ```python
   spawn_bounds_min, spawn_bounds_max = spawn_warehouse_layout(scene_config, asset_library, stage)
   ```

2. **Line 324:** Replace hardcoded bounds with the returned values:
   ```python
   b_min, b_max = spawn_bounds_min, spawn_bounds_max
   ```

3. **Add layout logging** after line 276 (after config load):
   ```python
   layout_name = scene_config.get("layout", "standard_warehouse")
   _progress(f"Layout: {layout_name}")
   ```

**Conventions:**
- Do NOT change SimulationApp boot order, import order, SDG settings, CocoWriter, camera trigger, teardown, or any existing logic beyond the 3 items above
- Bounds are tuples of floats — compatible with `get_geofenced_spawner` which expects `(float, float)` tuples

---

## Task 6.7: Module Exports

**File:** `isaac_backend/__init__.py`

Current state (8 lines): Exports from `config_loader`, `camera`, `lighting`, `semantics`, `spawner`, `warehouse`, `workers`, `animation`.

### Changes:

Add export for the new module:
```python
from isaac_backend.layouts import generate_layout
```

**Conventions:**
- `spawn_warehouse_layout` is still exported from `warehouse` (signature changed but import path unchanged)

---

## Task 6.8: Validation & Testing

### Manual Tests (run on RunPod):

1. **Default layout (backward compatibility):**
   ```bash
   ./run_pipeline.sh "spawn a forklift near a worker"
   ```
   Expected: Uses `standard_warehouse` defaults, identical behavior to before.

2. **Preset selection:**
   ```bash
   ./run_pipeline.sh "cramped warehouse with tight aisles, forklift and 2 workers"
   ```
   Expected: `narrow_aisle` layout, 7 rack rows, high clutter.

3. **Custom layout:**
   ```bash
   ./run_pipeline.sh "warehouse with 10 rack rows, 3m wide aisles, low clutter"
   ```
   Expected: `layout="custom"`, `layout_params` with `rack_rows=10`, `aisle_width=3.0`, `clutter_density="low"`.

4. **Preset with overrides:**
   ```bash
   ./run_pipeline.sh "loading dock layout but with high clutter everywhere"
   ```
   Expected: `layout="loading_dock"`, `layout_params.clutter_density="high"`.

5. **Multiple clutter zones:**
   ```bash
   ./run_pipeline.sh "warehouse with high clutter near the loading dock area and low clutter in the center"
   ```
   Expected: `layout_params.clutter_zones` contains 2 entries with different bounds and densities.

### Automated Checks:

1. `python3 -m py_compile llm_pipeline/schemas.py` — no syntax errors
2. `python3 -m py_compile isaac_backend/layouts.py` — no syntax errors
3. `python3 -m py_compile isaac_backend/warehouse.py` — no syntax errors
4. `python3 -m py_compile isaac_backend/main.py` — no syntax errors
5. Validate `assets/layouts.json` is valid JSON with all 8 presets

---

## Execution Order

| # | Task | File(s) | Dependencies |
|---|------|---------|-------------|
| 1 | 6.1: Layout metadata | `assets/layouts.json` | None |
| 2 | 6.2: Schema extension | `llm_pipeline/schemas.py` | 6.1 |
| 3 | 6.3: LLM prompt update | `llm_pipeline/generator.py` | 6.1, 6.2 |
| 4 | 6.4: Procedural generator | `isaac_backend/layouts.py` | 6.1 |
| 5 | 6.5: Warehouse dispatcher | `isaac_backend/warehouse.py` | 6.4 |
| 6 | 6.6: Main.py integration | `isaac_backend/main.py` | 6.5 |
| 7 | 6.7: Module exports | `isaac_backend/__init__.py` | 6.4, 6.5 |
| 8 | 6.8: Validation | All files | 6.1–6.7 |
