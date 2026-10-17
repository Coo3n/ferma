"""Кэш модулей сценариев: перезапись файла не должна отдавать старый код."""
import os

import pytest

from farm import config, scenarios
from farm.recorder import save, steps

OLD = 'NAME = "старый"\n\ndef run(ctx):\n    pass\n'
NEW = 'NAME = "новый, другой длины"\n\ndef run(ctx):\n    ctx.sleep(0)\n'


@pytest.fixture
def папка(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    scenarios._stamps.clear()
    scenarios._warned.clear()
    yield tmp_path
    scenarios._cache.clear()
    scenarios._stamps.clear()
    scenarios._warned.clear()


def _переписать_с_прежним_временем(path, text):
    st = path.stat()
    path.write_text(text, "utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_другой_размер_при_том_же_mtime_перезагружается(папка):
    path = папка / "k.py"
    path.write_text(OLD, "utf-8")
    assert scenarios.get("k").name == "старый"
    _переписать_с_прежним_временем(path, NEW)
    assert scenarios.get("k").name == "новый, другой длины"


def test_тот_же_размер_и_mtime_не_ловится_без_invalidate(папка):
    # (mtime_ns, size) не различает перезапись того же размера в тот же тик;
    # хешировать файлы на каждый опрос дорого — такой случай закрывает
    # явный invalidate(key) из save.save
    path = папка / "k.py"
    path.write_text(OLD, "utf-8")
    assert scenarios.get("k").name == "старый"
    _переписать_с_прежним_временем(path, OLD.replace("старый", "СТАРЫЙ"))
    assert scenarios.get("k").name == "старый"
    scenarios.invalidate("k")
    assert scenarios.get("k").name == "СТАРЫЙ"


def test_save_поверх_сценария_сбрасывает_кэш(папка):
    meta = {"name": "один", "description": "", "watch_popups": False}
    raw = [{"kind": "sleep", "args": {"seconds": 1}}]
    build = lambda: [steps.normalize_step(r) for r in raw]
    path = save.save("k", meta, {}, build())
    assert scenarios.get("k").name == "один"
    st = path.stat()
    save.save("k", {**meta, "name": "ОДИН"}, {}, build(), overwrite=True)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    # штамп и размер те же (имя той же длины): спасает только invalidate из save
    assert scenarios.get("k").name == "ОДИН"


GOOD = 'NAME = "хороший"\n\ndef run(ctx):\n    pass\n'


def test_utf8_bom_загружается(папка):
    (папка / "b.py").write_bytes(b"\xef\xbb\xbf" + OLD.encode("utf-8"))
    sc = scenarios.get("b")
    assert not sc.error and sc.name == "старый" and callable(sc.module.run)


def test_объявление_кодировки_cp1251(папка):
    text = '# -*- coding: cp1251 -*-\nNAME = "вин"\n\ndef run(ctx):\n    pass\n'
    (папка / "c.py").write_bytes(text.encode("cp1251"))
    sc = scenarios.get("c")
    assert not sc.error and sc.name == "вин"


def test_нечитаемый_файл_даёт_ошибку_и_не_ломает_остальные(папка):
    (папка / "bad.py").write_bytes(b'NAME = "\xff\xfe\xd0"\n')
    (папка / "good.py").write_text(GOOD, "utf-8")
    found = {s.key: s for s in scenarios.discover()}
    assert found["bad"].error
    assert not found["good"].error and found["good"].name == "хороший"


def test_аннотации_не_наследуют_future_модуля(папка):
    (папка / "a.py").write_text("def run(ctx: int):\n    pass\n", "utf-8")
    assert scenarios.get("a").module.run.__annotations__["ctx"] is int


def test_co_filename_и_traceback(папка):
    import traceback
    path = папка / "t.py"
    path.write_text("def run(ctx):\n    raise RuntimeError('бум')\n", "utf-8")
    run = scenarios.get("t").module.run
    assert run.__code__.co_filename == str(path)
    try:
        run(None)
    except RuntimeError:
        tb = traceback.format_exc()
    assert "t.py" in tb and "raise RuntimeError('бум')" in tb


def test_invalidate_во_время_опроса_не_оставляет_старый_кэш(папка, monkeypatch):
    import threading
    path = папка / "k.py"
    path.write_text(OLD, "utf-8")
    in_load, go = threading.Event(), threading.Event()
    real = scenarios._load_file

    def slow(p):
        sc = real(p)          # успел прочитать старое
        in_load.set()
        go.wait(2)
        return sc

    monkeypatch.setattr(scenarios, "_load_file", slow)
    t = threading.Thread(target=scenarios.discover)
    t.start()
    assert in_load.wait(2)
    inv = threading.Thread(target=scenarios.invalidate, args=("k",))
    inv.start()               # должен дождаться конца опроса
    go.set()
    t.join(); inv.join()
    assert "k" not in scenarios._cache and "k" not in scenarios._stamps


# ------------------------------------------------------- опасности загрузчика

def test_sys_exit_при_загрузке_не_обрывает_сканирование(папка):
    (папка / "a_exit.py").write_text("import sys\nsys.exit(3)\n", "utf-8")
    (папка / "z_good.py").write_text(OLD, "utf-8")
    found = {s.key: s for s in scenarios.discover()}
    assert "выход из программы" in found["a_exit"].error
    assert found["a_exit"].module is None
    assert not found["z_good"].error


def test_keyboardinterrupt_при_загрузке_не_глотается(папка):
    (папка / "k.py").write_text("raise KeyboardInterrupt\n", "utf-8")
    with pytest.raises(KeyboardInterrupt):
        scenarios.discover()


def test_файл_исчез_между_штампом_и_загрузкой(папка, monkeypatch, caplog):
    (папка / "gone.py").write_text(OLD, "utf-8")
    (папка / "z_good.py").write_text(OLD, "utf-8")
    настоящий = scenarios._stamp

    def stamp_и_удалить(path):
        st = настоящий(path)
        if path.name == "gone.py":
            path.unlink()
        return st

    monkeypatch.setattr(scenarios, "_stamp", stamp_и_удалить)
    with caplog.at_level("WARNING", logger="farm.scenarios"):
        found = {s.key for s in scenarios.discover()}
    assert found == {"z_good"}
    assert "gone" in caplog.text


def _петля(папка, имя):
    link = папка / имя
    link.symlink_to(link)
    return link


def test_нечитаемый_файл_предупреждает_один_раз(папка, caplog):
    _петля(папка, "loop.py")
    (папка / "good.py").write_text(OLD, "utf-8")
    with caplog.at_level("WARNING", logger="farm.scenarios"):
        first = {s.key for s in scenarios.discover()}
        scenarios.discover()
    assert first == {"good"}
    assert caplog.text.count("файл не читается") == 1


def test_предупреждение_повторяется_после_выздоровления(папка, caplog):
    link = _петля(папка, "loop.py")
    with caplog.at_level("WARNING", logger="farm.scenarios"):
        scenarios.discover()
        link.unlink()
        link.write_text(OLD, "utf-8")
        assert [s.key for s in scenarios.discover()] == ["loop"]
        link.unlink()
        _петля(папка, "loop.py")
        scenarios.discover()
    assert caplog.text.count("файл не читается") == 2
