"""Хелпер node: без node тест пропускается, а в CI (FARM_REQUIRE_NODE=1) падает."""
import pytest

import _node


def test_node_найден_возвращает_путь(monkeypatch):
    monkeypatch.setattr(_node.shutil, "which", lambda name: "/x/node")
    assert _node.require_node() == "/x/node"


def test_нет_node_пропуск_по_умолчанию(monkeypatch):
    monkeypatch.setattr(_node.shutil, "which", lambda name: None)
    monkeypatch.delenv("FARM_REQUIRE_NODE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="node"):
        _node.require_node()


def test_нет_node_падение_при_FARM_REQUIRE_NODE(monkeypatch):
    monkeypatch.setattr(_node.shutil, "which", lambda name: None)
    monkeypatch.setenv("FARM_REQUIRE_NODE", "1")
    with pytest.raises(pytest.fail.Exception, match="FARM_REQUIRE_NODE"):
        _node.require_node()


def test_FARM_REQUIRE_NODE_не_единица_это_пропуск(monkeypatch):
    monkeypatch.setattr(_node.shutil, "which", lambda name: None)
    monkeypatch.setenv("FARM_REQUIRE_NODE", "0")
    with pytest.raises(pytest.skip.Exception):
        _node.require_node()
