import pytest

from farm import config


@pytest.fixture(autouse=True)
def _tapcheck_off(monkeypatch):
    # Проверка «тап подействовал» на фейковых ctx повторяет тап (экран у фейка
    # не меняется) и сбивает подсчёт тапов в старых тестах. Её тесты включают
    # флаг сами.
    monkeypatch.setattr(config, "TAPCHECK", False)


@pytest.fixture(autouse=True)
def _deviations_clean():
    # Журнал отклонений — глобальный: запись из одного теста не должна
    # попадать в подсчёт соседнего.
    from farm import deviations as dv
    dv.deviations.clear()
    yield
    dv.deviations.clear()


@pytest.fixture(autouse=True)
def _secure_clean():
    # Флаг «экран защищён» живёт по серийнику SECURE_TTL секунд: без сброса
    # он переходит в соседний тест с тем же серийником.
    from farm.control import capture
    capture._secure_at.clear()
    yield
    capture._secure_at.clear()


@pytest.fixture(autouse=True)
def _vlm_files_isolated(tmp_path, monkeypatch):
    # Настройки, счётчик и выученные селекторы нейросети — файлы в data/.
    # Без подмены тест, что включает помощника или считает вызовы, пишет в
    # настоящую data/ и ферма пользователя стартует с чужими настройками.
    monkeypatch.setattr(config, "VLM_FILE", tmp_path / "vlm.json")
    monkeypatch.setattr(config, "VLM_USAGE_FILE", tmp_path / "vlm_usage.json")
    monkeypatch.setattr(config, "VLM_LEARNED_FILE", tmp_path / "vlm_learned.json")
