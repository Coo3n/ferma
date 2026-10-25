# Готовые сюжеты и галерея — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Шесть готовых сюжетов (лента TikTok, автолистание шортсов, Spotify, VK, Telegram, YouTube Shorts) и вкладка «Готовые» в разделе «Сценарии» с кнопкой «Добавить в мои».

**Architecture:** Чистая логика (`story.py`, `ui/structure.py`) отдельно от устройства; общий движок ленты `feed.py` берёт у сюжета только маленький класс `FeedUI` (как нажимать «лайк», «дальше»). Сюжеты лежат в `backend/scenarios/gallery/` и не попадают в «Мои», пока их не скопировали (`discover()` смотрит только `scenarios/*.py`). Галерея читает метаданные через `ast`, не выполняя файлы.

**Tech Stack:** Python 3.9+ (`from __future__ import annotations`, без `match`), FastAPI, pytest (функции роутера зовутся напрямую, TestClient не нужен), чистый JS без сборки, Node для JS-тестов.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-10-25-ready-stories-design.md`, часть 1.
- Python `>=3.9`: аннотации `X | None` только с `from __future__ import annotations`.
- Тексты интерфейса только в `frontend/strings/ru.json`, ключи вида `gallery.nazvanie`; `backend/tests/test_strings.py` должен проходить.
- Комментарии и сообщения пользователю на русском, простыми словами; стиль комментариев — «почему», как в `phrases.py` и `budget.py`.
- Чистые модули без adb, диска и FastAPI; случайное через параметр `rng`.
- Тесты не требуют телефона; запуск из `backend/`: `python -m pytest tests/<файл> -q`.
- Действия, меняющие аккаунт (лайк, избранное, подписка, комментарий), идут через `ctx.budget(...)`.
- Сюжеты ставятся с `GALLERY["verified"] = False`.
- Не коммитить чужие правки: в рабочем дереве есть незакоммиченные файлы владельца (`frontend/index.html`, `frontend/strings/ru.json`, `frontend/js/addstep.js`, `frontend/js/recorder.js`, `frontend/css/recorder.css`, `backend/tests/test_addstep_js.py`). Работа ведётся в отдельном git worktree от `main`; в коммит идёт только то, что создано или изменено задачей (`git add` по именам файлов).

---

## File Structure

| Файл | Ответственность |
|---|---|
| `backend/farm/story.py` (новый) | профили, `resolve_profile`, `validate`, `parse_lines`, `WordRotator`, `pick_actions`, `dwell_left`, `seek_plan`, `Tally` |
| `backend/farm/ui/structure.py` (новый) | поиск структурных элементов по дереву: колонка действий, нижняя панель, плитки, кнопка отправки |
| `backend/farm/feed.py` (новый) | `feed_params`, `FeedParams`, `from_params`, `FeedUI`, `run_feed`, `swipe_up` |
| `backend/farm/gallery.py` (новый) | список карточек и копирование в «Мои» |
| `backend/farm/api/gallery.py` (новый) | `GET /api/gallery`, `POST /api/gallery/{key}/add` |
| `backend/farm/api/__init__.py` | подключить роутер |
| `backend/farm/config.py` | `GALLERY_DIR` |
| `backend/scenarios/gallery/*.py` (6 новых) | сами сюжеты |
| `frontend/js/gallery.js`, `frontend/css/gallery.css` (новые) | вкладка «Готовые» |
| `frontend/js/scenarios.js` | поле `textarea` в параметрах |
| `frontend/index.html`, `frontend/js/app.js`, `frontend/strings/ru.json` | вкладка, представление, строки |
| `README.md`, `docs/guide.md`, `.claude/skills/farm-ux/SKILL.md` | документация |

---

### Task 1: `story.py` — логика сюжетов

**Files:**
- Create: `backend/farm/story.py`
- Test: `backend/tests/test_story.py`

**Interfaces:**
- Produces:
  - `ACTIONS = ("like", "favorite", "follow", "comment")`, `ACTION_WORDS: dict[str, str]`
  - `@dataclass(frozen=True) Profile(like, comment, favorite, follow: float; dwell, change_every: tuple)`
  - `PROFILES: dict[str, Profile]`, `PROFILE_LABELS: dict[str, str]` («Тихий»→`quiet`…), `DEFAULT_PROFILE_LABEL = "Обычный"`
  - `resolve_profile(name, overrides=None) -> Profile`
  - `validate(params, need_actions=True, allowed=ACTIONS) -> list[str]`
  - `parse_lines(text, limit=200) -> list[str]`
  - `class WordRotator(words, every=(3, 5), rng=None)`: `.tick() -> str | None`
  - `pick_actions(profile, rng=None, allowed=ACTIONS) -> list[str]`
  - `dwell_left(target, spent) -> float`
  - `seek_plan(total, lo, hi, rng=None) -> list[int]`
  - `class Tally`: `.add(key, n=1)`, `.counts: dict`, `.line() -> str`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_story.py`:

```python
"""Логика сюжетов: профили, проверка формы, слова, действия, сводка."""
import random

import pytest

from farm import story


def test_profile_by_label_and_key():
    assert story.resolve_profile("Тихий") == story.PROFILES["quiet"]
    assert story.resolve_profile("active") == story.PROFILES["active"]


def test_unknown_profile_falls_back_to_normal():
    assert story.resolve_profile("что-то") == story.PROFILES["normal"]
    assert story.resolve_profile(None) == story.PROFILES["normal"]


def test_overrides_win_over_profile():
    p = story.resolve_profile("Обычный", {"like": "55", "dwell_lo": 3, "dwell_hi": "9"})
    assert p.like == 55.0
    assert p.dwell == (3.0, 9.0)
    assert p.comment == story.PROFILES["normal"].comment


def test_empty_and_garbage_overrides_ignored():
    p = story.resolve_profile("Обычный", {"like": "", "comment": None, "follow": "abc", "favorite": True})
    assert p == story.PROFILES["normal"]


def test_override_lo_above_default_hi_pushes_hi_up():
    p = story.resolve_profile("Обычный", {"dwell_lo": 60})
    assert p.dwell[0] == 60.0 and p.dwell[1] >= 60.0


def test_validate_ok_for_defaults():
    assert story.validate({"profile": "Обычный", "views": 30}) == []


def test_validate_pause_order():
    errs = story.validate({"dwell_lo": 10, "dwell_hi": 5})
    assert any("Пауза" in e for e in errs)


def test_validate_rate_range_and_garbage():
    errs = story.validate({"like": 120, "comment": "много"})
    assert len(errs) == 2


def test_validate_views_range():
    assert story.validate({"views": 0})
    assert story.validate({"views": 5000})
    assert story.validate({"views": "12"}) == []


def test_validate_all_zero_rates_only_when_actions_needed():
    zero = {"profile": "Обычный", "like": 0, "comment": 0, "favorite": 0, "follow": 0}
    assert story.validate(zero)
    assert story.validate(zero, need_actions=False) == []


def test_validate_counts_only_allowed_actions():
    # лайк выключен, остальные включены, но разрешён только лайк — делать нечего
    params = {"profile": "Обычный", "like": 0}
    assert story.validate(params, allowed=("like",))
    assert story.validate(params) == []


def test_parse_lines_trims_dedups_and_limits():
    text = "  кошки \n\nсобаки\nкошки\r\n  \nптицы\nрыбы"
    assert story.parse_lines(text) == ["кошки", "собаки", "птицы", "рыбы"]
    assert story.parse_lines(text, limit=2) == ["кошки", "собаки"]
    assert story.parse_lines(None) == []
    assert story.parse_lines(123) == ["123"]


def test_word_rotator_changes_after_interval_and_never_repeats_twice():
    rot = story.WordRotator(["a", "b", "c"], every=(2, 2), rng=random.Random(1))
    got = [rot.tick() for _ in range(8)]
    assert got == [None, got[1], None, got[3], None, got[5], None, got[7]]
    words = [w for w in got if w]
    assert len(words) == 4
    assert all(x != y for x, y in zip(words, words[1:]))
    assert set(words) <= {"a", "b", "c"}


def test_word_rotator_single_word_and_empty():
    one = story.WordRotator(["x"], every=(1, 1), rng=random.Random(0))
    assert [one.tick() for _ in range(3)] == ["x", "x", "x"]
    empty = story.WordRotator([], every=(1, 1))
    assert [empty.tick() for _ in range(3)] == [None, None, None]


def test_pick_actions_all_or_nothing_at_extremes():
    full = story.Profile(100, 100, 100, 100, (5, 5), (3, 3))
    none = story.Profile(0, 0, 0, 0, (5, 5), (3, 3))
    assert story.pick_actions(full, random.Random(1)) == list(story.ACTIONS)
    assert story.pick_actions(none, random.Random(1)) == []


def test_pick_actions_respects_allowed_and_order():
    full = story.Profile(100, 100, 100, 100, (5, 5), (3, 3))
    assert story.pick_actions(full, random.Random(1), allowed=("like",)) == ["like"]
    assert story.pick_actions(full, random.Random(1), allowed=("comment", "like")) == ["like", "comment"]


def test_pick_actions_rate_is_roughly_right():
    p = story.Profile(30, 0, 0, 0, (5, 5), (3, 3))
    rng = random.Random(7)
    hits = sum("like" in story.pick_actions(p, rng) for _ in range(2000))
    assert 500 < hits < 700


def test_dwell_left():
    assert story.dwell_left(10, 4) == 6
    assert story.dwell_left(10, 12) == 1.0


def test_seek_plan_sums_exactly_and_respects_bounds():
    rng = random.Random(5)
    for total in (1, 7, 30, 61):
        plan = story.seek_plan(total, 3, 8, rng)
        assert sum(plan) == total
        assert all(1 <= s <= 8 for s in plan)
        assert all(s >= 3 for s in plan[:-1])   # короче lo может быть только последний шаг


def test_seek_plan_zero_total():
    assert story.seek_plan(0, 3, 8) == []


def test_tally_line():
    t = story.Tally()
    t.add("views", 14)
    t.add("like", 3)
    t.add("like")
    assert t.counts["like"] == 4
    assert t.line() == "просмотров 14, лайков 4"


def test_tally_line_empty():
    assert story.Tally().line() == "просмотров 0"


def test_tally_rejects_unknown_key():
    with pytest.raises(KeyError):
        story.Tally().add("fly")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_story.py -q`
Expected: FAIL / ERROR `ImportError: cannot import name 'story' from 'farm'`.

- [ ] **Step 3: Write the implementation**

Create `backend/farm/story.py`:

```python
"""Логика готовых сюжетов: профили поведения, смена слов, выбор действий.

Чистый модуль, как phrases.py: ни adb, ни диска, ни FastAPI. Всё случайное
принимает `rng`, поэтому тесты передают random.Random(seed) и получают
воспроизводимые числа без телефона.

Числа профилей — единственное место, где решается «насколько активно вести
себя». Они осторожнее, чем у Laixi (20/20/20/10): комментарии и подписки с
десятков аккаунтов первыми приводят к блокировке.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace

# Порядок действий на одном видео: дешёвое и обратимое раньше дорогого.
ACTIONS = ("like", "favorite", "follow", "comment")
ACTION_WORDS = {"like": "лайки", "favorite": "избранное",
                "follow": "подписки", "comment": "комментарии"}


@dataclass(frozen=True)
class Profile:
    like: float          # шанс действия на видео, проценты 0..100
    comment: float
    favorite: float
    follow: float
    dwell: tuple         # (от, до) секунд на одном видео
    change_every: tuple  # (от, до) видео до смены слова поиска

    def rate(self, action: str) -> float:
        return getattr(self, action)


PROFILES = {
    "quiet": Profile(10, 3, 5, 2, (8.0, 18.0), (4, 6)),
    "normal": Profile(20, 8, 10, 5, (6.0, 14.0), (3, 5)),
    "active": Profile(30, 15, 15, 10, (5.0, 10.0), (3, 5)),
}
PROFILE_LABELS = {"Тихий": "quiet", "Обычный": "normal", "Активный": "active"}
DEFAULT_PROFILE_LABEL = "Обычный"

RATE_LABELS = {"like": "Шанс лайка", "comment": "Шанс комментария",
               "favorite": "Шанс избранного", "follow": "Шанс подписки"}


def _num(value):
    """Число из значения формы или None: пусто, мусор и bool — «не задано»."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_profile(name, overrides=None) -> Profile:
    """Профиль по имени («Тихий» или quiet) плюс явные значения из формы.

    Явное значение побеждает профиль; пустое или нечисловое — игнорируется,
    чтобы разбор формы не падал на живом запуске.
    """
    key = PROFILE_LABELS.get(name, name)
    base = PROFILES.get(key, PROFILES["normal"])
    given = overrides or {}
    changes = {}
    for action in ACTIONS:
        n = _num(given.get(action))
        if n is not None:
            changes[action] = n
    dwell = list(base.dwell)
    lo, hi = _num(given.get("dwell_lo")), _num(given.get("dwell_hi"))
    if lo is not None:
        dwell[0] = lo
    if hi is not None:
        dwell[1] = hi
    if dwell[0] > dwell[1]:
        dwell[1] = dwell[0]
    every = list(base.change_every)
    clo, chi = _num(given.get("change_lo")), _num(given.get("change_hi"))
    if clo is not None:
        every[0] = int(clo)
    if chi is not None:
        every[1] = int(chi)
    if every[0] > every[1]:
        every[1] = every[0]
    return replace(base, dwell=(float(dwell[0]), float(dwell[1])),
                   change_every=(int(every[0]), int(every[1])), **changes)


def validate(params, need_actions: bool = True, allowed=ACTIONS) -> list:
    """Понятные ошибки формы до запуска; пустой список — можно запускать."""
    errors: list = []

    def number(key, label, lo=None, hi=None):
        raw = params.get(key)
        n = _num(raw)
        if raw not in (None, "") and n is None:
            errors.append(f"«{label}» — не число")
        elif n is not None and ((lo is not None and n < lo) or (hi is not None and n > hi)):
            errors.append(f"«{label}» должно быть от {lo:g} до {hi:g}")
        return n

    for action in ACTIONS:
        number(action, RATE_LABELS[action], 0, 100)
    dlo = number("dwell_lo", "Пауза на видео от", 0.5, 600)
    dhi = number("dwell_hi", "Пауза на видео до", 0.5, 600)
    if dlo is not None and dhi is not None and dlo >= dhi:
        errors.append("Пауза на видео «от» должна быть меньше паузы «до»")
    clo = number("change_lo", "Смена слова от", 1, 100)
    chi = number("change_hi", "Смена слова до", 1, 100)
    if clo is not None and chi is not None and clo >= chi:
        errors.append("Смена слова «от» должна быть меньше смены «до»")
    if "views" in params:
        number("views", "Сколько видео посмотреть", 1, 1000)
    if need_actions and not errors:
        prof = resolve_profile(params.get("profile"), params)
        if sum(prof.rate(a) for a in allowed) <= 0:
            errors.append("Все шансы равны нулю: сюжет только листал бы ленту. "
                          "Поднимите хотя бы один шанс или выберите другой профиль")
    return errors


def parse_lines(text, limit: int = 200) -> list:
    """Строки файла слов или фраз: без пустых и повторов, не больше `limit`."""
    seen = set()
    out = []
    for raw in str(text if text is not None else "").splitlines():
        line = raw.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= limit:
            break
    return out


class WordRotator:
    """Слово поиска: каждые N видео (N случайно из `every`) берётся новое.

    На первом видео слово не меняется (лента уже открыта), а два раза подряд
    одно и то же слово не выпадает, если слов больше одного. Laixi идёт по
    кругу в одном порядке; случайный порядок не даёт сорока телефонам искать
    одно и то же в одну и ту же минуту.
    """

    def __init__(self, words, every=(3, 5), rng=None):
        self.words = list(words)
        self.every = every
        self.rng = rng or random
        self.last = None
        self._left = self._draw()

    def _draw(self) -> int:
        lo, hi = int(self.every[0]), int(self.every[1])
        return self.rng.randint(lo, max(lo, hi))

    def tick(self):
        """Звать после каждого видео. Новое слово, когда пора менять, иначе None."""
        if not self.words:
            return None
        self._left -= 1
        if self._left > 0:
            return None
        self._left = self._draw()
        if len(self.words) == 1:
            self.last = self.words[0]
            return self.last
        pool = [w for w in self.words if w != self.last]
        self.last = self.rng.choice(pool)
        return self.last


def pick_actions(profile: Profile, rng=None, allowed=ACTIONS) -> list:
    """Какие действия сделать на этом видео: каждое — независимый бросок."""
    rng = rng or random
    return [a for a in ACTIONS
            if a in allowed and rng.random() * 100 < profile.rate(a)]


def dwell_left(target: float, spent: float) -> float:
    """Сколько ещё ждать на видео. Время на действия входит в паузу, поэтому
    видео занимает заданное время при любом числе действий. Не меньше секунды."""
    return max(1.0, target - spent)


def seek_plan(total, lo, hi, rng=None) -> list:
    """Разбивка времени прослушивания на паузы между перемотками.

    Сумма ровно `total` секунд; шаг случайный от `lo` до `hi`, последний
    обрезается до остатка.
    """
    rng = rng or random
    total = int(total)
    lo = max(1, int(lo))
    hi = max(lo, int(hi))
    plan = []
    done = 0
    while done < total:
        step = min(rng.randint(lo, hi), total - done)
        plan.append(step)
        done += step
    return plan


class Tally:
    """Счётчик просмотров и действий для строки в журнале."""

    LABELS = (("views", "просмотров"), ("like", "лайков"),
              ("favorite", "в избранное"), ("follow", "подписок"),
              ("comment", "комментариев"), ("searches", "поисков"))

    def __init__(self):
        self.counts = {key: 0 for key, _ in self.LABELS}

    def add(self, key: str, n: int = 1) -> None:
        if key not in self.counts:
            raise KeyError(key)
        self.counts[key] += n

    def line(self) -> str:
        parts = [f"{word} {self.counts[key]}" for key, word in self.LABELS
                 if key == "views" or self.counts[key]]
        return ", ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_story.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/farm/story.py backend/tests/test_story.py
git commit -m "Сюжеты: чистая логика story.py (профили, слова, действия, сводка)"
```

---

### Task 2: `ui/structure.py` — поиск элементов по структуре экрана

TikTok меняет `resourceId` между версиями, а структура экрана держится дольше. Скрипт Laixi ищет элементы именно по структуре; здесь то же, но чистыми функциями над деревом `farm/ui/tree.py`.

**Files:**
- Create: `backend/farm/ui/structure.py`
- Test: `backend/tests/test_structure.py`

**Interfaces:**
- Consumes: `farm.ui.tree.Node` (поля `id, parent, bounds (доли 0..1), cls, clickable, children: list[int]`), `tree.parse(xml, w, h)`.
- Produces:
  - `center(node) -> tuple[float, float]`
  - `action_column(nodes) -> list[Node]` — правая колонка действий сверху вниз или `[]`
  - `follow_plus(nodes, column) -> Node | None`
  - `tab_bar(nodes) -> list[Node]` — нижняя панель слева направо или `[]`
  - `grid_tiles(nodes) -> list[Node]` — плитки результатов в порядке чтения
  - `send_after_input(nodes) -> Node | None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_structure.py`:

```python
"""Структурные селекторы: колонка действий, панель вкладок, плитки, отправка."""
from farm.ui import structure, tree

W, H = 1080, 2280


def el(cls, box, kids="", clickable=False):
    x0, y0, x1, y1 = box
    return (f'<node class="{cls}" bounds="[{x0},{y0}][{x1},{y1}]" '
            f'clickable="{"true" if clickable else "false"}" text="" '
            f'resource-id="" content-desc="" package="p">{kids}</node>')


FL, LL, ET = "android.widget.FrameLayout", "android.widget.LinearLayout", "android.widget.EditText"


def column(plus_clickable=True):
    avatar = el("android.widget.ImageView", (910, 910, 1070, 1000))
    plus = el("android.widget.ImageView", (960, 1010, 1020, 1060), clickable=plus_clickable)
    wrapper = el(FL, (900, 900, 1080, 1100), el(FL, (900, 900, 1080, 1100), avatar + plus))
    rest = "".join(el(FL, (900, 1100 + i * 200, 1080, 1300 + i * 200), clickable=True)
                   for i in range(4))
    return el(LL, (900, 900, 1080, 1900), wrapper + rest)


def screen(*children):
    return f'<hierarchy>{el(FL, (0, 0, W, H), "".join(children))}</hierarchy>'


def parse(*children):
    return tree.parse(screen(*children), W, H)


def test_action_column_found_and_ordered_top_down():
    nodes = parse(column())
    col = structure.action_column(nodes)
    assert len(col) == 5
    tops = [n.bounds[1] for n in col]
    assert tops == sorted(tops)


def test_action_column_ignores_left_side_and_short_lists():
    left = el(LL, (0, 900, 200, 1900), "".join(el(FL, (0, 900 + i * 200, 200, 1100 + i * 200)) for i in range(5)))
    short = el(LL, (900, 900, 1080, 1700), "".join(el(FL, (900, 900 + i * 200, 1080, 1100 + i * 200)) for i in range(4)))
    assert structure.action_column(parse(left, short)) == []


def test_follow_plus_is_second_child_of_inner_and_clickable():
    nodes = parse(column())
    col = structure.action_column(nodes)
    plus = structure.follow_plus(nodes, col)
    assert plus is not None and plus.clickable
    assert structure.follow_plus(parse(column(plus_clickable=False)),
                                 structure.action_column(parse(column(plus_clickable=False)))) is None
    assert structure.follow_plus(nodes, []) is None


def test_tab_bar_five_children_at_bottom_left_to_right():
    tabs = el(LL, (0, 2200, 1080, 2250), "".join(el(FL, (i * 216, 2200, i * 216 + 216, 2250), clickable=True) for i in range(5)))
    nodes = parse(column(), tabs)
    bar = structure.tab_bar(nodes)
    assert len(bar) == 5
    assert [n.bounds[0] for n in bar] == sorted(n.bounds[0] for n in bar)
    # колонка действий (пять детей, но справа и выше) за панель не принимается
    assert all(n.bounds[1] > 0.9 for n in bar)


def test_tab_bar_absent():
    assert structure.tab_bar(parse(column())) == []


def test_grid_tiles_need_two_children_and_nested_second():
    good = el(FL, (0, 400, 500, 900), el(FL, (0, 400, 500, 450)) + el(FL, (0, 450, 500, 900), el(FL, (0, 450, 500, 500))), clickable=True)
    flat = el(FL, (500, 400, 1000, 900), el(FL, (500, 400, 1000, 450)) + el(FL, (500, 450, 1000, 900)), clickable=True)
    single = el(FL, (0, 900, 500, 1400), el(FL, (0, 900, 500, 950)), clickable=True)
    tiles = structure.grid_tiles(parse(good, flat, single))
    assert len(tiles) == 1 and tiles[0].bounds[0] == 0.0


def test_send_after_input_is_last_sibling():
    box = el(LL, (0, 2000, 1080, 2200), el(ET, (50, 2000, 800, 2200)) + el("android.widget.ImageView", (900, 2000, 1050, 2200), clickable=True))
    nodes = parse(box)
    send = structure.send_after_input(nodes)
    assert send is not None and send.bounds[0] > 0.8


def test_send_after_input_when_input_is_last_or_missing():
    only = el(LL, (0, 2000, 1080, 2200), el(ET, (50, 2000, 800, 2200)))
    assert structure.send_after_input(parse(only)) is None
    assert structure.send_after_input(parse(column())) is None


def test_center():
    nodes = parse(el(FL, (100, 200, 300, 600)))
    inner = [n for n in nodes if n.bounds[0] > 0][0]
    cx, cy = structure.center(inner)
    assert abs(cx - 200 / W) < 1e-6 and abs(cy - 400 / H) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_structure.py -q`
Expected: FAIL `ImportError: cannot import name 'structure' from 'farm.ui'`.

- [ ] **Step 3: Write the implementation**

Create `backend/farm/ui/structure.py`:

```python
"""Элементы экрана по структуре, а не по resource-id.

У TikTok id меняются между версиями, а раскладка держится дольше: справа
колонка из пяти значков, внизу панель из пяти вкладок. Скрипт Laixi ищет
элементы именно так. Чистые функции над узлами farm/ui/tree.py: ни adb, ни
uiautomator2, проверяются на образцах дампа.
"""
from __future__ import annotations

from .tree import Node


def center(node: Node):
    """Центр рамки в долях экрана — то, что принимает ctx.tap."""
    x0, y0, x1, y1 = node.bounds
    return (x0 + x1) / 2, (y0 + y1) / 2


def _is(node: Node, name: str) -> bool:
    return node.cls.endswith(name)


def action_column(nodes):
    """Правая колонка действий: LinearLayout с ≥5 детьми, высокий и у правого края.

    Дети сверху вниз: аватар (с «+» подписки), лайк, комментарий, избранное,
    «поделиться». Нет колонки (видео не открыто, реклама) — пустой список.
    """
    best = None
    for node in nodes:
        if not _is(node, "LinearLayout") or len(node.children) < 5:
            continue
        cx, _ = center(node)
        height = node.bounds[3] - node.bounds[1]
        if cx < 0.75 or height < 0.25:
            continue
        if best is None or node.area > best.area:
            best = node
    if best is None:
        return []
    return sorted((nodes[c] for c in best.children), key=lambda n: (n.bounds[1], n.bounds[0]))


def follow_plus(nodes, column):
    """Значок «+» подписки: второй ребёнок внутри первого элемента колонки.
    Нет его или он не нажимается (уже подписан) — None."""
    if not column or not column[0].children:
        return None
    inner = nodes[column[0].children[0]]
    if len(inner.children) < 2:
        return None
    plus = nodes[inner.children[1]]
    return plus if plus.clickable else None


def tab_bar(nodes):
    """Нижняя панель: LinearLayout ровно из пяти вкладок у нижнего края."""
    for node in nodes:
        if _is(node, "LinearLayout") and len(node.children) == 5 and node.bounds[1] >= 0.9:
            return sorted((nodes[c] for c in node.children), key=lambda n: n.bounds[0])
    return []


def grid_tiles(nodes):
    """Плитки результатов поиска: нажимаемый FrameLayout с ≥2 детьми, у второго
    есть свои дети. Порядок чтения: сверху вниз, слева направо."""
    tiles = []
    for node in nodes:
        if not (_is(node, "FrameLayout") and node.clickable and len(node.children) > 1):
            continue
        if node.bounds[1] < 0.1 or not nodes[node.children[1]].children:
            continue
        tiles.append(node)
    return sorted(tiles, key=lambda n: (round(n.bounds[1], 2), n.bounds[0]))


def send_after_input(nodes):
    """Кнопка отправки комментария: последний ребёнок родителя поля ввода.
    Поле одно в родителе или поля нет — None."""
    for node in nodes:
        if not _is(node, "EditText") or node.parent is None:
            continue
        parent = nodes[node.parent]
        last = nodes[parent.children[-1]]
        return None if last.id == node.id else last
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_structure.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/farm/ui/structure.py backend/tests/test_structure.py
git commit -m "Сюжеты: структурные селекторы экрана (колонка действий, вкладки, плитки)"
```

---

### Task 3: `feed.py` — общий движок ленты

**Files:**
- Create: `backend/farm/feed.py`
- Test: `backend/tests/test_feed.py`

**Interfaces:**
- Consumes (Task 1): `story.ACTIONS, story.ACTION_WORDS, story.PROFILE_LABELS, story.DEFAULT_PROFILE_LABEL, story.Profile, story.resolve_profile, story.validate, story.parse_lines, story.WordRotator, story.pick_actions, story.dwell_left, story.Tally`.
- Consumes (ctx, существующее): `ctx.loop(times=, watch=)`, `ctx.pause(lo, hi)`, `ctx.sleep(s)`, `ctx.log(s)`, `ctx.budget(name, limit, platform)`, `ctx.phrase(text)`, `ctx.fail(msg)`, `ctx.swipe(x1, y1, x2, y2, duration)`.
- Produces:
  - `DEFAULT_CAPS = {"like": 200, "favorite": 100, "follow": 40, "comment": 30}`
  - `feed_params(views=30, actions=True) -> dict` — готовый `PARAMS` для сюжета
  - `@dataclass FeedParams(views, profile, words, comments, caps, label, platform, allowed)`
  - `from_params(p, *, label, platform=None, allowed=story.ACTIONS, need_actions=True) -> FeedParams` (бросает `ValueError` с текстом ошибок формы)
  - `class FeedUI`: `ready() -> bool`, `has_actions() -> bool`, `perform(action, text="") -> bool`, `next() -> None`, `search(word) -> None`, `recover() -> None`
  - `run_feed(ctx, ui, fp, rng=None, clock=time.monotonic) -> story.Tally`
  - `swipe_up(ctx, rng=None) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_feed.py`:

```python
"""Движок ленты на фейковых ctx и FeedUI: порядок, бюджет времени, поиск, потолки."""
import random

import pytest

from farm import feed, story
from farm.context import BudgetReached, StepFailed


class FakeCtx:
    def __init__(self):
        self.now = 0.0
        self.logs = []
        self.sleeps = []
        self.budgets = {}
        self.limits = {}
        self.params = {}

    def log(self, m):
        self.logs.append(m)

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def pause(self, lo=0.4, hi=1.5):
        pass                      # паузы микро; время в тестах двигают только sleep и действия

    def phrase(self, t):
        return t

    def fail(self, m):
        raise StepFailed(m)

    def loop(self, times=None, minutes=None, pause=None, watch=False):
        for i in range(times):
            yield i

    def budget(self, name, limit, platform=None):
        self.budgets[name] = self.budgets.get(name, 0) + 1
        self.limits[name] = limit
        if self.budgets[name] > limit:
            raise BudgetReached(f"потолок: {name}")


class FakeUI(feed.FeedUI):
    def __init__(self, ctx, action_cost=4.0, ready=True, actions=True):
        self.ctx, self.cost = ctx, action_cost
        self._ready, self._actions = ready, actions
        self.performed, self.texts, self.searched = [], [], []
        self.nexts = self.recovers = 0

    def ready(self):
        return self._ready

    def has_actions(self):
        return self._actions

    def perform(self, action, text=""):
        self.performed.append(action)
        self.texts.append(text)
        self.ctx.now += self.cost
        return True

    def next(self):
        self.nexts += 1

    def search(self, word):
        self.searched.append(word)

    def recover(self):
        self.recovers += 1


def fp(**kw):
    prof = story.Profile(kw.pop("like", 0), kw.pop("comment", 0), kw.pop("favorite", 0),
                         kw.pop("follow", 0), kw.pop("dwell", (10.0, 10.0)),
                         kw.pop("every", (3, 5)))
    base = dict(views=3, profile=prof, words=[], comments=[],
                caps=dict(feed.DEFAULT_CAPS), label="Тест", platform=None,
                allowed=story.ACTIONS)
    base.update(kw)
    return feed.FeedParams(**base)


def run(ctx, ui, params, seed=1):
    return feed.run_feed(ctx, ui, params, rng=random.Random(seed), clock=lambda: ctx.now)


def test_views_and_swipes():
    ctx = FakeCtx()
    ui = FakeUI(ctx)
    tally = run(ctx, ui, fp(views=4))
    assert ui.nexts == 4
    assert tally.counts["views"] == 4
    assert all(s >= 1 for s in ctx.sleeps)


def test_dwell_budget_includes_action_time():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=4.0)
    run(ctx, ui, fp(views=1, like=100))
    assert ui.performed == ["like"]
    assert ctx.sleeps == [6.0]            # 10 с на видео минус 4 с на лайк


def test_no_actions_means_full_dwell():
    ctx = FakeCtx()
    ui = FakeUI(ctx, actions=False)
    run(ctx, ui, fp(views=1, like=100))
    assert ui.performed == []
    assert ctx.sleeps == [10.0]


def test_action_order_is_fixed():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, like=100, favorite=100, follow=100, comment=100, comments=["класс"]))
    assert ui.performed == ["like", "favorite", "follow", "comment"]
    assert ui.texts[-1] == "класс"


def test_comment_skipped_without_phrases():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, comment=100, comments=[]))
    assert ui.performed == []


def test_allowed_filters_actions():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, like=100, follow=100, allowed=("like",)))
    assert ui.performed == ["like"]


def test_budget_taken_before_each_action_and_stops_run():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    params = fp(views=5, like=100, caps={**feed.DEFAULT_CAPS, "like": 2})
    with pytest.raises(BudgetReached):
        run(ctx, ui, params)
    assert ui.performed == ["like", "like"]        # третий лайк не состоялся
    assert ctx.limits["Тест: лайки"] == 2


def test_zero_cap_disables_action():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=2, like=100, caps={**feed.DEFAULT_CAPS, "like": 0}))
    assert ui.performed == []
    assert ctx.budgets == {}


def test_search_rotation_not_on_first_video():
    ctx = FakeCtx()
    ui = FakeUI(ctx)
    tally = run(ctx, ui, fp(views=5, words=["alpha", "beta"], every=(2, 2)))
    assert len(ui.searched) == 2 and ui.searched[0] != ui.searched[1]
    assert tally.counts["searches"] == 2


def test_not_ready_triggers_recover_then_fails_if_still_not_ready():
    ctx = FakeCtx()
    ui = FakeUI(ctx, ready=False)
    with pytest.raises(StepFailed):
        run(ctx, ui, fp(views=2))
    assert ui.recovers == 1


def test_summary_logged_at_end():
    ctx = FakeCtx()
    run(ctx, FakeUI(ctx), fp(views=2))
    assert ctx.logs[-1].startswith("итог: просмотров 2")


def test_from_params_builds_and_validates():
    p = {"profile": "Тихий", "views": "12", "words": "a\nb\na", "comments": "x\n\ny",
         "like": "", "cap_like": "50", "cap_follow": 0}
    got = feed.from_params(p, label="TikTok", platform="tiktok")
    assert got.views == 12
    assert got.profile == story.PROFILES["quiet"]
    assert got.words == ["a", "b"] and got.comments == ["x", "y"]
    assert got.caps["like"] == 50 and got.caps["follow"] == 0 and got.caps["comment"] == 30


def test_from_params_zeroes_not_allowed_actions():
    got = feed.from_params({"profile": "Активный", "views": 5}, label="VK", allowed=("like",))
    assert got.profile.like == story.PROFILES["active"].like
    assert got.profile.comment == got.profile.follow == got.profile.favorite == 0


def test_from_params_reports_form_errors():
    with pytest.raises(ValueError) as e:
        feed.from_params({"profile": "Обычный", "views": 0}, label="x")
    assert "Сколько видео" in str(e.value)


def test_feed_params_shape():
    p = feed.feed_params(views=40)
    assert p["views"]["default"] == 40 and p["views"]["type"] == "number"
    assert p["profile"]["options"] == list(story.PROFILE_LABELS)
    assert p["words"]["type"] == "textarea"
    assert "cap_like" in p
    assert "comments" not in feed.feed_params(actions=False)
    assert "cap_like" not in feed.feed_params(actions=False)


def test_swipe_up_uses_fractions_and_goes_up():
    calls = []

    class C:
        def swipe(self, x1, y1, x2, y2, duration=0.25):
            calls.append((x1, y1, x2, y2, duration))

    feed.swipe_up(C(), random.Random(2))
    x1, y1, x2, y2, d = calls[0]
    assert 0.4 <= x1 <= 0.8 and 0.4 <= x2 <= 0.8
    assert 0.55 <= y1 <= 0.72 and 0.12 <= y2 <= 0.24 and y2 < y1
    assert 0.3 <= d <= 0.6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed.py -q`
Expected: FAIL `ImportError: cannot import name 'feed' from 'farm'`.

- [ ] **Step 3: Write the implementation**

Create `backend/farm/feed.py`:

```python
"""Общий движок ленты для готовых сюжетов: листает, ставит лайки по шансам.

Движок знает только порядок и время; как именно нажать «лайк» в TikTok или
VK, ему говорит маленький класс FeedUI, который пишет сам сюжет. Так шесть
сюжетов не повторяют цикл «пауза → действия → свайп».

Приёмы переняты из TikTok-скрипта Laixi: пауза на видео включает время
действий (видео занимает заданное время при любом числе лайков), между
действиями микропаузы, нет панели действий — только смотрим. Иначе, чем у
Laixi: комментарии выбираются случайно, а не по кругу, и у каждого действия
есть потолок за сутки.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from . import story

DEFAULT_CAPS = {"like": 200, "favorite": 100, "follow": 40, "comment": 30}
MAX_WORDS = 200


def feed_params(views: int = 30, actions: bool = True) -> dict:
    """PARAMS для сюжета-ленты: поля формы запуска, подписи простыми словами."""
    params = {
        "profile": {"label": "Как вести себя", "options": list(story.PROFILE_LABELS),
                    "default": story.DEFAULT_PROFILE_LABEL,
                    "help": "Тихий — редкие действия, Активный — чаще. Ниже можно уточнить"},
        "views": {"label": "Сколько видео посмотреть", "type": "number",
                  "default": views, "min": 1, "max": 1000},
        "dwell_lo": {"label": "Пауза на видео от, с", "type": "number", "default": "",
                     "help": "Пусто — как у выбранного профиля"},
        "dwell_hi": {"label": "Пауза на видео до, с", "type": "number", "default": ""},
    }
    if actions:
        params.update({
            "like": {"label": "Шанс лайка, %", "type": "number", "default": "", "min": 0, "max": 100},
            "comment": {"label": "Шанс комментария, %", "type": "number", "default": "", "min": 0, "max": 100},
            "favorite": {"label": "Шанс избранного, %", "type": "number", "default": "", "min": 0, "max": 100},
            "follow": {"label": "Шанс подписки, %", "type": "number", "default": "", "min": 0, "max": 100},
            "comments": {"label": "Фразы для комментариев (по строке)", "type": "textarea", "default": "",
                         "help": "Можно «{класс|супер|огонь}» — на каждом телефоне выпадет свой вариант"},
            "cap_like": {"label": "Не больше лайков за сутки", "type": "number",
                         "default": DEFAULT_CAPS["like"], "min": 0},
            "cap_favorite": {"label": "Не больше в избранное за сутки", "type": "number",
                             "default": DEFAULT_CAPS["favorite"], "min": 0},
            "cap_follow": {"label": "Не больше подписок за сутки", "type": "number",
                           "default": DEFAULT_CAPS["follow"], "min": 0},
            "cap_comment": {"label": "Не больше комментариев за сутки", "type": "number",
                            "default": DEFAULT_CAPS["comment"], "min": 0},
        })
    params["words"] = {"label": "Слова поиска (по строке)", "type": "textarea", "default": "",
                       "help": "Пусто — просто листать ленту без поиска"}
    return params


@dataclass
class FeedParams:
    views: int
    profile: story.Profile
    words: list
    comments: list
    caps: dict
    label: str
    platform: object      # платформа аккаунта для потолка или None
    allowed: tuple


def _cap(params, action):
    n = story._num(params.get(f"cap_{action}"))
    return DEFAULT_CAPS[action] if n is None else max(0, int(n))


def from_params(p, *, label, platform=None, allowed=story.ACTIONS, need_actions=True) -> FeedParams:
    """Параметры формы → FeedParams. Ошибки формы — ValueError с понятным текстом."""
    errors = story.validate(p, need_actions=need_actions and bool(allowed), allowed=allowed)
    if errors:
        raise ValueError("; ".join(errors))
    profile = story.resolve_profile(p.get("profile"), p)
    profile = replace(profile, **{a: 0.0 for a in story.ACTIONS if a not in allowed})
    views = story._num(p.get("views"))
    return FeedParams(
        views=int(views) if views is not None else 30,
        profile=profile,
        words=story.parse_lines(p.get("words"), MAX_WORDS),
        comments=story.parse_lines(p.get("comments"), MAX_WORDS),
        caps={a: _cap(p, a) for a in story.ACTIONS},
        label=label, platform=platform, allowed=tuple(allowed))


class FeedUI:
    """Что сюжет умеет делать на экране своей ленты."""

    def ready(self) -> bool:
        """Мы на ленте, а не в чужом экране."""
        return True

    def has_actions(self) -> bool:
        """На этом видео есть панель действий (не реклама, не подборка)."""
        return True

    def perform(self, action: str, text: str = "") -> bool:
        """Сделать действие из story.ACTIONS; True — получилось."""
        raise NotImplementedError

    def next(self) -> None:
        """Перейти к следующему видео."""
        raise NotImplementedError

    def search(self, word: str) -> None:
        """Найти слово и открыть случайный результат."""

    def recover(self) -> None:
        """Выбраться на ленту из чужого экрана."""


def swipe_up(ctx, rng=None) -> None:
    """Свайп к следующему видео. Геометрия из Laixi (экран 1080×2280:
    старт x 500–800, y 1300–1600, финиш x 500–800, y 350–500, 1 с), но долями
    экрана: ферма работает на разных разрешениях."""
    rng = rng or random
    ctx.swipe(rng.uniform(0.46, 0.74), rng.uniform(0.57, 0.70),
              rng.uniform(0.46, 0.74), rng.uniform(0.15, 0.22),
              rng.uniform(0.35, 0.55))


def run_feed(ctx, ui: FeedUI, fp: FeedParams, rng=None, clock=time.monotonic) -> story.Tally:
    """Лента: `fp.views` видео; на каждом — действия по шансам и пауза до цели."""
    rng = rng or random
    tally = story.Tally()
    rotator = story.WordRotator(fp.words, fp.profile.change_every, rng)
    ctx.log(f"{fp.label}: {fp.views} видео, слов поиска {len(fp.words)}, "
            f"фраз {len(fp.comments)}")
    for i in ctx.loop(times=fp.views, watch=True):
        started = clock()
        target = rng.uniform(*fp.profile.dwell)
        if i:
            word = rotator.tick()
            if word:
                ctx.log(f"меняю слово поиска: «{word}»")
                ui.search(word)
                tally.add("searches")
        ctx.pause(1, 3)
        if not ui.ready():
            ui.recover()
            if not ui.ready():
                ctx.fail("экран не похож на ленту, выбраться не удалось")
        chosen = story.pick_actions(fp.profile, rng, fp.allowed) if ui.has_actions() else []
        for action in story.ACTIONS:
            if action not in chosen or fp.caps[action] <= 0:
                continue
            if action == "comment" and not fp.comments:
                continue
            # Потолок берём ДО действия: исчерпан — сюжет заканчивается успехом
            # (BudgetReached), а пятьдесят первая подписка не случается.
            ctx.budget(f"{fp.label}: {story.ACTION_WORDS[action]}", fp.caps[action], fp.platform)
            text = ctx.phrase(rng.choice(fp.comments)) if action == "comment" else ""
            if ui.perform(action, text):
                tally.add(action)
            ctx.pause(1, 3)
        tally.add("views")
        ctx.sleep(story.dwell_left(target, clock() - started))
        ui.next()
        if tally.counts["views"] % 5 == 0:
            ctx.log(tally.line())
    ctx.log("итог: " + tally.line())
    return tally
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed.py tests/test_story.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/farm/feed.py backend/tests/test_feed.py
git commit -m "Сюжеты: общий движок ленты feed.py (бюджет времени, потолки, поиск)"
```

---

### Task 4: поле `textarea` в параметрах сценария

Слова поиска и фразы — по строке, а форма умеет только однострочные поля.

**Files:**
- Modify: `frontend/js/scenarios.js` (функция `paramField`, около строки 205)
- Test: `backend/tests/test_param_field_js.py`

**Interfaces:**
- Consumes: существующие `paramField(name, spec, value)` и `esc(...)`.
- Produces: `paramField` для `spec.type === 'textarea'` возвращает `<textarea id="p_<name>" rows="4" placeholder="...">значение</textarea>`; `paramsRead` ничего не меняет (читает `el.value`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_param_field_js.py`:

```python
"""Поле параметра сценария: textarea для списков слов и фраз (scenarios.js: paramField)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "scenarios.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function paramField'), b = src.indexOf('/* Настройки сценария');
const ctx = {esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.f=paramField', ctx);
const html = ctx.f('words', {type: 'textarea', placeholder: 'по строке'}, 'a\nb<c');
assert.ok(html.startsWith('<textarea id="p_words"'), html);
assert.ok(html.includes('rows="4"'));
assert.ok(html.includes('placeholder="по строке"'));
assert.ok(html.includes('a\nb&lt;c</textarea>'));
// остальные типы не сломаны
assert.ok(ctx.f('n', {type: 'number'}, 5).includes('type="number"'));
assert.ok(ctx.f('t', {}, 'x').includes('type="text"'));
assert.ok(ctx.f('s', {options: ['a', 'b']}, 'b').includes('<select'));
"""


def test_textarea_param_field():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_param_field_js.py -q`
Expected: FAIL (assertion: html does not start with `<textarea`).

- [ ] **Step 3: Implement**

In `frontend/js/scenarios.js`, inside `paramField`, insert before the final `return \`<input type="text"...`:

```javascript
    if (spec.type === 'textarea') {
        return `<textarea id="p_${name}" rows="4"
                 placeholder="${esc(spec.placeholder || '')}">${esc(value)}</textarea>`;
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_param_field_js.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/scenarios.js backend/tests/test_param_field_js.py
git commit -m "Параметры сценария: многострочное поле textarea"
```

---

### Task 5: галерея — бэкенд

**Files:**
- Create: `backend/farm/gallery.py`, `backend/farm/api/gallery.py`
- Modify: `backend/farm/config.py` (рядом со `SCENARIOS_DIR`, строка ~14), `backend/farm/api/__init__.py`
- Test: `backend/tests/test_gallery.py`

**Interfaces:**
- Produces:
  - `config.GALLERY_DIR: Path` (по умолчанию `ROOT / "scenarios" / "gallery"`, переопределяется `FARM_GALLERY_DIR`)
  - `gallery.items() -> list[dict]` — ключи: `key, name, description, platform, verified, package, added`
  - `gallery.add(key: str) -> str` — копирует `gallery/<key>.py` в `config.SCENARIOS_DIR`, возвращает ключ копии; неизвестный или кривой ключ → `KeyError`
  - API: `GET /api/gallery` → список; `POST /api/gallery/{key}/add` → `{"key": "<копия>"}`, 404 при `KeyError`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_gallery.py`:

```python
"""Галерея готовых сюжетов: карточки из ast, копирование, имена, изоляция."""
import pytest
from fastapi import HTTPException

from farm import config, gallery, scenarios
from farm.api import gallery as api_gallery

CARD = '''"""Лента для проверки."""
NAME = "Лента {n}"
DESCRIPTION = "Листает и лайкает"
GALLERY = {{"platform": "TikTok", "verified": False, "package": "com.x"}}
PARAMS = feed.feed_params()


def run(ctx):
    pass
'''


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    gal, sc = tmp_path / "gallery", tmp_path / "scenarios"
    gal.mkdir()
    sc.mkdir()
    monkeypatch.setattr(config, "GALLERY_DIR", gal)
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc)
    return gal, sc


def put(gal, key, n=1):
    (gal / f"{key}.py").write_text(CARD.format(n=n), "utf-8")


def test_items_read_metadata_without_executing(dirs):
    gal, _ = dirs
    put(gal, "tiktok_feed")                       # PARAMS ссылается на feed, которого в файле нет
    got = gallery.items()
    assert got == [{"key": "tiktok_feed", "name": "Лента 1", "description": "Листает и лайкает",
                    "platform": "TikTok", "verified": False, "package": "com.x", "added": False}]


def test_items_skip_underscore_and_broken_files(dirs):
    gal, _ = dirs
    put(gal, "ok")
    put(gal, "_hidden")
    (gal / "broken.py").write_text("def (:\n", "utf-8")
    (gal / "noname.py").write_text("x = 1\n", "utf-8")
    assert [c["key"] for c in gallery.items()] == ["ok"]


def test_description_falls_back_to_docstring(dirs):
    gal, _ = dirs
    (gal / "d.py").write_text('"""Первая строка.\n\nВторая."""\nNAME = "Д"\n', "utf-8")
    assert gallery.items()[0]["description"] == "Первая строка."


def test_add_copies_file_and_marks_added(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    key = gallery.add("tiktok_feed")
    assert key == "tiktok_feed"
    assert (sc / "tiktok_feed.py").read_bytes() == (gal / "tiktok_feed.py").read_bytes()
    assert gallery.items()[0]["added"] is True


def test_add_twice_gets_numbered_name(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    assert gallery.add("tiktok_feed") == "tiktok_feed"
    assert gallery.add("tiktok_feed") == "tiktok_feed_2"
    assert gallery.add("tiktok_feed") == "tiktok_feed_3"
    assert sorted(p.name for p in sc.glob("*.py")) == ["tiktok_feed.py", "tiktok_feed_2.py", "tiktok_feed_3.py"]


@pytest.mark.parametrize("bad", ["../etc", "a/b", "A", "", "x.py", "nope"])
def test_add_rejects_bad_or_unknown_keys(dirs, bad):
    with pytest.raises(KeyError):
        gallery.add(bad)


def test_gallery_files_are_not_in_my_scenarios(dirs):
    gal, sc = dirs
    put(gal, "tiktok_feed")
    assert scenarios.discover(force=True) == []


def test_api_list_and_add(dirs):
    gal, _ = dirs
    put(gal, "tiktok_feed")
    assert api_gallery.list_gallery()[0]["key"] == "tiktok_feed"
    assert api_gallery.add_to_mine("tiktok_feed") == {"key": "tiktok_feed"}


def test_api_add_unknown_is_404(dirs):
    with pytest.raises(HTTPException) as e:
        api_gallery.add_to_mine("nope")
    assert e.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_gallery.py -q`
Expected: FAIL `ImportError: cannot import name 'gallery' from 'farm'`.

- [ ] **Step 3: Implement**

In `backend/farm/config.py`, directly after the `SCENARIOS_DIR = ...` line (14):

```python
# Готовые сюжеты лежат отдельно от «Моих» и не запускаются, пока их не
# скопировали (farm/gallery.py). Каталог идёт вместе с программой, поэтому
# от FARM_SCENARIOS_DIR не зависит.
GALLERY_DIR = Path(os.getenv("FARM_GALLERY_DIR", ROOT / "scenarios" / "gallery"))
```

Create `backend/farm/gallery.py`:

```python
"""Галерея готовых сюжетов: карточки и копирование в «Мои».

Метаданные читаются через ast, файл не выполняется: карточка не должна
импортировать сюжет (а с ним TikTok-селекторы и прочее) и не должна
конфликтовать по имени модуля с копией того же сюжета в «Моих».
"""
from __future__ import annotations

import ast
import logging
import re
import shutil

from . import config

log = logging.getLogger("farm.gallery")

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_WANTED = ("NAME", "DESCRIPTION", "GALLERY")


def _meta(path):
    """NAME/DESCRIPTION/GALLERY из исходника или None, если файл негодный."""
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError) as e:
        log.warning("галерея: %s не читается: %s", path.name, e)
        return None
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in _WANTED):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    doc = ast.get_docstring(tree) or ""
    found["_doc"] = doc.strip().splitlines()[0] if doc.strip() else ""
    return found


def _added(key: str) -> bool:
    """Есть ли в «Моих» копия: сам ключ или ключ_N."""
    pattern = re.compile(rf"^{re.escape(key)}(_\d+)?$")
    return any(pattern.match(p.stem) for p in config.SCENARIOS_DIR.glob("*.py"))


def items() -> list:
    out = []
    for path in sorted(config.GALLERY_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        meta = _meta(path)
        if not meta or "NAME" not in meta:
            continue
        tag = meta.get("GALLERY") if isinstance(meta.get("GALLERY"), dict) else {}
        out.append({
            "key": path.stem,
            "name": str(meta["NAME"]),
            "description": str(meta.get("DESCRIPTION") or meta["_doc"]),
            "platform": str(tag.get("platform", "")),
            "verified": bool(tag.get("verified", False)),
            "package": str(tag.get("package", "")),
            "added": _added(path.stem),
        })
    return out


def add(key: str) -> str:
    """Скопировать сюжет в «Мои». Возвращает ключ копии (key, key_2, …)."""
    if not KEY_RE.match(key or ""):
        raise KeyError(key)
    src = config.GALLERY_DIR / f"{key}.py"
    if not src.is_file():
        raise KeyError(key)
    target = key
    n = 1
    while (config.SCENARIOS_DIR / f"{target}.py").exists():
        n += 1
        target = f"{key}_{n}"
    shutil.copyfile(src, config.SCENARIOS_DIR / f"{target}.py")
    return target
```

Create `backend/farm/api/gallery.py`:

```python
"""Галерея готовых сюжетов: список карточек и «Добавить в мои»."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import gallery

router = APIRouter()


@router.get("/api/gallery")
def list_gallery():
    return gallery.items()


@router.post("/api/gallery/{key}/add")
def add_to_mine(key: str):
    try:
        return {"key": gallery.add(key)}
    except KeyError:
        raise HTTPException(404, "такого сюжета в галерее нет")
```

In `backend/farm/api/__init__.py`: add `gallery` to the import tuple (`from . import (accounts, apks, budget, bulk, detours, deviations, devices, files, gallery, jobs, ...`) and, after `router.include_router(schedule.router)`:

```python
router.include_router(gallery.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_gallery.py tests/test_scenarios*.py -q`
Expected: all PASS (если `test_scenarios*.py` нет — запустить `python -m pytest -q -k scenario`).

- [ ] **Step 5: Commit**

```bash
git add backend/farm/gallery.py backend/farm/api/gallery.py backend/farm/api/__init__.py backend/farm/config.py backend/tests/test_gallery.py
git commit -m "Галерея готовых: карточки из ast и добавление в «Мои»"
```

---

### Task 6: шесть сюжетов

Каждый файл — отдельный сценарий в `backend/scenarios/gallery/`. Селекторы взяты из расшифрованных скриптов Laixi (спека, раздел «Что внутри скриптов Laixi») и не проверены на вашем парке: `verified = False`. Общие правила сюжетов: `ctx.watch_popups()`, `ctx.humanize()`, `ctx.unlock()` в начале; действия аккаунта через `feed.run_feed` (там `ctx.budget`).

**Files:**
- Create: `backend/scenarios/gallery/tiktok_feed.py`, `shorts_autoscroll.py`, `spotify_listener.py`, `vk_feed.py`, `telegram_channels.py`, `youtube_shorts.py`
- Test: `backend/tests/test_gallery_scenarios.py`

**Interfaces:**
- Consumes: `feed.feed_params, feed.from_params, feed.FeedUI, feed.run_feed, feed.swipe_up`, `structure.*`, `tree.parse`, `story.*`; ctx: `ctx.size` (свойство, `(w, h)`), `ctx.dump_hierarchy() -> str`, `ctx.tap(x, y)` (доли), `ctx.swipe(...)`, `ctx.key("enter")`, `ctx.type(text, clear=False)`, `ctx.find(timeout, **selector)`, `ctx.exists(timeout, **selector)`, `ctx.click_if_exists(timeout, **selector)`, `ctx.click_target(sel=, text=, at=, timeout=)`, `ctx.set_text(value, timeout, **selector)`, `ctx.launch_app(package, stop_first=False)`, `ctx.wait_app(package, timeout)`, `ctx.current_app() -> str` (пакет), `ctx.shell(cmd)`, `ctx.chance(percent)`, `ctx.budget(name, limit, platform)`, `ctx.back()`.
- Produces: у каждого файла `NAME`, `DESCRIPTION`, `GALLERY = {"platform", "verified": False, "package"}`, `PARAMS`, `run(ctx)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gallery_scenarios.py`:

```python
"""Каждый готовый сюжет импортируется, описан и совместим с формой запуска."""
import importlib.util
from pathlib import Path

import pytest

from farm import config, scenarios

GALLERY = Path(config.ROOT) / "scenarios" / "gallery"
KEYS = ["tiktok_feed", "shorts_autoscroll", "spotify_listener",
        "vk_feed", "telegram_channels", "youtube_shorts"]


def load(key):
    spec = importlib.util.spec_from_file_location(f"gallery_test_{key}", GALLERY / f"{key}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_expected_scenarios_exist():
    assert sorted(p.stem for p in GALLERY.glob("*.py")) == sorted(KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_scenario_is_described_and_unverified(key):
    mod = load(key)
    assert callable(mod.run)
    assert mod.NAME and mod.DESCRIPTION
    assert mod.GALLERY["platform"] and mod.GALLERY["package"]
    assert mod.GALLERY["verified"] is False


@pytest.mark.parametrize("key", KEYS)
def test_params_are_valid_form_fields(key):
    mod = load(key)
    for name, spec in mod.PARAMS.items():
        assert spec.get("label"), name
        assert spec.get("type") in (None, "number", "bool", "textarea"), name
        if spec.get("options"):
            assert spec["default"] in spec["options"], name


@pytest.mark.parametrize("key", KEYS)
def test_default_params_resolve(key):
    mod = load(key)
    sc = scenarios.Scenario(key, mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    resolved = scenarios.resolve_params(sc, {})
    assert set(mod.PARAMS) <= set(resolved)


@pytest.mark.parametrize("key", ["tiktok_feed", "vk_feed", "youtube_shorts"])
def test_feed_scenarios_accept_default_form(key):
    from farm import feed
    mod = load(key)
    sc = scenarios.Scenario(key, mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    params = scenarios.resolve_params(sc, {"words": "кошки\nсобаки"})
    assert feed.from_params(params, label="x", allowed=mod.ALLOWED).views >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gallery_scenarios.py -q`
Expected: FAIL (`test_all_expected_scenarios_exist`: каталога нет).

- [ ] **Step 3: Create the six scenario files**

Create `backend/scenarios/gallery/tiktok_feed.py`:

```python
"""Лента-прогрев TikTok: листает, лайкает, пишет комментарии по шансам.

Селекторы TikTok — по структуре экрана (как в скрипте Laixi): справа колонка
из пяти значков, внизу панель из пяти вкладок. Не проверено на вашем парке.
"""
import random

from farm import feed, story
from farm.ui import structure, tree

NAME = "TikTok: лента-прогрев"
DESCRIPTION = ("Листает ленту с паузой на видео, ставит лайки, добавляет в избранное, "
               "подписывается и пишет комментарии по шансам; меняет слова поиска.")
PACKAGE = "com.zhiliaoapp.musically"
GALLERY = {"platform": "TikTok", "verified": False, "package": PACKAGE}
ALLOWED = story.ACTIONS
PARAMS = feed.feed_params(views=30)

CLOSE_PANEL = (0.92, 0.075)   # тап над панелью комментариев закрывает её
SEARCH_ICON = (0.92, 0.075)


class TikTokUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng
        self.nodes, self.column = [], []

    def _scan(self):
        w, h = self.ctx.size
        self.nodes = tree.parse(self.ctx.dump_hierarchy(), w, h)
        self.column = structure.action_column(self.nodes)

    def _tap(self, node):
        self.ctx.tap(*structure.center(node))
        return True

    def go_home(self):
        self._scan()
        bar = structure.tab_bar(self.nodes)
        if bar:
            self._tap(bar[0])
            self.ctx.sleep(1.5)

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def has_actions(self):
        self._scan()
        return len(self.column) >= 5

    def perform(self, action, text=""):
        col = self.column
        if action == "like":
            return self._tap(col[1])
        if action == "favorite":
            return self._tap(col[3]) if len(col) > 5 else False
        if action == "follow":
            plus = structure.follow_plus(self.nodes, col)
            return self._tap(plus) if plus is not None else False
        if action == "comment":
            return self._comment(col[2], text)
        return False

    def _comment(self, icon, text):
        ctx = self.ctx
        self._tap(icon)
        ctx.sleep(2)
        for _ in range(self.rng.randint(1, 3)):          # «читает» комментарии
            ctx.pause(1, 3)
            ctx.swipe(0.5, 0.75, 0.5, 0.45, 0.35)
        field = ctx.find(timeout=3, className="android.widget.EditText")
        if field is None:
            ctx.back()
            return False
        field.click()
        ctx.type(text)
        ctx.pause(2, 4)
        w, h = ctx.size
        send = structure.send_after_input(tree.parse(ctx.dump_hierarchy(), w, h))
        if send is None:
            ctx.back()
            ctx.back()
            return False
        self._tap(send)
        ctx.sleep(2)
        ctx.tap(*CLOSE_PANEL)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.5)

    def search(self, word):
        ctx = self.ctx
        self.recover()
        ctx.tap(*SEARCH_ICON)
        ctx.sleep(1.5)
        field = ctx.find(timeout=5, className="android.widget.EditText")
        if field is None:
            ctx.back()
            return
        field.click()
        ctx.type(word, clear=True)
        ctx.key("enter")
        ctx.sleep(3)
        w, h = ctx.size
        tiles = structure.grid_tiles(tree.parse(ctx.dump_hierarchy(), w, h))
        if tiles:
            self._tap(self.rng.choice(tiles))
            ctx.sleep(2)
        else:
            ctx.back()

    def recover(self):
        for _ in range(5):
            if self.ctx.current_app() == PACKAGE and self.has_actions():
                return
            self.ctx.back()
            self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="TikTok", platform="tiktok", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("TikTok не открылся")
    ui = TikTokUI(ctx, random.Random())
    ui.go_home()
    feed.run_feed(ctx, ui, fp)
```

Create `backend/scenarios/gallery/shorts_autoscroll.py`:

```python
"""Автолистание шортсов: свайп вверх с паузой, без лайков и комментариев.

Из скрипта Laixi «自动上滑»: вертикальный свайп со случайными точками, пауза
7–20 с на ролик. Подходит для TikTok, YouTube Shorts и Reels — у всех лента
листается свайпом вверх.
"""
import random

from farm import feed, story

NAME = "Автолистание шортсов"
DESCRIPTION = "Листает вертикальную ленту (TikTok, YouTube Shorts, Reels) со случайной паузой на ролик."
GALLERY = {"platform": "Любая лента", "verified": False, "package": "com.zhiliaoapp.musically"}
ALLOWED = ()
PARAMS = {
    "package": {"label": "Приложение (пакет)", "default": "com.zhiliaoapp.musically",
                "help": "TikTok com.zhiliaoapp.musically, YouTube com.google.android.youtube, "
                        "Instagram com.instagram.android"},
    "views": {"label": "Сколько роликов", "type": "number", "default": 50, "min": 1, "max": 1000},
    "dwell_lo": {"label": "Пауза на ролик от, с", "type": "number", "default": 7, "min": 1},
    "dwell_hi": {"label": "Пауза на ролик до, с", "type": "number", "default": 20, "min": 2},
}


class ScrollUI(feed.FeedUI):
    def __init__(self, ctx, package, rng):
        self.ctx, self.package, self.rng = ctx, package, rng

    def ready(self):
        return self.ctx.current_app() == self.package

    def has_actions(self):
        return False

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.5)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    package = (ctx.params["package"] or "").strip()
    if not package:
        ctx.fail("не указан пакет приложения")
    form = {"views": ctx.params["views"], "dwell_lo": ctx.params["dwell_lo"],
            "dwell_hi": ctx.params["dwell_hi"]}
    fp = feed.from_params(form, label="Автолистание", allowed=ALLOWED, need_actions=False)
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(package)
    if not ctx.wait_app(package, timeout=20):
        ctx.fail(f"{package} не открылся")
    feed.run_feed(ctx, ScrollUI(ctx, package, random.Random()), fp)
```

Create `backend/scenarios/gallery/vk_feed.py`:

```python
"""Лента VK: листает, лайкает по шансу.

Кнопка лайка — `com.vkontakte.android:id/iv_likes` (из вашего записанного
сценария «VK like»). Комментарии, подписки и избранное отключены.
"""
import random

from farm import feed

NAME = "VK: лента с лайками"
DESCRIPTION = "Листает ленту VK с паузой, ставит лайки по шансу, соблюдая потолок за сутки."
PACKAGE = "com.vkontakte.android"
GALLERY = {"platform": "VK", "verified": False, "package": PACKAGE}
ALLOWED = ("like",)
PARAMS = {k: v for k, v in feed.feed_params(views=40).items()
          if k in ("profile", "views", "dwell_lo", "dwell_hi", "like", "cap_like")}
PARAMS["views"]["label"] = "Сколько экранов пролистать"


class VkUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def perform(self, action, text=""):
        if action != "like":
            return False
        self.ctx.click_target(sel=[dict(resourceId=f"{PACKAGE}:id/iv_likes")],
                              at=(0.064, 0.718), timeout=4)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(0.8)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="VK", platform="vk", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("VK не открылся")
    feed.run_feed(ctx, VkUI(ctx, random.Random()), fp)
```

Create `backend/scenarios/gallery/youtube_shorts.py`:

```python
"""YouTube Shorts: смотрит ролики, лайкает по шансу.

Лайк ищется по подписи «Мне нравится / like this video» — подпись зависит от
языка телефона, поэтому запасной вариант — точка справа. Не проверено.
"""
import random

from farm import feed

NAME = "YouTube Shorts: просмотр с лайками"
DESCRIPTION = "Открывает Shorts, смотрит ролики с паузой и ставит лайки по шансу."
PACKAGE = "com.google.android.youtube"
GALLERY = {"platform": "YouTube", "verified": False, "package": PACKAGE}
ALLOWED = ("like",)
PARAMS = {k: v for k, v in feed.feed_params(views=40).items()
          if k in ("profile", "views", "dwell_lo", "dwell_hi", "like", "cap_like", "words")}
LIKE_DESC = "(?i).*(like this video|нравится|лайк).*"


class ShortsUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng

    def open_shorts(self):
        ctx = self.ctx
        ctx.click_if_exists(timeout=4, descriptionMatches="(?i)shorts")

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def perform(self, action, text=""):
        if action != "like":
            return False
        self.ctx.click_target(sel=[dict(descriptionMatches=LIKE_DESC)], at=(0.93, 0.55), timeout=4)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.2)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="YouTube", platform="youtube", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("YouTube не открылся")
    ui = ShortsUI(ctx, random.Random())
    ui.open_shorts()
    feed.run_feed(ctx, ui, fp)
```

Create `backend/scenarios/gallery/telegram_channels.py`:

```python
"""Telegram: читает каналы из списка — открывает, листает посты, выходит.

Ничего не публикует. Поиск канала по названию через значок лупы; названия и
подписи значков зависят от языка телефона. Не проверено.
"""
from farm import story

NAME = "Telegram: чтение каналов"
DESCRIPTION = "Открывает каналы по списку названий, листает посты вверх и возвращается. Ничего не пишет."
PACKAGE = "org.telegram.messenger"
GALLERY = {"platform": "Telegram", "verified": False, "package": PACKAGE}
PARAMS = {
    "channels": {"label": "Каналы (по строке)", "type": "textarea", "default": "",
                 "help": "Название или @имя канала"},
    "scrolls": {"label": "Сколько раз пролистать каждый", "type": "number", "default": 8, "min": 1, "max": 100},
    "rounds": {"label": "Сколько кругов по списку", "type": "number", "default": 1, "min": 1, "max": 20},
}


def run(ctx):
    channels = story.parse_lines(ctx.params["channels"], 100)
    if not channels:
        ctx.fail("список каналов пуст")
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("Telegram не открылся")
    scrolls = int(ctx.params["scrolls"])
    for _ in ctx.loop(times=int(ctx.params["rounds"]), watch=True):
        for name in channels:
            ctx.log(f"канал: {name}")
            ctx.click_target(sel=[dict(descriptionMatches="(?i)(search|поиск)")], at=(0.88, 0.07))
            ctx.sleep(1)
            ctx.type(name, clear=True)
            ctx.sleep(2)
            ctx.click_target(text=[name], timeout=8)
            ctx.sleep(2)
            for _ in range(scrolls):
                ctx.swipe(0.5, 0.35, 0.5, 0.75, 0.4)    # вниз по экрану = к старым постам
                ctx.pause(1.5, 4)
            for _ in range(3):
                ctx.back()
                ctx.sleep(0.6)
```

Create `backend/scenarios/gallery/spotify_listener.py`:

```python
"""Spotify: ищет слово, запускает первый трек, слушает, лайкает по шансу.

Идентификаторы `com.spotify.music:id/...` взяты из скрипта Laixi (версия ver520)
и могут отличаться в вашей версии приложения. Режимы прослушивания: целиком
(пока не сменится название) или диапазон секунд со случайной перемоткой.
"""
import random

from farm import story

NAME = "Spotify: слушатель"
DESCRIPTION = "Ищет слова, запускает первый трек, слушает целиком или заданное время, лайкает по шансу."
PACKAGE = "com.spotify.music"
GALLERY = {"platform": "Spotify", "verified": False, "package": PACKAGE}
ID = PACKAGE + ":id/"
LISTEN_FULL = "Целиком"
LISTEN_RANGE = "Диапазон секунд"
PARAMS = {
    "words": {"label": "Слова поиска (по строке)", "type": "textarea", "default": ""},
    "mode": {"label": "Как слушать", "options": [LISTEN_FULL, LISTEN_RANGE], "default": LISTEN_FULL},
    "range_lo": {"label": "Диапазон от, с", "type": "number", "default": 30, "min": 5},
    "range_hi": {"label": "Диапазон до, с", "type": "number", "default": 90, "min": 6},
    "max_minutes": {"label": "Трек целиком — не дольше, мин", "type": "number", "default": 6, "min": 1, "max": 60},
    "like": {"label": "Шанс лайка, %", "type": "number", "default": 20, "min": 0, "max": 100},
    "cap_like": {"label": "Не больше лайков за сутки", "type": "number", "default": 100, "min": 0},
}


def _center(el):
    left, top, right, bottom = el.bounds()
    return (left + right) // 2, (top + bottom) // 2


def search(ctx, word):
    ctx.click_target(sel=[dict(resourceId=ID + "search_tab")], timeout=8)
    ctx.click_target(sel=[dict(resourceId=ID + "find_search_field")], timeout=8)
    ctx.set_text(word, timeout=8, resourceId=ID + "query")
    ctx.pause(2, 5)
    return ctx.exists(timeout=4, resourceId=ID + "search_body")


def open_first_track(ctx):
    row = ctx.find(timeout=4, resourceId=ID + "row_root")
    if row is None:
        return False
    x, y = _center(row)
    ctx.tap(x - 200, y)       # левее «⋯», чтобы не открыть меню строки
    ctx.pause(1, 3)
    return True


def maybe_like(ctx, rate, cap):
    if cap > 0 and ctx.chance(rate):
        ctx.budget("Spotify: лайки", cap, "spotify")
        ctx.click_target(sel=[dict(resourceId=ID + "add_to_button")], timeout=4)
        ctx.sleep(1)
        if "PageActivity" in ctx.shell("dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'"):
            ctx.back()     # открылся список плейлистов — лайк уже поставлен


def listen_full(ctx, max_minutes):
    title = ctx.find(timeout=3, resourceId=ID + "track_info_view_title")
    if title is None:
        ctx.log("название трека не нашёл — слушаю 60 секунд")
        ctx.sleep(60)
        return
    first = title.get_text()
    for _ in range(int(max_minutes * 30)):               # опрос раз в 2 с
        ctx.sleep(2)
        now = ctx.find(timeout=2, resourceId=ID + "track_info_view_title")
        if now is not None and now.get_text() != first:
            ctx.log("трек сменился — следующее слово")
            return
    ctx.log("трек не сменился за лимит времени — иду дальше")


def listen_range(ctx, lo, hi, rng):
    ctx.click_target(sel=[dict(resourceId=ID + "cover_image")], timeout=4)
    ctx.sleep(1)
    total = rng.randint(int(lo), int(hi))
    bar = ctx.find(timeout=2, resourceId=ID + "seekbar", className="android.widget.SeekBar") \
        if ctx.chance(40) else None
    plan = story.seek_plan(total, 3, 8, rng)
    ctx.log(f"слушаю {total} с" + (", с перемоткой" if bar is not None else ""))
    for step in plan:
        if bar is not None:
            left, top, right, bottom = bar.bounds()
            y = (top + bottom) // 2
            ctx.swipe(rng.randint(left, right), y, rng.randint(left, right), y, 0.9)
        ctx.sleep(step)
    ctx.back()


def run(ctx):
    words = story.parse_lines(ctx.params["words"], 200)
    if not words:
        ctx.fail("список слов пуст")
    if ctx.params["mode"] == LISTEN_RANGE and float(ctx.params["range_lo"]) >= float(ctx.params["range_hi"]):
        ctx.fail("Диапазон «от» должен быть меньше «до»")
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("Spotify не открылся")
    rng = random.Random()
    rate = float(ctx.params["like"])
    cap = int(ctx.params["cap_like"])
    for i, word in enumerate(words, 1):
        ctx.log(f"слово {i} из {len(words)}: «{word}»")
        if not search(ctx, word) or not open_first_track(ctx):
            ctx.log("результатов нет — следующее слово")
            continue
        maybe_like(ctx, rate, cap)
        if ctx.params["mode"] == LISTEN_RANGE:
            listen_range(ctx, ctx.params["range_lo"], ctx.params["range_hi"], rng)
        else:
            listen_full(ctx, float(ctx.params["max_minutes"]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_gallery_scenarios.py -q`
Expected: all PASS.

Note for the implementer: `test_feed_scenarios_accept_default_form` reads `mod.ALLOWED`; `vk_feed`/`youtube_shorts` keep it as `("like",)`. `PARAMS["views"]["label"] = ...` in `vk_feed.py` mutates a fresh dict returned by `feed_params`, so shared state is not affected.

- [ ] **Step 5: Commit**

```bash
git add backend/scenarios/gallery backend/tests/test_gallery_scenarios.py
git commit -m "Готовые сюжеты: TikTok, автолистание, Spotify, VK, Telegram, YouTube Shorts"
```

---

### Task 7: вкладка «Готовые» в интерфейсе

Новая вкладка раздела «Сценарии»: карточки, значок «Не проверено на телефоне», кнопка «Добавить в мои».

**Files:**
- Create: `frontend/js/gallery.js`, `frontend/css/gallery.css`, `backend/tests/test_gallery_js.py`
- Modify: `frontend/index.html` (три панели вкладок + новый `<section id="view-gallery">` + подключение css/js), `frontend/js/app.js` (`VIEWS`, `navName`, вызов `galleryShow()`), `frontend/strings/ru.json`

**Interfaces:**
- Consumes: `api(path, opts)` (как в `apklib.js`), `toast(msg, kind)`, `t(key, vars)`, `esc`, `$`, `setText`, `showView`, `S.scenario`, `loadScenarios` (`loadScenarios(reload)` в `scenarios.js` перечитывает список «Моих»).
- Produces: `galleryShow()`, `galleryRender()`, `galleryAdd(key)`, `galleryCard(item) -> html` (чистая, для теста).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gallery_js.py`:

```python
"""Карточка галереи: отрисовка, значок «не проверено», состояние «уже в моих»."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "gallery.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
  esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),
  t: (k, v) => k + (v ? JSON.stringify(v) : ''),
};
vm.createContext(ctx);
vm.runInContext(src + ';this.card=galleryCard', ctx);
const item = {key: 'tiktok_feed', name: 'TikTok <лента>', description: 'Листает', platform: 'TikTok',
              verified: false, package: 'com.x', added: false};
let html = ctx.card(item);
assert.ok(html.includes('TikTok &lt;лента&gt;'), 'имя экранируется');
assert.ok(html.includes('gallery.ne_proveren'), 'значок «не проверено»');
assert.ok(html.includes("galleryAdd('tiktok_feed')"), 'кнопка добавления');
assert.ok(!html.includes('gallery.uzhe_v_moih'));
html = ctx.card({...item, verified: true, added: true});
assert.ok(!html.includes('gallery.ne_proveren'));
assert.ok(html.includes('gallery.uzhe_v_moih'));
assert.ok(!html.includes("galleryAdd('tiktok_feed')"));
"""


def test_gallery_card():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_gallery_js.py -q`
Expected: FAIL (`gallery.js` не существует).

- [ ] **Step 3: Implement**

Create `frontend/js/gallery.js`:

```javascript
'use strict';

/* Галерея готовых сюжетов: вкладка раздела «Сценарии». Карточка показывает,
   проверен ли сюжет на телефоне; «Добавить в мои» копирует файл в «Мои». */

