"""Сетевые устройства: разбор адресов, `adb connect` и сторож.

Здесь ни одного живого adb: важна не сама команда, а решения вокруг неё —
кого дёргать, кого пропустить и как долго ждать после отказа.
"""
import time

import pytest

from farm import adb, config
from farm.devices import network as netmod
from farm.devices.network import CONNECTED, DISABLED, FAILED, PENDING, NetworkDevices


# ---------------------------------------------------------------- адреса

@pytest.mark.parametrize("сырой,ожидание", [
    ("192.168.1.50", "192.168.1.50:5555"),
    ("192.168.1.50:5037", "192.168.1.50:5037"),
    ("  10.0.0.7  ", "10.0.0.7:5555"),
    ("tcp://10.0.0.7:5555", "10.0.0.7:5555"),
    ("board-01.local", "board-01.local:5555"),
    ("[fe80::1]:5555", "[fe80::1]:5555"),
])
def test_адрес_приводится_к_host_port(сырой, ожидание):
    assert adb.normalize_target(сырой) == ожидание


@pytest.mark.parametrize("мусор", ["", "   ", ":5555", "192.168.1.50:0", "192.168.1.50:70000",
                                   "192.168.1.50:abc", "a b:5555"])
def test_кривой_адрес_отвергается(мусор):
    with pytest.raises(ValueError):
        adb.normalize_target(мусор)


@pytest.mark.parametrize("серийник,сетевой", [
    ("192.168.1.50:5555", True),
    ("[fe80::1]:5555", True),
    ("emulator-5554", False),
    ("79AULJHYVCKRKF5L", False),
    ("192.168.1.50:99999", False),
])
def test_сетевой_серийник_отличается_от_usb(серийник, сетевой):
    assert adb.is_network_serial(серийник) is сетевой


# ------------------------------------------------------------ adb connect

@pytest.mark.parametrize("rc,вывод,успех", [
    (0, "connected to 192.168.1.50:5555", True),
    (0, "already connected to 192.168.1.50:5555", True),
    (1, "failed to connect to '192.168.1.50:5555': Connection refused", False),
    (0, "failed to connect to 192.168.1.50:5555", False),
    (1, "adb таймаут: connect 192.168.1.50:5555", False),
])
def test_ответ_adb_connect_разбирается(monkeypatch, rc, вывод, успех):
    """adb сообщает об отказе то кодом возврата, то текстом — учитываем оба."""
    monkeypatch.setattr(adb, "_run_soft", lambda args, timeout=None: (rc, вывод))
    ok, message = adb.connect("192.168.1.50:5555")
    assert ok is успех
    assert message == вывод


def test_пустой_ответ_connect_не_считается_успехом(monkeypatch):
    monkeypatch.setattr(adb, "_run_soft", lambda args, timeout=None: (0, ""))
    ok, message = adb.connect("192.168.1.50:5555")
    assert ok is False
    assert message


# ----------------------------------------------------------------- IP платы

def test_ip_берётся_с_проводного_интерфейса(monkeypatch):
    вывод = (
        "1: lo    inet 127.0.0.1/8 scope host lo\n"
        "    inet 192.168.1.77/24 brd 192.168.1.255 scope global wlan0\n"
        "    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0\n"
    )
    monkeypatch.setattr(adb, "shell", lambda *a, **k: вывод)
    assert adb.device_ip("board") == "192.168.1.50"


def test_ip_падает_на_wifi_если_провода_нет(monkeypatch):
    вывод = "    inet 192.168.1.77/24 brd 192.168.1.255 scope global wlan0\n"
    monkeypatch.setattr(adb, "shell", lambda *a, **k: вывод)
    assert adb.device_ip("phone") == "192.168.1.77"


def test_только_локалхост_и_модем_ip_не_дают(monkeypatch):
    вывод = ("    inet 127.0.0.1/8 scope host lo\n"
             "    inet 10.51.2.3/30 scope global rmnet_data0\n")
    monkeypatch.setattr(adb, "shell", lambda *a, **k: вывод)
    assert adb.device_ip("phone") == ""


# ------------------------------------------------------------------ сторож

