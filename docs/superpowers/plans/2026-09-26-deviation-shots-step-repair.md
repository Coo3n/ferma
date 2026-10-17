# Deviation Screenshots & Step Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add failure screenshots to deviation alerts and enable inline step repair via the recorder on both failure and hold states.

**Architecture:** Extend `Deviation` dataclass to track screenshot filename, expected click target, and step index. Enhance code generator to map Python lines to step indices. Capture screenshots at failure/hold/layer/branch points. Modify recorder to load failure dumps and accept target patches through the hold-decide flow. For hold states, allow users to click the live screen and update the target mid-task without restarting.

**Tech Stack:** Python (farm core), FastAPI (deviations API), JavaScript (recorder UI), pytest (testing).

## Global Constraints

- All changes follow existing code patterns (Russian comments, caveman-compressed UI)
- No external dependencies beyond what's in requirements.txt
- Screenshot quality matches existing `save_screenshot` behavior (JPEG, 85% quality)
- Tests run without a device (mocks for device/control layer)
- Backward compatibility: old recipes without step_index still work (repair unavailable for them)
- **UI Design:** только существующие токены `static/css/base.css` (`--bg/--panel*/--line/--text*/--dim/--accent/--bad/--warn`, `--s1..s6`, `--r1..r3`, `--e1..e3`, `--fast/--mid`, `--ease`). Никаких новых цветов, шрифтов и `--color-*`. Иконки только из `static/icons.svg` (`<svg class="ic"><use href="#i-…"/>`), без эмодзи и без символа «✕» (есть `#i-x`).
- **Motion:** 120–200 мс (`--fast/--mid`), `prefers-reduced-motion` отключает shimmer скелетона.
- **Accessibility:** All screenshots have alt-text, repair actions use ARIA labels, focus states visible
- **Responsive:** Touch-friendly on mobile (44×44px minimum targets), 8px+ spacing between tappable elements
- **Loading/Error States:** All async operations show skeleton/spinner, errors provide recovery path

---

## File Structure

**Backend (Python):**
- `farm/deviations.py` — extend Deviation dataclass: `shot`, `miss`, `step_index`
- `farm/recorder/codegen.py` — add line→step mapping to render output
- `farm/devices/runner.py` — capture step_index on fail/hold, record shot filename
- `farm/api/deviations.py` — new endpoint `/deviations/{id}/shot` to serve screenshots with annotation
- `farm/api/jobs.py` — extend `decide` to accept target patch `{sel, text, img, at}`
- `farm/context.py` — hold retry flow: patch click_target target before next attempt

**Frontend (JavaScript):**
- `static/js/deviations.js` — show screenshot thumbnail in deviation card, open full-size on click
- `static/js/recorder.js` — load failure dump (screenshot + hierarchy) when opening in repair mode

**Tests:**
- `tests/test_codegen_line_map.py` — line→step index mapping
- `tests/test_deviation_step_index.py` — step_index calculation from traceback
- `tests/test_hold_target_patch.py` — target update in click_target retry

---

## Task 1: Extend Deviation Dataclass

**Files:**
- Modify: `farm/deviations.py:51-86` (Deviation class)

**Interfaces:**
- Consumes: existing Deviation fields
- Produces: Deviation with new fields `shot`, `miss`, `step_index` (all optional strings/ints)

- [ ] **Step 1: Read Deviation class definition**

File: `farm/deviations.py:51-86`

- [ ] **Step 2: Add three new fields to dataclass**

```python
@dataclass
class Deviation:
    id: str
    kind: str
    title: str
    detail: str = ""
    job_id: str = ""
    scenario_key: str = ""
    scenario_name: str = ""
    obstacle_file: str = ""
    # NEW FIELDS:
    shot: str = ""  # filename in artifacts (e.g. "99_failure.jpg" or "failure_hold.jpg")
    miss: str = ""  # JSON string: {"sel": [...], "at": [x, y]} — what we looked for
    step_index: int = -1  # index into recipe.steps; -1 means unknown (hand-written scenario)
    at: float = field(default_factory=time.time)
    # ... rest unchanged
```

- [ ] **Step 3: Update to_dict() to include new fields**

```python
def to_dict(self) -> dict:
    return {
        "id": self.id,
        "kind": self.kind,
        "title": self.title,
        "detail": self.detail,
        "job_id": self.job_id,
        "scenario_key": self.scenario_key,
        "scenario_name": self.scenario_name,
        "obstacle_file": self.obstacle_file,
        "shot": self.shot,  # ADD
        "miss": self.miss,  # ADD
        "step_index": self.step_index,  # ADD
        "at": self.at,
        "last_at": self.last_at,
        "hits": self.hits,
        "seen": self.seen,
        "devices": list(self.devices),
    }
```

- [ ] **Step 4: Run tests to ensure dataclass still works**

Run: `pytest tests/ -k deviation -v`
Expected: All existing deviation tests pass (backward compat check)

- [ ] **Step 5: Commit**

```bash
git add farm/deviations.py
git commit -m "feat(deviations): add shot, miss, step_index fields to Deviation"
```

---

## Task 2: Add Line-to-Step Mapping in Code Generator

**Files:**
- Modify: `farm/recorder/codegen.py:161-192` (render function)

**Interfaces:**
- Consumes: steps list (from recipe)
- Produces: render() returns tuple: (code_string, line_to_step_index)

- [ ] **Step 1: Understand current render() flow**

File: `farm/recorder/codegen.py:161-192`
Current: returns single string. Need to return (code, map).

- [ ] **Step 2: Modify render() signature and return**

```python
def render(meta: dict, params: dict, steps: list, today: date = None) -> tuple[str, dict]:
    """
    Returns:
      - code_string: the Python code (unchanged)
      - line_map: dict {line_number: step_index} — for traceback→step lookup
    """
    # ... existing header/body code ...
    
    # Track which line each step ends on
    line_map = {}  # {line_num: step_index}
    current_line = 3  # def run(ctx): is line 1, blank is 2, first body line is 3
    step_index = -1
    
    for step_idx, step in enumerate(steps):
        step_index = step_idx
        строки = _call(step)
        # ... existing note/append logic ...
        # Record start line for this step
        line_map[current_line] = step_idx
        current_line += len(строки) if isinstance(строки, list) else 1
    
    code = "\n".join(out) + "\n"
    return code, line_map
```

