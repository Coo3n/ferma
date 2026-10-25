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