const GALLERY = {list: null};

async function galleryShow() {
    galleryRender();
    try {
        GALLERY.list = await api('/api/gallery');
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    galleryRender();
}

function galleryCard(item) {
    const badge = item.verified ? '' :
        `<span class="gal-badge" title="${esc(t('gallery.ne_proveren_d'))}">${esc(t('gallery.ne_proveren'))}</span>`;
    const action = item.added
        ? `<span class="gal-done">${esc(t('gallery.uzhe_v_moih'))}</span>`
        : `<button class="sm accent" onclick="galleryAdd('${esc(item.key)}')">${esc(t('gallery.dobavit'))}</button>`;
    return `<article class="gal-card">
        <header><b>${esc(item.name)}</b><span class="gal-plat">${esc(item.platform)}</span></header>
        <p>${esc(item.description)}</p>
        <footer>${badge}<span class="sp"></span>${action}</footer>
      </article>`;
}

function galleryRender() {
    const box = $('galList');
    if (!box) return;
    const list = GALLERY.list;
    if (!list) return;
    if (!list.length) {
        box.innerHTML = `<div class="apk-empty"><h3>${esc(t('gallery.pusto'))}</h3><p>${esc(t('gallery.pusto_d'))}</p></div>`;
        return;
    }
    box.innerHTML = `<div class="gal-grid">${list.map(galleryCard).join('')}</div>`;
}

async function galleryAdd(key) {
    try {
        await api(`/api/gallery/${encodeURIComponent(key)}/add`, {method: 'POST'});
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    toast(t('gallery.dobavlen'), 'ok');
    await loadScenarios(true);
    GALLERY.list = await api('/api/gallery');
    galleryRender();
}
```

Create `frontend/css/gallery.css`:

```css
/* Галерея готовых сюжетов (gallery.js). */
.gal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--s3);
    padding: var(--s3) var(--s4);
}

