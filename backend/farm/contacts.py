"""Контакты пакетом: номера, разбор файла и shell-скрипты для телефона.

Чистый модуль. Номера и имена проходят через жёсткую очистку: в shell
телефона попадает только то, что мы собрали из безопасных символов, а не
строка пользователя как есть. Запись идёт через `content insert` в базу
контактов; не все прошивки это разрешают, поэтому отказ телефона — понятное
сообщение по этому телефону, а не падение всей пачки.
"""
from __future__ import annotations

import random
import re

MAX_ITEMS = 2000
MAX_GENERATE = 1000
_DIGITS = re.compile(r"[^\d+]", re.A)
_NAME_BAD = re.compile(r"[^\w .\-]", re.U)   # имена могут быть кириллицей: без ASCII
_NUMBER = re.compile(r"^\+?\d{7,15}$", re.A)
RAW = "content://com.android.contacts/raw_contacts"
DATA = "content://com.android.contacts/data"
CLEAR_SCRIPT = f"content delete --uri {DATA}; content delete --uri {RAW}"
_DENIED = ("securityexception", "permission denial", "permission denied", "exception occurred", "error:")


def _clean_number(raw: str):
    num = _DIGITS.sub("", raw or "")
    if num.count("+") > 1 or ("+" in num and not num.startswith("+")):
        return None
    return num if _NUMBER.match(num) else None


def _clean_name(raw: str, fallback: str) -> str:
    name = _NAME_BAD.sub("", raw or "").strip()[:40]
    return name or fallback


def generate(prefix: str, length: int, count: int, rng=None) -> list:
    """`count` разных номеров длиной `length` цифр с общим началом `prefix`."""
    rng = rng or random
    prefix = (prefix or "").strip()
    if not re.fullmatch(r"\+?\d{1,10}", prefix):
        raise ValueError("начало номера — цифры, можно с плюсом в начале")
    length, count = int(length), int(count)
    if not 7 <= length <= 15:
        raise ValueError("длина номера — от 7 до 15 цифр")
    if not 1 <= count <= MAX_GENERATE:
        raise ValueError(f"количество — от 1 до {MAX_GENERATE}")
    free = length - len(prefix.lstrip("+"))
    if free < 1:
        raise ValueError("начало номера уже такой длины, как весь номер")
    if count > 10 ** free:
        raise ValueError(f"после начала остаётся {free} цифр — столько разных номеров не набрать")
    seen = set()
    while len(seen) < count:
        seen.add(prefix + "".join(rng.choice("0123456789") for _ in range(free)))
    return sorted(seen)


def parse_file(text: str):
    """Строки «номер» или «имя;номер» / «имя, номер» → контакты. Негодные строки считаются."""
    items, skipped = [], 0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"[;,\t]", line, maxsplit=1)
        number = _clean_number(parts[-1])
        if number is None:
            skipped += 1
            continue
        name = _clean_name(parts[0], number) if len(parts) == 2 else number
        items.append({"name": name, "number": number})
        if len(items) >= MAX_ITEMS:
            break
    return items, skipped


def _one(name: str, number: str) -> str:
    return (
        f"content insert --uri {RAW} --bind account_type:n: --bind account_name:n:; "
        f"RID=$(content query --uri {RAW} --projection _id --sort '_id DESC' | head -n 1 | sed 's/.*_id=\\([0-9]*\\).*/\\1/'); "
        f"content insert --uri {DATA} --bind raw_contact_id:i:$RID "
        f"--bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:'{name}'; "
        f"content insert --uri {DATA} --bind raw_contact_id:i:$RID "
        f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:'{number}' --bind data2:i:2"
    )


def insert_scripts(items, chunk: int = 15) -> list:
    """Скрипты по `chunk` контактов: десять вызовов adb вместо сотни."""
    safe = []
    for item in items:
        number = _clean_number(item.get("number"))
        if number:
            safe.append((_clean_name(item.get("name"), number), number))
    return ["; ".join(_one(n, p) for n, p in safe[i:i + chunk]) for i in range(0, len(safe), chunk)]


def check_output(out: str) -> None:
    low = (out or "").lower()
    if any(mark in low for mark in _DENIED):
        raise RuntimeError("этот телефон не даёт писать контакты через adb — "
                           "добавьте их на нём вручную или импортом файла .vcf")