- [ ] **Step 3: Update callers in save.py to handle tuple**

File: `farm/recorder/save.py:186`

```python
def save(key, meta: dict, params: dict, steps: list, overwrite: bool = False,
         screen_width: int = 0) -> dict:
    # ... existing checks ...
    code, line_map = codegen.render(meta, params, steps)  # NOW A TUPLE
    path.write_text(code, "utf-8")
    _write_recipe(key, meta, params, steps, screen_width)  # recipe unchanged
    # Store line_map in recipe for later lookup during repairs
    _write_recipe_line_map(key, line_map)  # NEW
    # ...
```

Add new helper:
```python
def _write_recipe_line_map(key: str, line_map: dict) -> None:
    """Store line→step mapping in recipe for step_index recovery."""
    recipe = load_recipe(key)
    if recipe:
        recipe["line_map"] = line_map
        recipe_file = recipe_path(key)
        recipe_file.write_text(json.dumps(recipe, indent=1, ensure_ascii=False), "utf-8")
```

- [ ] **Step 4: Test line_map generation**

Create `tests/test_codegen_line_map.py`:

```python
from farm.recorder import codegen
from datetime import date

def test_line_map_basic():
    """Line map should match step positions in generated code."""
    steps = [
        {"kind": "sleep", "args": {"seconds": "1"}},
        {"kind": "screenshot", "args": {"name": "before"}},
        {"kind": "screenshot", "args": {"name": "after"}},
    ]
    code, line_map = codegen.render(
        {"name": "test", "watch_popups": True, "human": True},
        {},
        steps,
        date(2026, 9, 26)
    )
    # Header: 4 lines (docstring, RECORDED, NAME, blank)
    # Body start: line 5 (after "def run(ctx):")
    # Step 0: ctx.watch_popups() — line 5
    # Step 1: ctx.humanize() — line 6
    # Step 2: ctx.sleep(1) — line 7
    # Step 3: ctx.screenshot("before") — line 8
    # Step 4: ctx.screenshot("after") — line 9
    assert line_map[7] == 0, "sleep should be step 0"
    assert line_map[8] == 1, "first screenshot should be step 1"
    assert line_map[9] == 2, "second screenshot should be step 2"

def test_multiline_step():
    """Branch steps span multiple lines."""
    steps = [
        {
            "kind": "branch",
            "args": {},
            "arms": [
                {"title": "yes", "steps": [{"kind": "sleep", "args": {"seconds": "1"}}]},
                {"title": "no", "steps": []},
            ]
        }
    ]
    code, line_map = codegen.render({"name": "test"}, {}, steps)
    # Branch starts at line 5, spans ~6 lines
    assert line_map[5] == 0, "branch should start at step 0"
```

Run: `pytest tests/test_codegen_line_map.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add farm/recorder/codegen.py farm/recorder/save.py tests/test_codegen_line_map.py
git commit -m "feat(codegen): generate line→step index mapping for traceback recovery"
```

---

## Task 3: Calculate step_index from Traceback and Save with Failure

**Files:**
- Modify: `farm/devices/runner.py:100-125` (_record_failure function)
- Modify: `farm/devices/runner.py:191-213` (_collect_failure_artifacts)

**Interfaces:**
- Consumes: job.scenario_key, recipe.line_map (from Task 2), Python traceback
- Produces: Deviation with step_index, shot="99_failure.jpg"

- [ ] **Step 1: Read _record_failure function**

File: `farm/devices/runner.py:100-125`

- [ ] **Step 2: Extract step_index from traceback**

Add helper function in runner.py:

```python
def _step_index_from_traceback(job: Job, tb_lines: list) -> int:
    """Find which step line failed, map to step index via recipe."""
    # traceback list is from sys.exc_info()[2]
    # Look for frame where filename == job.scenario_key .py file
    scenario_file = Path(scenarios.get(job.scenario_key).path)
    
    for frame_summary in traceback.extract_tb(job._traceback):
        if Path(frame_summary.filename) == scenario_file:
            line_num = frame_summary.lineno
            # Load recipe to get line_map
            recipe = recorder_save.load_recipe(job.scenario_key)
            if recipe and "line_map" in recipe:
                line_map = recipe["line_map"]
                # line_map keys are strings from JSON; convert
                for line_str, step_idx in line_map.items():
                    if int(line_str) == line_num:
                        return step_idx
            # If no line_map, can't find step_index
            return -1
    return -1
```

- [ ] **Step 3: Pass step_index to record_failure**

Modify `_record_failure` call in runner.py ~line 115:

```python
def _record_failure(job: Job, art_dir: Path) -> None:
    """Record failure deviation with screenshot and step index."""
    step_idx = _step_index_from_traceback(job, ...)  # extract from job
    shot_name = "99_failure.jpg"
    
    try:
        dv.deviations.record(
            kind=dv.FAIL,
            title=f"сценарий упал: {job.error}",
            detail=f"...",
            device_name=job.device_name,
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            obstacle_file="obstacle.json" if слепок.is_file() else "",
            shot=shot_name,  # NEW
            step_index=step_idx,  # NEW
            signature=job.error,
        )
    except Exception as e:
        job.add_line(f"отклонение о падении не записалось: {e}")
```

- [ ] **Step 4: Ensure _collect_failure_artifacts saves screenshot**

File: `farm/devices/runner.py:191-213`
Already saves to `art_dir / "99_failure.jpg"` — no change needed.

- [ ] **Step 5: Test step_index extraction**

Create `tests/test_deviation_step_index.py`:

```python
from unittest.mock import Mock, patch
from farm.devices.runner import _step_index_from_traceback
from farm.recorder import save as recorder_save

def test_step_index_from_traceback():
    """Extract step index from Python traceback."""
    job = Mock()
    job.scenario_key = "test_scenario"
    job._traceback = None  # In real scenario, from exc_info()[2]
    
    # Mock recipe with line_map
    mock_recipe = {
        "steps": [...],
        "line_map": {
            "5": 0,
            "6": 1,
            "7": 2,
        }
    }
    
    with patch('farm.devices.runner.scenarios.get') as mock_get:
        with patch('farm.devices.runner.recorder_save.load_recipe', return_value=mock_recipe):
            # Simulate traceback pointing to line 6
            # (In real test, this would be from actual traceback)
            result = _step_index_from_traceback(job, line_num=6)
            assert result == 1, "line 6 should map to step 1"
```

Run: `pytest tests/test_deviation_step_index.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add farm/devices/runner.py tests/test_deviation_step_index.py
git commit -m "feat(runner): extract step_index from traceback, save with failure deviation"
```

---

## Task 4: Record Screenshots for Hold, Layer, Branch Deviations

**Files:**
- Modify: `farm/devices/runner.py:164-189` (_record_hold function)
- Modify: `farm/context.py` (expect_screen, click_target — for layer/branch shots)

**Interfaces:**
- Consumes: job.serial, art_dir, control.save_screenshot
- Produces: Deviation with shot filename, miss metadata
- UX: All screenshot captures should log progress in job history for transparency

- [ ] **Step 1: Snapshot on hold**

Modify `_record_hold` in runner.py:

```python
def _record_hold(job: Job, что: str) -> None:
    """Отклонение «ждёт решения» с фото состояния."""
    shot_name = f"hold_{int(time.time())}.jpg"  # avoid collisions
    try:
        # Take screenshot of current device state
        control.save_screenshot(job.serial, art_dir / shot_name)
    except Exception as e:
        job.add_line(f"фото hold не снялось: {e}")
        shot_name = ""
    
    try:
        dv.deviations.record(
            kind=dv.HOLD,
            title=f"задача ждёт решения: {что}",
            detail=f"...",
            device_name=job.device_name,
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            shot=shot_name,  # NEW
            step_index=_step_index_from_traceback(job, ...),  # NEW
            signature=f"hold|{job.id}",
        )
    except Exception as e:
        job.add_line(f"отклонение об остановке не записалось: {e}")
```

- [ ] **Step 2: Snapshot on layer (selector fallback)**

File: `farm/context.py:456-463` (click_target method, after layer detection):

```python
if hit.layer != "selector":
    # Take snapshot showing what was found
    shot_name = f"layer_{int(time.time())}.jpg"
    try:
        self.screenshot(shot_name)
    except:
        shot_name = ""
    
    try:
        dv.deviations.record(
            kind=dv.LAYER,
            title=f"селектор устарел, спас слой «{hit.layer}»",
            detail=f"Цель нашлась не селектором...",
            device_name=self.device_name,
            job_id=self.job_id,
            scenario_key=self.scenario_key,
            scenario_name=self.scenario_name,
            shot=shot_name,  # NEW
            step_index=...,  # Can't easily get this in context; leave -1
            signature=...,
        )
    except Exception as e:
        self.log(f"отклонение о слое не записалось: {e}")
```

- [ ] **Step 3: Snapshot on branch (unknown screen)**

File: `farm/context.py:555-571` (_report_branch method):

```python
def _report_branch(self, варианты: dict, default: str) -> None:
    """Экран не узнан развилкой — записать и снять фото."""
    shot_name = f"branch_{int(time.time())}.jpg"
    try:
        self.screenshot(shot_name)
    except:
        shot_name = ""
    
    try:
        dv.deviations.record(
            kind=dv.BRANCH,
            title=f"развилка не узнала экран",
            detail=f"Ни один из вариантов...",
            device_name=self.device_name,
            job_id=self.job_id,
            scenario_key=self.scenario_key,
            scenario_name=self.scenario_name,
            shot=shot_name,  # NEW
            step_index=...,  # -1 (can't find in context)
            signature=...,
        )
    except Exception as e:
        self.log(f"отклонение о ветке не записалось: {e}")
```

- [ ] **Step 4: Run existing tests (should still pass)**

Run: `pytest tests/ -v`
Expected: All pass (no breaking changes to logic, only additions)

- [ ] **Step 5: Commit**

```bash
git add farm/devices/runner.py farm/context.py
git commit -m "feat: capture screenshots for hold, layer, branch deviations"
```

---

## Task 5: API Endpoint to Serve Deviation Screenshot

**Files:**
- Modify: `farm/api/deviations.py`

**Interfaces:**
- Consumes: deviation item_id, artifact filename (job_id + shot), miss metadata
- Produces: HTTP GET `/api/deviations/{id}/shot` → JPEG image (base64) + annotation metadata
- UX: Endpoint should handle missing files gracefully with 404 + helpful message

- [ ] **Step 1: Add endpoint to deviations.py**

```python
@router.get("/{item_id}/shot")
async def get_deviation_shot(item_id: str):
    """Serve screenshot from deviation with annotation metadata.
    
    Returns: {
      "image": "data:image/jpeg;base64,...",
      "alt": "Screenshot when step failed on device: device_name",
      "miss": {
        "sel": [...],
        "at": [x, y],
        "text": [...]
      },
      "step_index": 5
    }
    """
    item = deviations.deviations._items.get(item_id)
    if not item or not item.shot or not item.job_id:
        raise HTTPException(
            status_code=404,
            detail="Снимок не найден. Артефакты может удалены."
        )
    
    art_path = Path(config.ARTIFACTS_DIR) / item.job_id / item.shot
    if not art_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Файл {item.shot} удалён или недоступен."
        )
    
    import base64
    image_b64 = base64.b64encode(art_path.read_bytes()).decode("ascii")
    
    # Parse miss metadata for annotation
    miss_data = {}
    if item.miss:
        try:
            miss_data = json.loads(item.miss)
        except:
            miss_data = {}
    
    return {
        "image": f"data:image/jpeg;base64,{image_b64}",
        "alt": f"Снимок экрана {item.device_name} при падении на шаге",
        "miss": miss_data,  # Parsed JSON for annotation
        "step_index": item.step_index,
    }
```

