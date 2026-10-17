"""Поиск node для JS-тестов: только PATH, без зашитых путей.

Нет node — тест пропускается с понятной причиной; в CI выставляют
FARM_REQUIRE_NODE=1, и тогда отсутствие node роняет тест, а не прячется.
"""
import os
import shutil

import pytest


def require_node() -> str:
    path = shutil.which("node")
    if path:
        return path
    if os.environ.get("FARM_REQUIRE_NODE") == "1":
        pytest.fail("node не найден в PATH, а FARM_REQUIRE_NODE=1: "
                    "JS-тесты обязательны", pytrace=False)
    pytest.skip("node не найден в PATH (FARM_REQUIRE_NODE=1 сделает это ошибкой)")