.gal-card {
    display: flex;
    flex-direction: column;
    gap: var(--s2);
    padding: var(--s3);
    border: 1px solid var(--line-soft);
    border-radius: var(--r2);
    background: var(--panel);
}

.gal-card header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s2);
}

.gal-card p {
    margin: 0;
    color: var(--dim);
}

.gal-card footer {
    display: flex;
    align-items: center;
    gap: var(--s2);
    margin-top: auto;
}

.gal-plat {
    color: var(--dim);
    font-size: 0.85em;
}

.gal-badge {
    padding: 2px var(--s2);
    border-radius: var(--r2);
    background: var(--panel2);
    color: var(--dim);
    font-size: 0.85em;
}

.gal-done {
    color: var(--dim);
}
```

`frontend/index.html`:
1. В `<head>` рядом с `css/apklib.css`: `<link rel="stylesheet" href="css/gallery.css">`.
2. В трёх панелях вкладок (внутри `view-scen`, `view-apps`, `view-schedule` — ищите `data-t="apk.tab_raspisanie"`) после кнопки «Расписание» добавить кнопку (в панели самой галереи у неё класс `on`, `aria-selected="true"`, в остальных — `aria-selected="false"`):

```html
<button class="sm" role="tab" aria-selected="false"
        onclick="showView('gallery')"><span data-t="gallery.tab">Готовые</span></button>