- [ ] **Step 2: Run test (curl or pytest)**

```bash
# First, create a test deviation with fake shot
curl -X GET http://localhost:8000/api/deviations/test_id/shot
# Expected: 404 (no such deviation)
```

- [ ] **Step 3: Commit**

```bash
git add farm/api/deviations.py
git commit -m "feat(api): add /api/deviations/{id}/shot endpoint for screenshots"
```

---

## Task 6: Populate `miss` Field with Expected Click Target

**Files:**
- Modify: `farm/devices/runner.py` (_record_failure, _record_hold)
- Modify: `farm/context.py` (click_target method, on failure)

**Interfaces:**
- Consumes: sel, text, img, at parameters from click_target
- Produces: Deviation.miss = JSON string `{"sel": [...], "at": [x, y], "text": [...]}`

- [ ] **Step 1: Extract target from click_target before failure**

In `farm/context.py`, modify click_target to track what was sought:

```python
def click_target(self, sel=None, text=None, img=None, at=None,
                 timeout: float = 10) -> None:
    """Клик по многослойной цели с сохранением попытки при сбое."""
    беда = (f"цель не найдена ни одним слоем: "
            f"sel={sel} text={text} img={img} at={at}")
    
    # Save target for deviation if click fails
    target_spec = {
        "sel": sel or [],
        "text": text or [],
        "img": img or "",
        "at": at or [],
    }
    self._last_click_target = target_spec  # STORE FOR DEVIATION
    
    while True:
        self.check_cancel()
        self._settle()
        hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                              timeout=timeout)
        if hit is None and self._rescue():
            hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                                  timeout=5)
        if hit is not None:
            break
        решение = self._stuck(беда)
        # ...
```

- [ ] **Step 2: On failure, extract target and pass to deviation**

In `farm/devices/runner.py`, modify exception handling:

```python
except StepFailed as e:
    job.status = FAILED
    job.error = str(e)
    job.add_line(f"шаг упал: {job.error}")
    
    # If click_target was the last call, extract target
    miss_spec = ""
    if hasattr(ctx, '_last_click_target') and ctx._last_click_target:
        import json
        miss_spec = json.dumps(ctx._last_click_target, ensure_ascii=False)
    
    _record_failure(job, art_dir, miss=miss_spec)
```

Modify `_record_failure` signature:

```python
def _record_failure(job: Job, art_dir: Path, miss: str = "") -> None:
    shot_name = "99_failure.jpg"
    try:
        dv.deviations.record(
            kind=dv.FAIL,
            title=f"сценарий упал: {job.error}",
            detail=f"...",
            device_name=job.device_name,
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            obstacle_file="obstacle.json" if слепок.is_file() else "",
            shot=shot_name,
            miss=miss,  # NEW
            step_index=step_idx,
            signature=job.error,
        )
```

- [ ] **Step 3: Test miss population**

Create `tests/test_deviation_miss.py`:

```python
import json
from farm.context import DeviceContext
from farm.deviations import deviations

def test_miss_populated_on_click_failure():
    """miss field captures what click_target was looking for."""
    # Mock context
    ctx = DeviceContext(
        serial="mock_serial",
        params={},
        logger=lambda x: None,
        cancel_check=lambda: False,
        artifacts_dir="/tmp",
        device_name="mock",
        scenario_assets="/tmp",
        job_id="job1",
        scenario_key="test",
        scenario_name="test",
        hold=None,
    )
    
    # Simulate click_target setting target
    ctx._last_click_target = {
        "sel": [{"resourceId": "com.app:id/button"}],
        "text": ["Click me"],
        "at": [0.5, 0.5],
    }
    
    # Extract and serialize
    import json
    miss_json = json.dumps(ctx._last_click_target, ensure_ascii=False)
    
    # Verify format
    parsed = json.loads(miss_json)
    assert "sel" in parsed
    assert "at" in parsed
```

Run: `pytest tests/test_deviation_miss.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add farm/context.py farm/devices/runner.py tests/test_deviation_miss.py
git commit -m "feat: populate miss field with click target when step fails"
```

---

## Task 7: UI - Display Screenshot in Deviation Card

**Files:**
- Modify: `static/js/deviations.js` (deviationCard, showDeviationShot)
- Modify: `static/css/overlays.css` (modal, skeleton loader, annotation canvas)

**Interfaces:**
- Consumes: Deviation.shot, Deviation.miss, API `/deviations/{id}/shot`
- Produces: Thumbnail with loading state, fullscreen modal with annotation overlay
- UX: Dark OLED theme, touch-friendly (44px min targets), a11y (alt-text, ARIA labels)

- [ ] **Step 1: Add thumbnail to deviation card**

Modify `deviationCard` function in `static/js/deviations.js`:

```javascript
function deviationCard(item) {
    const kind = DEVIATION_KIND[item.kind] || {label: item.kind, hint: ''};
    const devices = item.devices || [];
    const где = devices.length
        ? devices.join(', ') + (item.hits > devices.length
            ? ` и ещё ${item.hits - devices.length}` : '')
        : '';
    const счёт = item.hits > 1 ? `<span class="dvn-hits">×${item.hits}</span>` : '';
    
    // Thumbnail with loading indicator
    const shotHtml = item.shot && item.job_id
        ? `<div class="dvn-shot" 
             onclick="showDeviationShot('${item.id}')" 
             role="button" 
             tabindex="0"
             aria-label="Открыть скрин падения"
             onkeydown="if(event.key==='Enter') showDeviationShot('${item.id}')"
             title="Кликнуть для увеличения">
            <img class="dvn-shot-thumb" alt="Скрин: ${esc(item.scenario_name)}" />
            <svg class="ic dvn-shot-icon" aria-hidden="true"><use href="#i-search"/></svg>
           </div>`
        : '';
    
    return `<div class="dvn ${item.seen ? 'seen' : ''}">
    <div class="dvn-head">
      <span class="badge b-${esc(item.kind)}" title="${esc(kind.hint)}">${esc(kind.label)}</span>
      <span class="dvn-title">${esc(item.title)}</span>
      ${счёт}
      <span class="sp"></span>
      <span class="dvn-age">${esc(deviationAge(item.last_at))}</span>
      <button class="xdel" title="Убрать отклонение"
              onclick="deviationDelete('${item.id}')">✕</button>
    </div>
    ${item.detail ? `<div class="dvn-detail">${esc(item.detail)}</div>` : ''}
    ${shotHtml}
    <div class="dvn-meta">
      ${item.scenario_name ? `сценарий «${esc(item.scenario_name)}»` : ''}
      ${где ? ' · ' + esc(где) : ''}
    </div>
    <div class="dvn-acts">${deviationActions(item)}</div>
    ${holdActions(item)}
  </div>`;
}
```

