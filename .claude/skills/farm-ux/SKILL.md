---
name: farm-ux
description: Use when changing or reviewing any UI in Android Farm (frontend/index.html, frontend/js, frontend/css) — new screens, buttons, dialogs, fleet tiles, bulk actions, accounts. Rules for a phone-farm UI used by non-technical people at 40+ devices, plus the LaiXi feature-parity checklist.
---

# Android Farm — UI/UX rules

Users are ordinary people, not developers. Scale target: **40 phones** today, 100 later.
Design system: **graphite console** (redesign 2026-10-17), tokens in `frontend/design/tokens.css`, strings in `frontend/strings/ru.json` (`data-t`, `t()` — never a Russian literal in new code). Don't restyle — extend.
- Principle: calm normal, loud exceptions. Neutrals are near-neutral graphite (no violet/blue glow; alphas via color-mix of tokens, no raw rgba). Accent = Android green `--accent` (fills with dark `--accent-ink`). States share saturation/lightness: `--bad` coral, `--warn` amber, `--busy` sky blue. Never reintroduce violet or blue-tinted greys.
- Calm layer (2026-10-17, owner: «глаза разбегаются»): buttons are soft fills without borders; only inputs keep a border. `.primary` = one per panel (green fill). `.danger` = red text, border/fill only on hover or `data-armed`. Row actions in lists stay quiet (dim/transparent) until the row is hovered, focused or selected — keep their space, no height jumps. Section bars sit on `--bg` with `--line-soft` dividers; no glows/drop shadows on cards or nav. Hover = one token step of fill/border (`--panel2→--panel3`, `--line→--line-hover`), never shadows. Small icon squares (builder row actions, scheme ▶) are 30×30 like `.sm`, ripple disabled.
- Font: Golos Text, local in `frontend/fonts` (farm works offline — never link Google Fonts). Mono only for code/logs/diff.
- Only tokens: `--fs-1..5` (12/13/14/16/20 — nothing below 12px; operators are 40+), `--lh` 1.55 body line-height, `--r1/--r2/--r3/--pill`, colors incl. `--well`, `--glass`, `--line-hover`, `--bad-dim/--bad-line`. No raw px font sizes, no raw hex, no uppercase tracked labels.
- Fleet overview (`renderFleetStats`): filter pills in words + a named attention list («Phone 13 — батарея 9%»). No unlabeled colored cells — users didn't understand them. Tile state via `data-st` (err/busy) — top bar + border.
- Problems: kind filters + three-level cards (kind+title / detail / facts column). Runs: grouped by launch batch with progress (`runGroupsHtml`).
- Mass run safety: 2+ phones → «Сначала проверить на одном телефоне» (on by default, `RD_TRIALS` in rundialog.js; rest joins the same `batch` via `/api/run`), failed rows show «встал на шаге N: …» (`jobWhereStopped`), batch has «Перезапустить упавшие» → `openRunDialog({scenario, params, serials})`.
- Phone screen from the fleet = «Пульт» (`pult.js`, `.work.pult-on`): screen left full height, right panel with keys (incl. volume/rotate), apps, text (+ из буфера), file drop, screenshot/video, last runs; screen is live at once. Builder appears on «Записать сценарий»/edit/teach (`REC.builder`), «⊞» in the builder goes back. Text field, live keyboard and held bar are the SAME nodes moved into the pult (`PULT_MOVES`) — never duplicate them. (A bare view-only mode without this panel was rejected 2026-10-17.)
- Stuck runs: long loops in own scenarios call `ctx.on_track(package)`; off-track → guards → HELD `held_kind:'lost'` with main action «Показать, как быть» (teach detour, job resumes after save). Farm asking a human → title «(N) ждёт», beep, browser notification (`notify.js`).
- One run entry per screen: no «Запустить» repeated on every list row; no «…» in button labels.
- Formats/examples (`логин:пароль:прокси`) are never plain mono text: use `.fmt` chips (bulk.css) — fields as chips, `:` in accent, optional part in `--busy`.
- Words: «телефон» (not «устройство»), «запуск» (not «задача»/«прогон»). Copy is short: empty state = title + one line (+ button), tooltips one phrase.
- Builder blocks (`frontend/js/blocks.js`): `loop` ↻ / `chance` 🎲 / `until` 🔎 are header steps; steps inside carry `parent` (header id), contiguous after it, nesting ≤ 3 (`BLOCK_DEPTH_MAX`). Span is computed on payload, restored by `recBlocksFromSpan`. Moves go through `blockPlace`; a header moves its whole block (`blockOf`). Colors: loop accent, chance warn, until busy, `if_seen` 👁 neutral (`--line-hover`; «+ иначе» adds the negated twin). Logic steps `break`/`finish`/`call` are added from «Шаг» → «Логика» (`recLogicPick`), not the toolbar.
- Click selectors: main (radio) + «или так» fallbacks (`step.or`, ≤3, custom variants allowed). Auto screen checks are opt-in («авто-проверки», off by default) — screens change. AI helpers use `GET /api/recorder/schema` + `docs/recipe-format.md`.
- Builder: step-by-step («Следующий шаг» after a passed single-step check) and «записать после этого шага» (`REC.insertAfter`).
- Empty states center via `.scroll:has(> .emptywrap)`; an id selector with `display: grid` on a list overrides it — add the id to that rule.
- All selects use the custom chevron in base.css; if a select rule sets `background:` shorthand, use `background-color` instead.
- Builder column uses a container query (`build`, ≤900px): secondary toolbar buttons become icon-only. Check every change at 1280 and 1728 for no wrapping/overflow.

