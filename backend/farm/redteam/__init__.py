"""Red-team стенд: детектор фермы + харнесс, который гоняет сценарии в
профилях bot/human и меряет, как часто бот проходит детектор как человек
(false negative rate).

Это учебный инструмент для проверки ВАШЕГО детектора (`RiskDetector` ниже),
а не тулкит для обхода боевых антифрод-систем реальных платформ: там сигналы
другого уровня (аппаратная аттестация, серверные ML-модели, сетевая
репутация), которые здесь не эмулируются и не обходятся. Подробности — в
farm/redteam/README.md.
"""
from .detector import RiskDetector, RiskResult, SignalResult
from .signals import ActionEvent, EnvSnapshot, snapshot_env
from .harness import run_harness

__all__ = [
    "RiskDetector", "RiskResult", "SignalResult",
    "ActionEvent", "EnvSnapshot", "snapshot_env",
    "run_harness",
]