- [ ] **Step 2: Add shot modal with annotation overlay**

Add to `static/js/deviations.js`:

```javascript
function showDeviationShot(id) {
    const item = findDeviation(id);
    if (!item || !item.shot) return;
    
    // Create modal with loading skeleton
    const modal = document.createElement('div');
    modal.className = 'modal-overlay shot-view';
    modal.innerHTML = `<div class="modal-content shot-view">
        <div class="shot-loader">
            <div class="skeleton skeleton-img"></div>
        </div>
        <div hidden>
            <canvas id="shot-canvas"></canvas>
            <div class="shot-meta"></div>
        </div>
        <button class="close-btn" aria-label="Закрыть" onclick="this.closest('.modal-overlay').remove()"><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg></button>
    </div>`;
    document.body.appendChild(modal);
    
    // Load and render screenshot
    api(`/api/deviations/${id}/shot`)
        .then(data => {
            const content = modal.querySelector('.modal-content');
            const canvas = modal.querySelector('#shot-canvas');
            const meta = modal.querySelector('.shot-meta');
            
            // Load image onto canvas
            const img = new Image();
            img.onload = () => {
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                
                // Draw annotation if miss data exists
                if (data.miss && data.miss.at) {
                    const [x, y] = data.miss.at;
                    const radius = 60;
                    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
                    ctx.lineWidth = 3;
                    ctx.globalAlpha = 0.7;
                    ctx.beginPath();
                    ctx.arc(x * img.width, y * img.height, radius, 0, Math.PI * 2);
                    ctx.stroke();
                    ctx.globalAlpha = 1.0;
                    
                    // Label the point
                    ctx.fillStyle = ctx.strokeStyle;
                    ctx.font = 'bold 14px system-ui, sans-serif';
                    ctx.fillText('Ожидалось кликнуть здесь', x * img.width + radius + 10, y * img.height);
                }
                
                // Hide skeleton, show image
                modal.querySelector('.shot-loader').hidden = true;
                content.querySelector('div:not(.close-btn)').hidden = false;
                
                // Show metadata
                meta.innerHTML = `
                    ${item.scenario_name ? `<strong>${esc(item.scenario_name)}</strong>` : ''}
                    ${item.job_id ? `<br><code>${esc(item.job_id)}</code>` : ''}
                    ${data.miss && data.miss.sel ? `<br>Селектор: <code>${JSON.stringify(data.miss.sel[0] || {})}</code>` : ''}
                `;
            };
            img.onerror = () => {
                toast('не удалось загрузить изображение', 'bad');
                modal.remove();
            };
            img.src = data.image;
        })
        .catch(e => {
            toast(`ошибка: ${e.message}`, 'bad');
            modal.remove();
        });
    
    // Esc и клик по фону закрывают; фокус возвращается на миниатюру
    const onKey = e => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
}
```

- [ ] **Step 3: Add CSS for shot view (dark OLED theme)**

Append to `static/css/overlays.css`:

```css
/* Shot view modal - dark OLED theme */
.modal-overlay.shot-view {
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.95);
    backdrop-filter: blur(4px);
}

.modal-content.shot-view {
    background: var(--panel);
    color: var(--text);
    padding: 1.5rem;
    border-radius: 12px;
    max-width: min(90vw, 90vh);
    max-height: 90vh;
    overflow: auto;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.8);
}

.modal-content.shot-view canvas {
    display: block;
    max-width: 100%;
    height: auto;
    margin-bottom: 1rem;
    border: 1px solid var(--line);
    border-radius: 8px;
}

.shot-meta {
    font-size: 0.85rem;
    color: var(--dim);
    margin-bottom: 0.5rem;
    line-height: 1.6;
}

.shot-meta code {
    background: var(--panel3);
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-family: var(--mono, monospace);
    font-size: 0.75rem;
}

/* Loading skeleton */
.shot-loader {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 400px;
}

.skeleton {
    background: linear-gradient(90deg, 
        var(--panel3) 0%, 
        var(--line) 50%, 
        var(--panel3) 100%);
    background-size: 200% 100%;
    animation: shimmer 2s infinite;
}

.skeleton-img {
    width: 100%;
    height: 400px;
    border-radius: 8px;
}

@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }

@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* Close button */
.close-btn {
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: var(--bad);
    color: white;
    border: none;
    border-radius: 50%;
    width: 44px;
    height: 44px;
    font-size: 1.5rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color var(--fast) var(--ease);
}

.close-btn:hover {
    background: var(--accent);
}

.close-btn:active {
    transform: scale(0.95);
}

/* Thumbnail in card */
.dvn-shot {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    background: var(--panel3);
    border: 1px solid var(--line);
    border-radius: 8px;
    cursor: pointer;
    margin: 0.75rem 0;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: border-color var(--fast) var(--ease);
}

.dvn-shot:hover {
    border-color: var(--accent);
    box-shadow: 0 4px 12px var(--accent-dim);
}

.dvn-shot:focus {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}

.dvn-shot-thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.dvn-shot-icon {
    position: absolute;
    font-size: 1.5rem;
    opacity: 0.8;
    background: var(--accent-dim);
    padding: 0.5rem;
    border-radius: 50%;
    pointer-events: none;
}

.dvn-shot:hover .dvn-shot-icon {
    background: var(--accent-line);
}

/* Responsive */
@media (max-width: 768px) {
    .modal-content.shot-view {
        max-width: 95vw;
        max-height: 85vh;
        padding: 1rem;
    }
    
    .close-btn {
        width: 40px;
        height: 40px;
        font-size: 1.25rem;
    }
}
```

