"""Устройства: реестр, пул подключений, сетевые адреса, очередь задач.

`runner` намеренно не импортируется здесь: он тянет `farm.control`, который
через fallback обращается к `devices.pool`. Импорт runner в этом файле замкнул
бы цикл. Берите его явно: `from farm.devices.runner import runner`.
"""
from . import network, pool
from .network import net
from .registry import registry

__all__ = ["network", "net", "pool", "registry"]