ADDR = "192.168.1.50:5555"


class Связь(list):
    """Журнал вызовов adb + переключатель их исхода."""

    outcome = {"ok": True, "message": "connected to " + ADDR}


@pytest.fixture
def связь(monkeypatch):
    """Подменённые connect/disconnect + журнал вызовов."""
    calls = Связь()
    calls.outcome = {"ok": True, "message": "connected to " + ADDR}

    def fake_connect(target, timeout=None):
        calls.append(("connect", target))
        return calls.outcome["ok"], calls.outcome["message"]

    def fake_disconnect(target, timeout=None):
        calls.append(("disconnect", target))
        return True, "disconnected"

    monkeypatch.setattr(netmod.adb, "connect", fake_connect)
    monkeypatch.setattr(netmod.adb, "disconnect", fake_disconnect)
    monkeypatch.setattr(config, "NETWORK_WORKERS", 1)  # без потоков — порядок предсказуем
    return calls


@pytest.fixture
def сеть(tmp_path, связь):
    return NetworkDevices(path=tmp_path / "network.json", seed="")


def test_подключённую_плату_сторож_не_трогает(сеть, связь):
    сеть.add(ADDR)
    связь.clear()
    сеть.tick({ADDR: "device"})
    assert связь == [], "полез подключать то, что и так работает"
    assert сеть.get(ADDR).state == CONNECTED


def test_невидимую_плату_сторож_подключает(сеть, связь):
    сеть.add(ADDR)
    связь.clear()
    сеть.tick({})
    assert связь == [("connect", ADDR)], "лишний disconnect по адресу, которого adb не знает"
    assert сеть.get(ADDR).state == PENDING


def test_мёртвая_запись_сначала_отцепляется(сеть, связь):
    """adb помнит адрес как offline и на connect отвечает 'already connected'."""
    сеть.add(ADDR)
    связь.clear()
    сеть.tick({ADDR: "offline"})
    assert связь == [("disconnect", ADDR), ("connect", ADDR)]


def test_отказ_включает_паузу(сеть, связь):
    сеть.add(ADDR)
    связь.outcome.update(ok=False, message="failed to connect")
    сеть.tick({})
    цель = сеть.get(ADDR)
    assert цель.state == FAILED
    assert цель.attempts == 1
    assert цель.next_try > time.time()

    связь.clear()
    сеть.tick({})
    assert связь == [], "долбит мёртвую плату, не дождавшись паузы"


def test_пауза_растёт_и_упирается_в_потолок(monkeypatch):
    monkeypatch.setattr(config, "NETWORK_RETRY_BASE", 5.0)
    monkeypatch.setattr(config, "NETWORK_RETRY_MAX", 120.0)
    assert [netmod.backoff(n) for n in (0, 1, 2, 3, 4)] == [0.0, 5.0, 10.0, 20.0, 40.0]
    assert netmod.backoff(20) == 120.0


def test_успех_обнуляет_счётчик_неудач(сеть, связь):
    сеть.add(ADDR)
    связь.outcome.update(ok=False, message="failed to connect")
    сеть.tick({})
    assert сеть.get(ADDR).attempts == 1

    сеть.tick({ADDR: "device"})
    цель = сеть.get(ADDR)
    assert цель.attempts == 0
    assert цель.next_try == 0.0
    assert цель.error == ""


def test_выключенный_адрес_пропускается(сеть, связь):
    сеть.add(ADDR)
    сеть.set_enabled(ADDR, False)
    связь.clear()
    сеть.tick({})
    assert связь == []
    assert сеть.get(ADDR).state == DISABLED


def test_отвалившаяся_плата_чинится_без_ожидания(сеть, связь):
    """Была в строю и пропала — паузу применять не за что, чиним сразу."""
    сеть.add(ADDR)
    сеть.tick({ADDR: "device"})
    связь.clear()
    сеть.tick({})
    assert ("connect", ADDR) in связь


def test_ручное_подключение_сбрасывает_паузу(сеть, связь):
    сеть.add(ADDR)
    связь.outcome.update(ok=False, message="failed to connect")
    сеть.tick({})
    связь.outcome.update(ok=True, message="connected to " + ADDR)

    ok, _ = сеть.connect_now(ADDR)
    assert ok
    assert сеть.get(ADDR).attempts == 0