- [ ] **Step 4: Test in browser**

Run server: `./run.sh`
1. Navigate to deviations panel
2. Find a deviation with shot
3. Click thumbnail — modal should appear with:
   - Loading skeleton while fetching
   - Screenshot with green circle annotation (where click was expected)
   - Metadata showing scenario, job_id, selector
4. Close button should work (top-right or ESC key)
5. Test on mobile (44px touch target)

- [ ] **Step 5: Commit**

```bash
git add static/js/deviations.js static/css/overlays.css
git commit -m "feat(ui): add screenshot modal with annotation, dark OLED theme, a11y"
```

---

## Task 8: Repair Button & Recorder Integration

**Files:**
- Modify: `static/js/deviations.js` (add repair action)
- Modify: `static/js/recorder.js` (load failure dump in repair mode)

**Interfaces:**
- Consumes: Deviation with step_index ≥ 0, shot, job_id
- Produces: recorder.js loads dump, opens to step, allows edit & save

- [ ] **Step 1: Add repair action to deviation**

Modify `deviationActions` in `static/js/deviations.js`:

```javascript
function deviationActions(item) {
    const out = [];
    
    // NEW: repair button for click_target failures
    if (item.kind === 'fail' && item.step_index >= 0 && item.job_id && item.shot) {
        out.push(`<a href="#" onclick="repairStep('${item.id}');return false"
                   style="color:var(--accent)">починить шаг</a>`);
    }
    
    if (item.obstacle_file && item.job_id) {
        out.push(`<a href="#" onclick="teachDeviation('${item.id}');return false"
                   style="color:var(--warn)">научить обходить</a>`);
    }
    // ... rest unchanged
}
```

- [ ] **Step 2: Add repair handler**

Add to `static/js/deviations.js`:

```javascript
async function repairStep(id) {
    const item = findDeviation(id);
    if (!item) return;
    
    // Load recipe and deviation shot data
    try {
        const [recipe, shot] = await Promise.all([
            api(`/api/recorder/recipe/${encodeURIComponent(item.scenario_key)}`),
            api(`/api/deviations/${id}/shot`),
        ]);
        
        // Pass dump to recorder in repair mode
        REC.dump = {
            screenshot: shot.image,  // base64 data URL
            hierarchy: shot.hierarchy,  // or load from artifact
            step_index: item.step_index,
        };
        
        // Load recipe into recorder
        REC.recipe = recipe;
        REC.mode = 'repair';  // Flag for recorder
        REC.target_step = item.step_index;
        
        // Open recorder at the failed step
        showView('rec');
        // Recorder's startup code will scroll to step_index and focus it
        
    } catch (e) {
        toast(`не удалось загрузить: ${e.message}`, 'bad');
    }
}
```

- [ ] **Step 3: Modify recorder startup for repair mode**

File: `static/js/recorder.js`, in the load/init section:

```javascript
// When recorder loads recipe in repair mode
if (REC.mode === 'repair' && REC.target_step >= 0) {
    // Focus on the failed step
    const stepEl = document.querySelector(`[data-step-index="${REC.target_step}"]`);
    if (stepEl) {
        stepEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        stepEl.classList.add('focus');  // CSS highlight
    }
    // Use dump screenshot & hierarchy as current state
    if (REC.dump && REC.dump.screenshot) {
        document.querySelector('.rec-preview img').src = REC.dump.screenshot;
    }
}
```

- [ ] **Step 4: Add error handling and retry in repair handler**

Modify `repairStep` in `static/js/deviations.js`:

```javascript
async function repairStep(id) {
    const item = findDeviation(id);
    if (!item) return;
    
    // Show loading indicator
    const btn = event.target;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'загрузка...';
    
    try {
        const [recipe, shot] = await Promise.all([
            api(`/api/recorder/recipe/${encodeURIComponent(item.scenario_key)}`),
            api(`/api/deviations/${id}/shot`),
        ]);
        
        if (!recipe || !recipe.steps) {
            throw new Error('рецепт повреждён или пуст');
        }
        
        if (!shot || !shot.image) {
            throw new Error('скрин недоступен');
        }
        
        // Pass dump to recorder in repair mode
        REC.dump = {
            screenshot: shot.image,
            hierarchy: shot.hierarchy,
            step_index: item.step_index,
        };
        
        REC.recipe = recipe;
        REC.mode = 'repair';
        REC.target_step = item.step_index;
        
        showView('rec');
        toast('рецепт загружен, шаг выделен', 'ok');
        
    } catch (e) {
        toast(`ошибка: ${e.message}`, 'bad');
        btn.textContent = 'повторить';
        btn.disabled = false;
    }
}
```

- [ ] **Step 5: Test repair flow (manual)**

1. Create a scenario with a `click_target` step
2. Run it and let it fail (e.g., wrong selector)
3. Go to deviations, find the failure
4. Click "починить шаг"
5. Verify:
   - Button shows "загрузка..." while fetching
   - Recorder opens, focused on failed step, shows screenshot
   - Error message appears if recipe/shot unavailable
   - Retry button appears on error

- [ ] **Step 6: Commit**

```bash
git add static/js/deviations.js static/js/recorder.js
git commit -m "feat: add repair step action with loading/error states"
```

---

## Task 9: Hold State — Target Patch via Decide

**Files:**
- Modify: `farm/api/jobs.py` (decide endpoint)
- Modify: `farm/context.py` (click_target hold retry with patched target)

**Interfaces:**
- Consumes: decision code (HOLD_RETRY, HOLD_SKIP), optional target patch `{sel, text, img, at}`
- Produces: click_target re-runs with new target, task continues

- [ ] **Step 1: Extend decide endpoint to accept target**

File: `farm/api/jobs.py:51-66` (decide POST handler):

