"""Нейросеть-помощник (vision-LLM): ищет цель на кадре и подсказывает человеку.

По умолчанию выключена: кадры экрана уходят на внешний адрес только по
явному согласию. Подробности — docs/guide.md, «Нейросеть-помощник».
"""
from . import advise, client, learn, locate, safety, settings, usage
from .locate import locate as locate_target
from .parse import Answer, parse

__all__ = ["advise", "client", "learn", "locate", "locate_target", "safety",
           "settings", "usage", "parse", "Answer"]
