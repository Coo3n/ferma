"""Тонкая обёртка над adb. Никакой магии — просто безопасный вызов бинарника."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import config

log = logging.getLogger("farm.adb")

# .deps/ — куда run.sh / run.bat сами скачивают platform-tools, если adb нет.
_DEPS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     ".deps", "platform-tools")

_ADB_CANDIDATES = [
    os.getenv("ADB_PATH", ""),
    "adb",
    os.path.join(_DEPS, "adb.exe" if os.name == "nt" else "adb"),
    "/opt/homebrew/bin/adb",
    "/usr/local/bin/adb",
    os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    # Windows: Android Studio ставит SDK сюда, platform-tools — отдельной папкой
    os.path.join(os.getenv("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe")
    if os.getenv("LOCALAPPDATA") else "",
    r"C:\platform-tools\adb.exe",
]


def adb_path() -> str:
    for cand in _ADB_CANDIDATES:
        if not cand:
            continue
        found = shutil.which(cand) if not os.path.sep in cand else (cand if os.path.exists(cand) else None)
        if found:
            return found
    return "adb"


ADB = adb_path()

# Как поставить adb — своими словами для каждой системы.
_ADB_HINT = ("Запустите run.bat — он скачает adb сам, или поставьте Platform-Tools: "
             "https://developer.android.com/tools/releases/platform-tools") if os.name == "nt" else (
             "Запустите ./run.sh — он скачает adb сам, или: brew install --cask android-platform-tools")


class AdbError(RuntimeError):
    pass


def _exec(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    cmd = [ADB] + args
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout if timeout is not None else config.ADB_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise AdbError(f"adb не найден ({ADB}). {_ADB_HINT}") from e
    except subprocess.TimeoutExpired as e:
        raise AdbError(f"adb таймаут: {' '.join(args)}") from e


def _run(args: list[str], timeout: float | None = None, binary: bool = False):
    p = _exec(args, timeout=timeout)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip() or p.stdout.decode("utf-8", "replace").strip()
        raise AdbError(f"adb {' '.join(args)} -> rc={p.returncode}: {err}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def _run_soft(args: list[str], timeout: float | None = None) -> tuple[int, str]:
    """Как `_run`, но без исключений: (код возврата, весь вывод).

    Нужен для `connect`/`disconnect`: часть сборок adb сообщает об отказе
    текстом при rc=0, часть — ненулевым кодом. Решение принимает вызывающий,
    а не механика запуска.
    """
    try:
        p = _exec(args, timeout=timeout)
    except AdbError as e:
        return 1, str(e)
    parts = [s.decode("utf-8", "replace").strip() for s in (p.stdout, p.stderr)]
    return p.returncode, "\n".join(s for s in parts if s)


def raw(args: list[str], serial: str | None = None, timeout: float | None = None, binary: bool = False):
    """Произвольная команда adb, опционально для конкретного устройства."""
    pre = ["-s", serial] if serial else []
    return _run(pre + args, timeout=timeout, binary=binary)


def shell(serial: str, cmd: str | list[str], timeout: float | None = None) -> str:
    args = ["shell"] + (cmd if isinstance(cmd, list) else [cmd])
    return raw(args, serial=serial, timeout=timeout)


def exec_out(serial: str, cmd: str | list[str], timeout: float | None = None) -> bytes | str:
    """exec-out — для бинарных данных (screencap -p и т.п.), без порчи \\r\\n."""
    args = ["exec-out"] + (cmd if isinstance(cmd, list) else [cmd])
    return raw(args, serial=serial, timeout=timeout, binary=True)


def version() -> str:
    try:
        return _run(["--version"], timeout=10).strip().splitlines()[0]
    except AdbError as e:
        return f"недоступен: {e}"


def start_server() -> None:
    try:
        _run(["start-server"], timeout=30)
    except AdbError as e:
        log.warning("start-server: %s", e)


def kill_server() -> None:
    try:
        _run(["kill-server"], timeout=30)
    except AdbError as e:
        log.warning("kill-server: %s", e)


def reconnect_offline() -> bytes | str:
    try:
        return _run(["reconnect", "offline"], timeout=30)
    except AdbError as e:
        return str(e)


# ---------- устройства по TCP ----------

DEFAULT_TCP_PORT = 5555

# host:port, где host — имя, IPv4 или IPv6 в скобках. Серийник USB-устройства
# двоеточия не содержит, поэтому одного этого шаблона хватает, чтобы отличить
# сетевую плату от телефона на проводе.
_NET_SERIAL = re.compile(r"^(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9][A-Za-z0-9.\-]*):(\d{1,5})$")
_HOST_ONLY = re.compile(r"^(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9][A-Za-z0-9.\-]*)$")


def is_network_serial(serial: str) -> bool:
    """`192.168.1.50:5555` — да, `emulator-5554` и голый серийник — нет."""
    m = _NET_SERIAL.match(serial)
    return bool(m) and 0 < int(m.group(1)) <= 65535


def normalize_target(address: str, default_port: int = DEFAULT_TCP_PORT) -> str:
    """Привести адрес платы к виду `host:port`. Мусор — ValueError.

    Порт можно не писать: без него подставляется штатный 5555.
    """
    text = (address or "").strip()
    if not text:
        raise ValueError("пустой адрес")
    if text.startswith("tcp://"):
        text = text[len("tcp://"):]
    text = text.rstrip("/")

    if _HOST_ONLY.match(text):
        text = f"{text}:{default_port}"
    if not is_network_serial(text):
        raise ValueError(f"не похоже на адрес устройства: {address!r} (ожидается host или host:port)")
    return text


def connect(target: str, timeout: float | None = None) -> tuple[bool, str]:
    """`adb connect host:port` → (получилось, сообщение adb)."""
    rc, out = _run_soft(["connect", target], timeout=timeout)
    text = out or ("нет ответа" if rc == 0 else f"adb connect -> rc={rc}")
    ok = rc == 0 and ("connected to" in out)  # покрывает и "already connected to"
    return ok, text


def disconnect(target: str, timeout: float | None = None) -> tuple[bool, str]:
    """`adb disconnect host:port`. Отсутствие такого подключения — не ошибка."""
    rc, out = _run_soft(["disconnect", target], timeout=timeout)
    return rc == 0, out or "отключено"


def tcpip(serial: str, port: int = DEFAULT_TCP_PORT, timeout: float = 20) -> str:
    """Перевести устройство на проводе в режим adb-по-TCP.

    Демон adbd на устройстве перезапускается, поэтому USB-подключение на
    секунду-другую отваливается — это штатно.
    """
    return raw(["tcpip", str(port)], serial=serial, timeout=timeout).strip()


# "    inet 192.168.1.50/24 brd 192.168.1.255 scope global wlan0"
_INET = re.compile(r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)/\d+.*?\s(\S+)\s*$", re.M)
# "inet addr:192.168.1.50  Bcast:..." — старый ifconfig, имя интерфейса выше по блоку
_IFCONFIG = re.compile(r"^(\S+)[\s\S]*?inet addr:(\d+\.\d+\.\d+\.\d+)", re.M)


def _iface_rank(name: str) -> int:
    """Чем меньше, тем нужнее. Плату ищем на витой паре, телефон — на Wi-Fi."""
    if name.startswith("eth") or name.startswith("enp") or name.startswith("en"):
        return 0
    if name.startswith("wlan") or name.startswith("wl"):
        return 1
    if name.startswith(("lo", "rmnet", "tun", "dummy", "p2p", "ap")):
        return 9
    return 5


def device_ip(serial: str) -> str:
    """IPv4 устройства в локальной сети. Пусто — значит не нашли."""
    candidates: list[tuple[int, str]] = []
    try:
        out = shell(serial, ["ip", "-f", "inet", "addr", "show"], timeout=10)
    except AdbError:
        out = ""
    for ip, iface in _INET.findall(out):
        if not ip.startswith("127."):
            candidates.append((_iface_rank(iface), ip))

    if not candidates:
        try:
            out = shell(serial, ["ifconfig"], timeout=10)
        except AdbError:
            out = ""
        for iface, ip in _IFCONFIG.findall(out):
            if not ip.startswith("127."):
                candidates.append((_iface_rank(iface), ip))

    if not candidates:
        return ""
    candidates.sort()
    rank, ip = candidates[0]
    return "" if rank >= 9 else ip


@dataclass
class AdbDevice:
    serial: str
    state: str  # device | offline | unauthorized | ...
    props: dict[str, str] = field(default_factory=dict)

    @property
    def model(self) -> str:
        return self.props.get("model", "").replace("_", " ") or self.serial

    @property
    def is_online(self) -> bool:
        return self.state == "device"


_LINE = re.compile(r"^(\S+)\s+(\S+)(.*)$")
# USB-серийник, emulator-5554, host:port, [v6]:port, mDNS adb-XXX._adb-tls-connect._tcp
_SAFE_SERIAL = re.compile(r"^[A-Za-z0-9._:\-\[\]@%+]{1,128}$")
_rejected: set[str] = set()


def is_safe_serial(serial: str) -> bool:
    return bool(_SAFE_SERIAL.match(serial or ""))


def list_devices() -> list[AdbDevice]:
    """Разбор `adb devices -l`. Не бросает исключений — при сбое вернёт пустой список."""
    try:
        out = raw(["devices", "-l"], timeout=15)
    except AdbError as e:
        log.warning("list_devices: %s", e)
        return []

    devices: list[AdbDevice] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        serial, state, rest = m.group(1), m.group(2), m.group(3)
        if not is_safe_serial(serial):
            # Серийник сообщает само устройство (или mDNS в сети). Он попадает
            # в HTML интерфейса, в onclick-строки и в аргументы adb, поэтому
            # кавычки, < > и прочее — признак подделки, а не телефона.
            if serial not in _rejected:
                _rejected.add(serial)
                log.warning("устройство с недопустимым серийником пропущено: %r", serial[:80])
            continue
        props: dict[str, str] = {}
        for token in rest.split():
            if ":" in token:
                k, _, v = token.partition(":")
                props[k] = v
        devices.append(AdbDevice(serial=serial, state=state, props=props))
    return devices


def getprop(serial: str, name: str, default: str = "") -> str:
    try:
        return shell(serial, ["getprop", name], timeout=10).strip() or default
    except AdbError:
        return default


def battery(serial: str) -> dict:
    """level (%), temperature (°C), status, plugged."""
    out = {}
    try:
        raw_out = shell(serial, ["dumpsys", "battery"], timeout=10)
    except AdbError:
        return out
    for line in raw_out.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.strip().partition(":")
        k, v = k.strip(), v.strip()
        if k == "level" and v.isdigit():
            out["level"] = int(v)
        elif k == "temperature" and v.lstrip("-").isdigit():
            out["temperature"] = int(v) / 10.0
        elif k == "status" and v.isdigit():
            out["status"] = {1: "unknown", 2: "charging", 3: "discharging", 4: "not charging", 5: "full"}.get(int(v), v)
        elif k in ("AC powered", "USB powered") and v == "true":
            out["plugged"] = k.split()[0]
    return out


_LOCK_RE = re.compile(r"\b(mshowinglockscreen|iskeyguardshowing|mkeyguardshowing|mdreaminglockscreen)=(true|false)")
_KG_SHOWING = re.compile(r"^showing=(true|false)\b")


def parse_screen_state(out: str) -> dict:
    """Вывод dumpsys power/window → {"on", "locked", "known"}.

    on — экран горит. Always On Display (Samsung, Xiaomi) — это Dozing /
    Display Power: state=DOZE: часы на чёрном, пользоваться нельзя — считаем
    выключенным. locked — висит экран блокировки: AOSP пишет «showing=» в
    блоке KeyguardServiceDelegate (One UI и MIUI/HyperOS его сохраняют),
    старые прошивки — mShowingLockscreen, новые activity-дампы —
    mKeyguardShowing. «showing=» вне блока Keyguard не считаем: такие строки
    бывают у других частей системы. known — нашлась ли хоть одна строка
    про питание экрана (нет — grep на телефоне не сработал).
    """
    on = None
    locked = False
    kg_indent = None   # отступ заголовка KeyguardServiceDelegate, пока внутри блока
    for line in out.splitlines():
        s = line.strip()
        low = s.lower()
        indent = len(line) - len(line.lstrip())
        if "keyguardservicedelegate" in low:
            kg_indent = indent
            continue
        if kg_indent is not None and s and indent <= kg_indent:
            kg_indent = None   # блок кончился: дальше чужие «showing=»
        if s.startswith("mWakefulness="):
            on = s.split("=", 1)[1].strip().lower() == "awake"
        elif s.startswith("Display Power: state=") and on is None:
            on = s.rsplit("=", 1)[1].strip().upper() == "ON"
        m = _LOCK_RE.search(low)
        if m and m.group(2) == "true":
            locked = True
        m = _KG_SHOWING.match(low)
        if m and kg_indent is not None and m.group(1) == "true":
            locked = True
    return {"on": True if on is None else on, "locked": locked, "known": on is not None}


SCREEN_STATE_CMD = (
    "dumpsys power | grep -E 'mWakefulness=|Display Power: state='; "
    "dumpsys window policy | grep -iE 'keyguardservicedelegate|^ *showing=|lockscreen=|keyguardshowing'")


def screen_state(serial: str) -> dict | None:
    """Горит ли экран и заблокирован ли телефон. None — узнать не удалось."""
    try:
        state = parse_screen_state(shell(serial, SCREEN_STATE_CMD, timeout=5))
        if not state["known"]:
            # Прошивка без grep -E (старые MIUI) — разбираем дампы целиком.
            state = parse_screen_state(
                shell(serial, "dumpsys power; dumpsys window policy", timeout=8))
    except AdbError:
        return None
    return {"on": state["on"], "locked": state["locked"]} if state["known"] else None


_WM_SIZE = re.compile(r"(\d+)x(\d+)")


def screen_size(serial: str) -> tuple[int, int] | None:
    try:
        out = shell(serial, ["wm", "size"], timeout=10)
    except AdbError:
        return None
    # "Physical size: 1080x2400" / может быть ещё "Override size: ..."
    override = None
    physical = None
    for line in out.splitlines():
        m = _WM_SIZE.search(line)
        if not m:
            continue
        val = (int(m.group(1)), int(m.group(2)))
        if "Override" in line:
            override = val
        elif "Physical" in line:
            physical = val
    return override or physical


def current_app(serial: str) -> str:
    """Пакет приложения на переднем плане (без root)."""
    for cmd in (
            ["dumpsys", "activity", "activities"],
            ["dumpsys", "window", "windows"],
    ):
        try:
            out = shell(serial, cmd, timeout=12)
        except AdbError:
            continue
        m = re.search(r"(?:mCurrentFocus|mResumedActivity|topResumedActivity).*?([a-zA-Z][\w\.]+)/([\w\.\$]+)", out)
        if m:
            return m.group(1)
    return ""


def list_packages(serial: str, third_party_only: bool = True) -> list[str]:
    args = ["pm", "list", "packages"]
    if third_party_only:
        args.append("-3")
    try:
        out = shell(serial, args, timeout=20)
    except AdbError:
        return []
    return sorted(l.strip().replace("package:", "") for l in out.splitlines() if l.strip().startswith("package:"))


def screencap_png(serial: str, timeout: float = 15) -> bytes | str:
    return exec_out(serial, ["screencap", "-p"], timeout=timeout)