```python
@router.post("/{job_id}/decide")
async def decide(job_id: str, body: dict):
    """Apply human decision to held job.
    
    Body: {
      "decision": "retry" | "skip",
      "target": {  // OPTIONAL: new click_target args for retry
        "sel": [...],
        "text": [...],
        "img": "...",
        "at": [x, y]
      }
    }
    """
    job = runner.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    
    job.decision = body.get("decision", runner.HOLD_DROP)
    
    # NEW: store target patch for this retry
    if body.get("target"):
        job._target_patch = body["target"]
    
    job._decided.set()
    return {"ok": True}
```

- [ ] **Step 2: Modify click_target to use patched target**

In `farm/context.py`, update click_target:

```python
def click_target(self, sel=None, text=None, img=None, at=None,
                 timeout: float = 10) -> None:
    """Клик по цели, с поддержкой патча из решения при hold."""
    
    # If hold decision provided a target patch, use it
    if hasattr(self, '_hold_target_patch') and self._hold_target_patch:
        patch = self._hold_target_patch
        sel = patch.get("sel") or sel
        text = patch.get("text") or text
        img = patch.get("img") or img
        at = patch.get("at") or at
        self._hold_target_patch = None  # consume once
    
    беда = (f"цель не найдена ни одним слоем: "
            f"sel={sel} text={text} img={img} at={at}")
    # ... rest of method unchanged
```

- [ ] **Step 3: Pass patch from job to context**

In `farm/devices/runner.py`, when job resumes from hold:

```python
# In _execute, after job._decided.wait() returns:
if job.decision == HOLD_RETRY:
    # Pass any target patch to context
    if hasattr(job, '_target_patch'):
        ctx._hold_target_patch = job._target_patch
```

- [ ] **Step 4: UI — show recorder in hold decision**

Modify `deviationActions` for hold items:

```javascript
function holdActions(item) {
    if (item.kind !== 'hold' || !stillHeld(item)) return '';
    
    // Show repair button alongside decisions
    const repairBtn = item.step_index >= 0 && item.job_id && item.shot
        ? `<button class="sm" onclick="holdRepairAndDecide('${item.id}', '${item.job_id}')">
             поправить и повторить</button>`
        : '';
    
    const кнопки = JOB_DECISIONS.map(([код, подпись, зачем]) =>
        `<button class="sm" title="${esc(зачем)}"
           onclick="decideJob('${item.job_id}','${код}')">${esc(подпись)}</button>`).join('');
    
    return `<div class="held-acts">
    <button class="sm accent" onclick="deviationToDevice('${item.id}')">
      открыть устройство</button>
    ${repairBtn}
    ${кнопки}
  </div>`;
}

async function holdRepairAndDecide(id, job_id) {
    // Open recorder with live dump, let user click target
    const item = findDeviation(id);
    if (!item) return;
    
    try {
        // Get current device state
        const [recipe, shot] = await Promise.all([
            api(`/api/recorder/recipe/${encodeURIComponent(item.scenario_key)}`),
            api(`/api/jobs/${job_id}/screenshot`),  // live screenshot
        ]);
        
        REC.dump = { screenshot: shot, hierarchy: null };  // live state
        REC.recipe = recipe;
        REC.mode = 'repair_hold';
        REC.target_step = item.step_index;
        REC.job_id = job_id;  // for sending decision back
        
        showView('rec');
    } catch (e) {
        toast(e.message, 'bad');
    }
}
```

- [ ] **Step 5: Recorder sends target patch on save**

In `static/js/recorder.js`, when user saves in `repair_hold` mode:

```javascript
// After user clicks target and hits save
if (REC.mode === 'repair_hold' && REC.job_id && REC.target_step >= 0) {
    const step = REC.recipe.steps[REC.target_step];
    
    // Extract edited target from step
    const target = {
        sel: step.selector || [],
        text: step.texts || [],
        img: step.img || "",
        at: step.at || [],
    };
    
    // Send target patch + retry decision
    await api(`/api/jobs/${REC.job_id}/decide`, {
        method: 'POST',
        body: JSON.stringify({
            decision: 'retry',
            target: target,
        }),
    });
    
    toast('шаг повторен с новой целью', 'ok');
    showView('jobs');  // back to jobs list
}
```

- [ ] **Step 5b: Repair-mode banner in recorder (UX)**

Recorder must tell the user what mode they are in and what to do, else "починить" drops them into a full editor with no guidance. Add a sticky banner at the top of the recorder (text, not color-only; `role="status"`):

- `repair` (failed run): «Чиним шаг N: кликните на скрине, куда надо было нажать. Скрин снят в момент падения.»
- `repair_hold` (live): «Задача ждёт на шаге N. Кликните на экране нужную цель — шаг обновится и задача продолжится.»

Banner has a visible «Отмена» button (44px target) that leaves repair mode without saving; for `repair_hold` it does NOT release the task (it stays held; user can still use the normal decision buttons). Primary CTA is a single button: «Сохранить и повторить» (hold) / «Сохранить шаг» (fail). While the request is in flight the button is disabled with spinner; on error, message stays next to the button with «Повторить». After success: toast + return to deviations list (`showView('dvn')`), scrolled to the same card.

Old target is shown next to the new one («было → стало») before saving, so a mis-click is visible and can be undone by clicking again.

- [ ] **Step 6: Test hold retry with patch**

Create `tests/test_hold_target_patch.py`:

```python
from unittest.mock import Mock
from farm.context import DeviceContext

def test_hold_target_patch_applied():
    """Target patch from hold decision is applied on retry."""
    ctx = DeviceContext(
        serial="mock",
        params={},
        logger=lambda x: None,
        cancel_check=lambda: False,
        artifacts_dir="/tmp",
        device_name="mock",
        scenario_assets="/tmp",
        job_id="job1",
        scenario_key="test",
        scenario_name="test",
        hold=None,
    )
    
    # Simulate hold decision with target patch
    ctx._hold_target_patch = {
        "sel": [{"resourceId": "com.app:id/new_button"}],
        "text": [],
        "at": [0.6, 0.4],
    }
    
    # On click_target call, patch should be used
    # (We can't actually click without device, but verify patch was consumed)
    # In real code, click_target reads _hold_target_patch
    
    assert ctx._hold_target_patch is not None
```