```
3. После секции `view-apps` добавить:

```html
    <!-- Готовые сюжеты: вкладка «Сценариев». «Добавить в мои» копирует файл
         из backend/scenarios/gallery в обычный список. -->
    <section class="view" id="view-gallery" aria-label="Готовые сюжеты" data-t-aria-label="gallery.razdel">
        <div class="bar">
            <div class="seg runs-seg" role="tablist" aria-label="Сценарии и приложения" data-t-aria-label="apk.stsenarii_tabs">
                <button class="sm" role="tab" aria-selected="false"
                        onclick="showView('scen')"><span data-t="apk.tab_stsenarii">Сценарии</span><b class="tab-n" data-count="scen"></b></button>
                <button class="sm" role="tab" aria-selected="false"
                        onclick="showView('apps')"><span data-t="apk.tab_prilozheniya">Приложения</span><b class="tab-n" data-count="apps"></b></button>
                <button class="sm" role="tab" aria-selected="false"
                        onclick="showView('schedule')"><span data-t="apk.tab_raspisanie">Расписание</span></button>
                <button class="sm on" role="tab" aria-selected="true"
                        onclick="showView('gallery')"><span data-t="gallery.tab">Готовые</span></button>
            </div>
        </div>
        <div class="scroll" id="galList"></div>
    </section>