def test_сверка_поднимает_состояние_без_подключений(сеть, связь):
    """API отвечает сразу, не дожидаясь прохода сторожа."""
    сеть.add(ADDR)
    сеть.tick({})
    assert сеть.get(ADDR).state == PENDING
    связь.clear()

    сеть.settle({ADDR: "device"})
    assert сеть.get(ADDR).state == CONNECTED
    assert связь == [], "сверка полезла в adb"


def test_сверка_не_воскрешает_мёртвых(сеть, связь):
    сеть.add(ADDR)
    связь.outcome.update(ok=False, message="failed to connect")
    сеть.tick({})
    сеть.settle({ADDR: "offline"})
    assert сеть.get(ADDR).state == FAILED


def test_ручное_подключение_неизвестного_адреса(сеть):
    ok, message = сеть.connect_now("10.0.0.9:5555")
    assert not ok and "не в списке" in message


# ----------------------------------------------------------------- хранение

def test_адрес_переживает_перезапуск(tmp_path, связь):
    путь = tmp_path / "network.json"
    NetworkDevices(path=путь, seed="").add("192.168.1.50", label="Board-01")

    снова = NetworkDevices(path=путь, seed="")
    цель = снова.get(ADDR)
    assert цель is not None
    assert цель.label == "Board-01"


def test_состояние_в_файл_не_пишется(tmp_path, связь):
    """В файле только адрес, метка и флаг — счётчики попыток временные."""
    путь = tmp_path / "network.json"
    сеть = NetworkDevices(path=путь, seed="")
    сеть.add(ADDR)
    связь.outcome.update(ok=False, message="failed")
    сеть.tick({})
    сеть._save()

    assert set(__import__("json").loads(путь.read_text("utf-8"))[0]) == {"address", "label", "enabled"}


def test_удаление_отцепляет_и_забывает(tmp_path, связь):
    путь = tmp_path / "network.json"
    сеть = NetworkDevices(path=путь, seed="")
    сеть.add(ADDR)
    связь.clear()

    assert сеть.remove(ADDR) is True
    assert ("disconnect", ADDR) in связь
    assert NetworkDevices(path=путь, seed="").get(ADDR) is None
    assert сеть.remove(ADDR) is False


def test_повторное_добавление_не_плодит_дублей(сеть):
    сеть.add(ADDR, label="Board-01")
    сеть.add("192.168.1.50", label="Board-01-renamed")
    assert сеть.addresses() == [ADDR]
    assert сеть.get(ADDR).label == "Board-01-renamed"


def test_добавление_возвращает_выключенный_адрес_в_строй(сеть):
    сеть.add(ADDR)
    сеть.set_enabled(ADDR, False)
    цель = сеть.add(ADDR)
    assert цель.enabled and цель.state != DISABLED


def test_битый_файл_не_роняет_ферму(tmp_path, связь):
    путь = tmp_path / "network.json"
    путь.write_text("{ это не json", "utf-8")
    assert NetworkDevices(path=путь, seed="").all() == []


def test_кривые_записи_из_файла_пропускаются(tmp_path, связь):
    путь = tmp_path / "network.json"
    путь.write_text('[{"address": "192.168.1.50"}, {"address": "!!!"}, "мусор"]', "utf-8")
    сеть = NetworkDevices(path=путь, seed="")
    assert сеть.addresses() == [ADDR]


def test_адреса_из_переменной_окружения(tmp_path, связь):
    сеть = NetworkDevices(path=tmp_path / "network.json",
                          seed="192.168.1.50, 192.168.1.51:5556 ; кривь!")
    assert сеть.addresses() == [ADDR, "192.168.1.51:5556"]


def test_переменная_окружения_не_затирает_метки(tmp_path, связь):
    путь = tmp_path / "network.json"
    NetworkDevices(path=путь, seed="").add(ADDR, label="Board-01")
    снова = NetworkDevices(path=путь, seed="192.168.1.50")
    assert снова.get(ADDR).label == "Board-01"