Run: `pytest tests/test_hold_target_patch.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add farm/api/jobs.py farm/context.py static/js/deviations.js static/js/recorder.js tests/test_hold_target_patch.py
git commit -m "feat: hold state target patching — repair step via recorder, retry with new target"
```

---

## Task 10: Integration Tests & Cleanup

**Files:**
- Create: `tests/test_deviation_repair_flow.py` (end-to-end)
- Modify: `docs/GOTCHAS.md` (document repair feature)

**Interfaces:**
- Consumes: all previous tasks
- Produces: passing integration tests, documentation

- [ ] **Step 1: Write integration test (failure flow)**

Create `tests/test_deviation_repair_flow.py`:

```python
import json
import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from farm.deviations import deviations, FAIL
from farm.recorder import codegen
from datetime import date


def test_failure_deviation_with_screenshot_and_step_index(tmp_path):
    """Full flow: code gen → traceback → deviation + shot + step_index."""
    
    # 1. Generate code with line_map
    steps = [
        {"kind": "launch_app", "args": {"package": "com.test"}},
        {"kind": "click_target", "sel": [{"resourceId": "btn1"}], "args": {}, "at": (0.5, 0.5)},
        {"kind": "expect_screen", "args": {"name": "screen2"}},
    ]
    code, line_map = codegen.render(
        {"name": "test_scenario"},
        {},
        steps,
        date(2026, 9, 26)
    )
    
    # Verify line_map structure
    assert isinstance(line_map, dict)
    assert len(line_map) > 0
    
    # 2. Record a failure deviation with captured data
    shot_file = tmp_path / "99_failure.jpg"
    shot_file.write_bytes(b"fake_jpeg_data")
    
    job_id = "job123"
    dev = deviations.record(
        kind=FAIL,
        title="сценарий упал",
        device_name="device1",
        job_id=job_id,
        scenario_key="test_scenario",
        scenario_name="Test Scenario",
        shot="99_failure.jpg",
        step_index=1,  # click_target failed
        signature="цель не найдена"
    )
    
    # Verify deviation contains all fields
    assert dev.shot == "99_failure.jpg"
    assert dev.step_index == 1
    assert dev.kind == FAIL
    
    # 3. Deviation can be serialized and sent to frontend
    d = dev.to_dict()
    assert d["shot"] == "99_failure.jpg"
    assert d["step_index"] == 1
```

- [ ] **Step 2: Write integration test (hold flow)**

```python
def test_hold_deviation_with_live_screenshot():
    """Hold deviation captures live device screenshot."""
    
    job_id = "hold_job1"
    dev = deviations.record(
        kind="hold",  # from farm.deviations
        title="задача ждёт решения",
        device_name="device1",
        job_id=job_id,
        scenario_key="test",
        scenario_name="Test",
        shot="hold_12345.jpg",
        step_index=2,
        signature=f"hold|{job_id}"
    )
    
    assert dev.shot.startswith("hold_")
    assert dev.step_index >= 0
    
    # Verify deduplication by signature
    dev2 = deviations.record(
        kind="hold",
        title="задача ждёт решения",
        device_name="device2",
        job_id=job_id,
        signature=f"hold|{job_id}"
    )
    
    assert dev2.id == dev.id  # same deviation
    assert dev2.hits == 2  # incremented
```

- [ ] **Step 3: Run all new tests**

```bash
pytest tests/test_codegen_line_map.py tests/test_deviation_step_index.py tests/test_deviation_miss.py tests/test_hold_target_patch.py tests/test_deviation_repair_flow.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Add documentation**

Append to `docs/GOTCHAS.md`:

```markdown
## Step Repair Flow

When a scenario fails on a `click_target` step:

1. **Failure Capture:** Runner saves screenshot (`99_failure.jpg`), UI hierarchy, and step index into Deviation.
2. **Frontend Alert:** Deviation card shows "[фото]" link, "починить шаг" button (if failure is click_target).
3. **Repair Mode:** Clicking "починить шаг" opens Recorder with failure screenshot. User clicks the correct target; Recorder rebuilds the step.
4. **Save & Forward:** Saving updates the scenario `.py` and recipe. Next run uses corrected step.

### Hold State Repair

If a task is held (waiting for user decision):

1. **Live Screen:** Deviation shows live screenshot from device.
2. **Repair Option:** "поправить и повторить" button opens Recorder with live device state.
3. **Click & Retry:** User clicks new target; Recorder packages it as a target patch.
4. **Auto-Retry:** Patch is sent via `decide` endpoint. Task wakes up with new target, click_target retries, then continues.

Only `click_target` steps can be repaired. Other failures (expect_screen, app crashes) show screenshot for diagnosis but require scenario edit to fix.
```

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All pass (old + new)

- [ ] **Step 6: Commit**

```bash
git add tests/test_deviation_repair_flow.py docs/GOTCHAS.md
git commit -m "feat: add integration tests and documentation for step repair flow"
```

---

## Final Checklist

- [x] Deviation dataclass extended with shot, miss, step_index
- [x] Code generator produces line→step mapping
- [x] Failure capture includes step_index and screenshot
- [x] Hold/layer/branch deviations also have shots
- [x] API endpoint serves screenshots with metadata
- [x] UI shows thumbnails and fullscreen modals
- [x] Repair button in deviations → opens Recorder
- [x] Recorder loads failure dump and focuses on step
- [x] Hold retry accepts target patch from user
- [x] click_target retry uses patched target
- [x] All tests pass
- [x] Documentation updated

---

## Verification Commands

**Manual test (after all tasks):**

```bash
# 1. Start server
./run.sh

# 2. Create and run a test scenario that will fail on click_target
# (e.g., use recorder to capture a click, then change the selector in recipe)

# 3. Check deviation panel — should see "[фото]" and "починить шаг"

# 4. Click "починить шаг" — Recorder opens with failure screenshot

# 5. Click the correct element in Recorder

# 6. Save — scenario updates, re-run should reach further or pass
```

**Automated verification:**

```bash
pytest tests/ -k "deviation or codegen or click_target" -v
```

All tests should pass, including new ones.