```
4. Перед `js/app.js`: `<script src="js/gallery.js"></script>`.

`frontend/js/app.js`:
- `const VIEWS = [..., 'apps', 'gallery', ...];`
- `const navName = (name === 'apps' || name === 'schedule' || name === 'gallery') ? 'scen' : name;`
- после `if (name === 'apps') apkShow();` добавить `if (name === 'gallery') galleryShow();`

`frontend/strings/ru.json` — добавить (в алфавитном порядке ключей, как в файле):

```json
"gallery.dobavit": "Добавить в мои",
"gallery.dobavlen": "Сюжет добавлен в «Мои» — найдите его на вкладке «Сценарии»",
"gallery.ne_proveren": "Не проверено на телефоне",
"gallery.ne_proveren_d": "Селекторы взяты из рабочего скрипта, но на вашем парке не прогонялись. Запустите на одном телефоне, прежде чем на всех",
"gallery.pusto": "Готовых сюжетов пока нет",
"gallery.pusto_d": "Положите файлы сюжетов в папку backend/scenarios/gallery",
"gallery.razdel": "Готовые сюжеты",
"gallery.tab": "Готовые",
"gallery.uzhe_v_moih": "Уже в моих",
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_gallery_js.py tests/test_strings.py tests/test_param_field_js.py -q`
Expected: all PASS. Затем вручную: `./run.sh`, открыть «Сценарии → Готовые», убедиться, что видно шесть карточек, «Добавить в мои» переносит сюжет в «Сценарии».

- [ ] **Step 5: Commit**

```bash
git add frontend/js/gallery.js frontend/css/gallery.css frontend/index.html frontend/js/app.js frontend/strings/ru.json backend/tests/test_gallery_js.py
git commit -m "Интерфейс: вкладка «Готовые» с карточками и «Добавить в мои»"
```

---

### Task 8: документация

**Files:**
- Modify: `README.md` (таблица «Что умеет»), `docs/guide.md` (новый раздел «Готовые сюжеты»), `.claude/skills/farm-ux/SKILL.md` (строка в «LaiXi parity checklist»)

- [ ] **Step 1: Edit**

`README.md`: в таблицу «Что умеет» добавить строку:

```
| **Готовые сюжеты** — лента TikTok, шортсы, Spotify, VK, Telegram, YouTube со своими шансами и потолком за сутки | **Галерея** — «Сценарии → Готовые»: «Добавить в мои», пометка «не проверено на телефоне» |
```

`docs/guide.md`: добавить раздел «Готовые сюжеты» с тремя абзацами: что в галерее, как добавить («Сценарии → Готовые → Добавить в мои»), что значат профили Тихий/Обычный/Активный (таблица шансов из `story.PROFILES`), почему есть потолок за сутки, как положить свой сюжет (файл в `backend/scenarios/gallery/` с `NAME`, `DESCRIPTION`, `GALLERY`), и что «не проверено» снимается строкой `verified = True` в файле.

`.claude/skills/farm-ux/SKILL.md`, в «LaiXi parity checklist» перед строкой `Added 2026-10-20:` добавить:

```
Added 2026-10-25: «Готовые» сюжеты (Сценарии → Готовые; `gallery.py`, `scenarios/gallery/`, движок `feed.py`, логика `story.py`) — вернули шаблоны, убранные 2026-10-17, но без слепых тапов: структурные селекторы + запасные цели + пометка «не проверено», потолок за сутки по умолчанию.
```

- [ ] **Step 2: Run the whole suite**

Run: `cd backend && python -m pytest -q`
Expected: all PASS (≈870+ тестов).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/guide.md .claude/skills/farm-ux/SKILL.md
git commit -m "Документация: готовые сюжеты и галерея"
```