## Before you build: ask these

1. **Does it already exist somewhere?** Grep `frontend/index.html` for the label/action. Two controls for one thing = remove one.
   Known merges: KPI cards *are* the fleet filter (no chips); header shows only active work/errors (counts live on KPI cards). «Подготовить» lives in «Действия» (bulkMenu); the selection bar has «Синхронно» (2+ free phones) and «Действия».
2. **Does it work at 40 devices?** Mentally put 40 tiles on a 1920×1080 screen at density S/M/L.
   - Anything per-device that polls → only for visible tiles (`thumbSeen` IntersectionObserver in `fleet.js`).
   - Anything per-device that fires at once → stagger (thumb first frame jitter, bulk `jitter`).
   - Selecting many: marquee, Cmd/Ctrl+click, Shift+click range, «Выбрать группу» — keep all working.
3. **Will a non-technical user understand the word?** No `adb`, `serial`, `shell`, `u2`, `pm clear` in visible text. Say what happens: «Переподключить телефоны», «Очистить данные приложения (как после переустановки)». Jargon is OK in `title` tooltips only if a plain word leads.
4. **Is it a frequent action?** Frequent → visible button. Rare (once a day) → dialog («Действия», «Управление»). Never a permanent bar for a rare action.

## Patterns already in the codebase — reuse them

| Need | Use |
|---|---|
| Run a scenario on the farm | **only** `openRunDialog({scenario?, mode?})` (rundialog.js) — preflight summary included. Never a new run button with its own code |
| Confirm destructive click | `armConfirm(btn, text)` (core.js) |
| Browser-stored preference | `store.get/set` (core.js) |
| Empty screen | `emptyBig({art, title, text, action})` (core.js) |
| Action on selected phones | `bulkAction({type, ...}, 'Название')` in `bulk.js` → `/api/bulk/action` |
| New device action type | add to `ACTIONS` in `backend/farm/api/screen.py` — bulk and sync get it free |
| Destructive action (reboot, clear, delete) | second click confirms (`data-armed`, 3–4 s timeout), no confirm() dialogs |
| Disabled button | `disableWithReason(btn, cond, 'why')` — never silent grey |
| Dialog | fill `mTitle`/`mBody`/`mActs`, call `openModal()` |
| Per-viewer preference (density, phrases, jitter) | `localStorage` wrapped in try/catch |
| Farm data (accounts, groups) | server JSON file next to `devices.json`, gitignored if it holds secrets |
| Scenario needs login | `ctx.account("vk"|"inst"|"tiktok"|"tg")` — never hardcode credentials |