---

## Self-Review

**Spec coverage (часть 1):** `story.py` — T1; профили, `validate`, `dwell_left`, `seek_plan`, `Tally` — T1; структурные селекторы TikTok — T2; движок (бюджет времени, микропаузы, порядок, нет панели → смотрит, потолок, смена слова не на первом видео) — T3; поле многострочного ввода для слов и фраз — T4; галерея (API, карточки, копирование, коллизия имён, изоляция от `discover`) — T5; шесть сюжетов — T6; вкладка «Готовые» и значок «Не проверено» — T7; документация, запись в `farm-ux` — T8. «Профили поведения», «файл слов» (многострочное поле), «живая сводка» (`Tally.line` каждые 5 видео и итог) — покрыты T1/T3/T4.

**Отступление от спеки, зафиксированное здесь:** загрузка `.txt`-файлом для слов не делается, вместо неё многострочное поле (спека допускала это: «если её для параметров нет, остаётся многострочное поле»).

**Placeholder scan:** шаблонных заглушек нет.

**Type consistency:** `feed.feed_params`, `FeedParams(views, profile, words, comments, caps, label, platform, allowed)`, `from_params(..., allowed, need_actions)`, `run_feed(ctx, ui, fp, rng, clock)`, `FeedUI.perform(action, text)` одинаковы в T3 и T6. `structure.*` в T6 совпадают с T2. `gallery.items()/add()` и `api.gallery.list_gallery()/add_to_mine()` совпадают в T5 и тестах.