Platforms are fixed: `vk`, `inst`, `tiktok`, `tg` (`backend/farm/accounts.py:PLATFORMS`).

## Anti-detection is a UX requirement

Simultaneous identical actions on many phones = ban. Default ON: jitter modes off / 0.2–1 s (default) / 0.5–3 s. Delay is counted from the click (due time), never after the previous action — lag must not accumulate. Per-device ordered queue (`backend/farm/api/bulk.py`); sync warms u2 connections via `/api/bulk/warm`. Never ask users for package names — use `/api/bulk/packages` + `recApp()`. Any new mass action must go through it, not loop requests from the browser.

## Builder (конструктор) rules

- Step labels come from `recLabel()` (recorder.js) — human words: «Нажать «Закрыть»», «Очистить данные «VK»», place on screen instead of coordinates. Never show class names (View, LinearLayout), resource ids raw, or `shell …`.
- Every step must be testable alone: ▶ on scheme card / list row → `recRunStep(i)` → `/api/run` with `stop_step`.
- Toolbar row 1 = flow (Запись → Проверить → Сохранить). Row 2 = editing tools. Canvas controls (zoom) live on the canvas. Each row must fit 1280px without wrapping.
- Input steps can take login/password/phone from the phone's account (`args.account` + `args.field` → `ctx.account(...)[field]`). Offer it instead of hardcoded credentials.
- Builder needs a phone: use `pickPhone(title, then)` (devices.js), never a disabled button.
- Re-render the scheme when it becomes visible (`recSetView`) — widths computed while hidden are wrong.

## Safety rules (from the fresh audit)

- Farm-wide actions (adb restart, cancel all) need `armConfirm` + say how many runs break. Single-phone repair never restarts the farm.
- Bulk actions skip busy phones (`bulkTargets`); selection only takes online, visible phones (`selectable`).
- Sync mode broadcasts only gestures/text/keys (`SYNC_TYPES`) and stops on phone change.
- Any submit button that starts work disables itself until the request returns.
- Esc in a modal closes only the modal (`stopImmediatePropagation`).
- `/api/accounts` never returns passwords; use `/api/accounts/{id}/password` on explicit «показать».
- Pollers re-render only on change (`setHTML`, signature compare); UI state like open groups must survive a poll.

## Copy

Russian, lowercase toasts, short. Toast says result + count: «Установка: готово на 38, 2 с ошибкой — <первая ошибка>».

## Navigation

Four sections: Ферма · Сценарии · Запуски (tabs «Все запуски» / «Проблемы») · Аккаунты. Don't add a fifth top-level item; nest instead.

## Verify (cheaply — user asked to save tokens)

- `node --check` on changed JS; `.venv/bin/python -c "import farm.api"` for Python.
- Browser check **once** at the end, not after every edit. No devices? Stub `fetch('/api/devices')` with fake list via `javascript_tool`, hard-reload (`cmd+shift+r`) first — static files are cached.
- Watch for global CSS leaks: class names like `.runbar`, `.bar`, `.chip` are reused across views; scope view-specific rules by id.
- Run pytest once before reporting, not per change.
- **Never clear the user's localStorage in the browser** (recorder drafts `farm.recorder.draft.*` live there). Remove only keys you created, by exact name.

## LaiXi parity checklist

Done: preflight before run (accounts/busy/offline), runs filtered by launch batch, mirroring, sync control (+jitter), bulk APK/file/reboot/text/open/clear data, groups + scenario per group, quick phrases, density S/M/L, accounts manager. Schedules «смены» (per-phone random slots in a window, Запуски → Расписание), device tags (filter, bulk, run by tag), bulk screenshots, screen off, jobs CSV export. Phone pult (volume, rotate, full-size screenshot, screen video, clipboard paste), drag-and-drop APK/file onto screen or tiles, «farm waits» notifications, stuck-run watchdog with teach-and-continue.
Removed 2026-10-17: ready-made warm-up templates (blind taps, untested on real phones — owner records own scenarios).
Not planned: multi-computer remote control, chat/inbox management.
When adding a competitor feature, write it into this list.
