"""Настройки фермы. Всё переопределяется переменными окружения."""
import os
from pathlib import Path

# Раскладка проекта:
#   backend/   — этот сервер (пакет farm, сценарии, стражи, тесты)
#   frontend/  — сайт: статические файлы, сервер их только раздаёт
#   data/      — рабочие данные фермы (аккаунты, телефоны, артефакты), не в git
ROOT = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = ROOT.parent
DATA_DIR = Path(os.getenv("FARM_DATA_DIR", PROJECT_DIR / "data"))

# Каталоги
SCENARIOS_DIR = Path(os.getenv("FARM_SCENARIOS_DIR", ROOT / "scenarios"))
ARTIFACTS_DIR = Path(os.getenv("FARM_ARTIFACTS_DIR", DATA_DIR / "artifacts"))
GUARDS_DIR = Path(os.getenv("FARM_GUARDS_DIR", ROOT / "guards"))
# Сайт. Сервер раздаёт его сам, чтобы ферма поднималась одной командой;
# FARM_SERVE_FRONTEND=0 — чистый API, сайт раздаёт кто-то другой (nginx,
# frontend/dev_server.py), проксируя /api на этот сервер.
FRONTEND_DIR = Path(os.getenv("FARM_FRONTEND_DIR", PROJECT_DIR / "frontend"))
SERVE_FRONTEND = os.getenv("FARM_SERVE_FRONTEND", "1") != "0"

# Сеть
HOST = os.getenv("FARM_HOST", "127.0.0.1")
PORT = int(os.getenv("FARM_PORT", "8777"))

# Опрос устройств
POLL_INTERVAL = float(os.getenv("FARM_POLL_INTERVAL", "3.0"))  # список adb devices
HEALTH_INTERVAL = float(os.getenv("FARM_HEALTH_INTERVAL", "20.0"))  # батарея/температура
ADB_TIMEOUT = float(os.getenv("FARM_ADB_TIMEOUT", "20.0"))

# Сетевые устройства (платы по Ethernet/Wi-Fi)
# Плата в стойке не появится в `adb devices` сама: её адрес надо помнить и
# переподключать после каждого обрыва. Список живёт в NETWORK_FILE, а
# FARM_NETWORK_DEVICES только досыпает в него адреса при старте.
NETWORK_FILE = Path(os.getenv("FARM_NETWORK_FILE", DATA_DIR / "network.json"))
NETWORK_SEED = os.getenv("FARM_NETWORK_DEVICES", "")  # "10.0.0.5, 10.0.0.6:5555"
NETWORK_PORT = int(os.getenv("FARM_NETWORK_PORT", "5555"))
NETWORK_TICK = float(os.getenv("FARM_NETWORK_TICK", "5.0"))  # проход сторожа
NETWORK_CONNECT_TIMEOUT = float(os.getenv("FARM_NETWORK_CONNECT_TIMEOUT", "10.0"))
# Мёртвую плату не долбим каждые пять секунд: пауза растёт вдвое до потолка.
NETWORK_RETRY_BASE = float(os.getenv("FARM_NETWORK_RETRY_BASE", "5.0"))
NETWORK_RETRY_MAX = float(os.getenv("FARM_NETWORK_RETRY_MAX", "120.0"))
NETWORK_WORKERS = int(os.getenv("FARM_NETWORK_WORKERS", "8"))  # connect'ы разом

# Стриминг экрана
STREAM_FPS = float(os.getenv("FARM_STREAM_FPS", "6"))
STREAM_MAX_WIDTH = int(os.getenv("FARM_STREAM_MAX_WIDTH", "480"))
STREAM_QUALITY = int(os.getenv("FARM_STREAM_QUALITY", "60"))
# Экран «живой» (пульт, запись, ожидание человека): кадры чаще и чуть крупнее;
# после каждого действия BURST секунд снимаем без пауз, чтобы реакция была видна.
STREAM_FPS_LIVE = float(os.getenv("FARM_STREAM_FPS_LIVE", "12"))
STREAM_MAX_WIDTH_LIVE = int(os.getenv("FARM_STREAM_MAX_WIDTH_LIVE", "540"))
STREAM_BURST_SECONDS = float(os.getenv("FARM_STREAM_BURST_SECONDS", "1.5"))
STREAM_IDLE_TIMEOUT = float(os.getenv("FARM_STREAM_IDLE_TIMEOUT", "10.0"))

# Превью для плитки фермы: мелкие, редкие, с кэшем на сервере. Отдельно от
# STREAM_*, потому что их снимают со всех устройств сразу, а не с одного.
THUMB_MAX_WIDTH = int(os.getenv("FARM_THUMB_MAX_WIDTH", "240"))
THUMB_QUALITY = int(os.getenv("FARM_THUMB_QUALITY", "45"))
THUMB_TTL = float(os.getenv("FARM_THUMB_TTL", "1.5"))

# Скриншоты для артефактов — крупнее
ARTIFACT_MAX_WIDTH = int(os.getenv("FARM_ARTIFACT_MAX_WIDTH", "1080"))

# Стабильность экрана: перед шагом ждём два одинаковых дампа подряд. Вечная
# анимация стабильности не даст — тогда выходим по таймауту и шаг идёт дальше:
# ожидание best-effort, а не гейт.
SETTLE = os.getenv("FARM_SETTLE", "1") != "0"
SETTLE_TIMEOUT = float(os.getenv("FARM_SETTLE_TIMEOUT", "3.0"))
SETTLE_QUIET = float(os.getenv("FARM_SETTLE_QUIET", "0.4"))
# После свайпа ждём не весь экран, а рамку цели; ленту, что дорисовывается
# вечно, не держим дольше этих секунд (иначе полный SETTLE_TIMEOUT на шаг).
TARGET_STABLE_TIMEOUT = float(os.getenv("FARM_TARGET_STABLE_TIMEOUT", "1.5"))
SCROLL_SETTLE_TIMEOUT = float(os.getenv("FARM_SCROLL_SETTLE_TIMEOUT", "1.0"))
# Пиксельный дифф: доля среднего отличия кадров (0..1), ниже которой экран
# считаем тем же. Запасной путь для вечной анимации, где XML не стабилизируется.
PIXEL_DIFF_THRESHOLD = float(os.getenv("FARM_PIXEL_DIFF_THRESHOLD", "0.01"))
SETTLE_PIXEL = os.getenv("FARM_SETTLE_PIXEL", "1") != "0"

# Общий выход: перебор back/закрыть/пропустить, когда экран не тот, а стражи
# промолчали. Выключается там, где чужие нажатия недопустимы.
ESCAPE = os.getenv("FARM_ESCAPE", "1") != "0"

# Сколько задач хранить в журнале
ARTIFACT_KEEP_DAYS = float(os.getenv("FARM_ARTIFACT_KEEP_DAYS", "14"))  # снимки и отчёты старше — удаляются
JOB_HISTORY = int(os.getenv("FARM_JOB_HISTORY", "1000"))  # запуск на 100 телефонов × повторы

# Остановка на человеке: шаг промахнулся, но вместо падения задача встаёт и
# ждёт решения, не отпуская устройство. Смысл в том, что экран на телефоне ещё
# тот самый: отпущенное устройство тут же забирает следующая задача из очереди,
# и показывать человеку уже нечего (см. docstring farm/obstacle.py).
#
# Цена — простой устройства. Поэтому потолки жёсткие: HOLD_MAX ограничивает,
# сколько устройств разом могут ждать (иначе ночной прогон встанет весь),
# HOLD_TIMEOUT сам роняет задачу, если никто не пришёл, а HOLD_MAX_PER_JOB не
# даёт одной задаче висеть вечно на «повторить → снова промах».
HOLD = os.getenv("FARM_HOLD", "1") != "0"
HOLD_TIMEOUT = float(os.getenv("FARM_HOLD_TIMEOUT", "600"))   # сек ждать человека
HOLD_MAX = int(os.getenv("FARM_HOLD_MAX", "3"))               # устройств разом
HOLD_MAX_PER_JOB = int(os.getenv("FARM_HOLD_MAX_PER_JOB", "5"))
# Останавливаться и спрашивать перед шагом «вслепую» (тап по координатам,
# якорь по системной панели). 0 — только помечать в отчёте.
HOLD_BLIND = os.getenv("FARM_HOLD_BLIND", "1") != "0"

# Сторож долгих циклов (лента, просмотр — ctx.on_track): листание не промахивается,
# поэтому без сторожа ферма минутами листала бы чужой экран. Раз в WATCH_EVERY
# секунд проверяется: своё ли приложение впереди и меняется ли экран. WATCH_SAME
# одинаковых экранов подряд, несмотря на листание, — застряли.
WATCH = os.getenv("FARM_WATCH", "1") != "0"
WATCH_EVERY = float(os.getenv("FARM_WATCH_EVERY", "20"))
WATCH_SAME = int(os.getenv("FARM_WATCH_SAME", "3"))

# Сколько отклонений от сценария хранить. Меньше, чем задач: одинаковые
# сливаются в одну строку со счётчиком, так что двести строк — это очень
# много поводов. Не путать с тревогами устройств (TEMP_ALERT_C ниже).
DEVIATION_HISTORY = int(os.getenv("FARM_DEVIATION_HISTORY", "200"))

# Проверка «нажали — эффект есть»: после тапа сверяем дамп, потом кадр; ничего
# не изменилось — один повтор, и если снова пусто, это отклонение «noeffect».
TAPCHECK = os.getenv("FARM_TAPCHECK", "1") != "0"
TAPCHECK_DELAY = float(os.getenv("FARM_TAPCHECK_DELAY", "0.8"))  # пауза на реакцию
# Тап мимо перекрывашки: если центр цели закрыт кликабельным братом, ищем
# свободную точку рамки (ui/tree.tap_point). Стоит лишнего дампа на селекторный клик.
TAPCOVER = os.getenv("FARM_TAPCOVER", "1") != "0"

# Нейросеть-помощник (farm/vlm). По умолчанию ВЫКЛЮЧЕНА: кадры экрана аккаунтов
# уходят на внешний адрес, и без явного согласия человека этого быть не должно.
# Здесь только значения по умолчанию и пути файлов; живые значения читает
# farm/vlm/settings.py заново на каждый вызов (переменные окружения важнее
# data/vlm.json, который правят из интерфейса).
VLM = os.getenv("FARM_VLM", "0") == "1"
VLM_URL = os.getenv("FARM_VLM_URL", "")
VLM_MODEL = os.getenv("FARM_VLM_MODEL", "")
VLM_KEY = os.getenv("FARM_VLM_KEY", "")
VLM_TIMEOUT = float(os.getenv("FARM_VLM_TIMEOUT", "30"))
VLM_MAX_PER_JOB = int(os.getenv("FARM_VLM_MAX_PER_JOB", "3"))
VLM_MAX_PER_DAY = int(os.getenv("FARM_VLM_MAX_PER_DAY", "200"))
VLM_MAX_WIDTH = int(os.getenv("FARM_VLM_MAX_WIDTH", "720"))
VLM_FILE = Path(os.getenv("FARM_VLM_FILE", DATA_DIR / "vlm.json"))
VLM_USAGE_FILE = Path(os.getenv("FARM_VLM_USAGE_FILE", DATA_DIR / "vlm_usage.json"))
VLM_LEARNED_FILE = Path(os.getenv("FARM_VLM_LEARNED_FILE", DATA_DIR / "vlm_learned.json"))

# Тревоги
TEMP_ALERT_C = float(os.getenv("FARM_TEMP_ALERT_C", "42"))
BATTERY_LOW = int(os.getenv("FARM_BATTERY_LOW", "20"))
BATTERY_HIGH = int(os.getenv("FARM_BATTERY_HIGH", "95"))
# Защита от разряда и перегрева (devices/power.py): критичный заряд даёт время
# на реакцию, дальше запуски на телефоне снимаются и он «отдыхает».
BATTERY_CRITICAL = int(os.getenv("FARM_BATTERY_CRITICAL", "15"))
BATTERY_STOP = int(os.getenv("FARM_BATTERY_STOP", "5"))                    # стоп сразу
BATTERY_GRACE = float(os.getenv("FARM_BATTERY_GRACE", "600"))              # секунд на реакцию
BATTERY_RESUME = int(os.getenv("FARM_BATTERY_RESUME", "30"))               # вернуть в строй
BATTERY_RESUME_CHARGING = int(os.getenv("FARM_BATTERY_RESUME_CHARGING", "20"))
TEMP_STOP_C = float(os.getenv("FARM_TEMP_STOP_C", "46"))
TEMP_RESUME_C = float(os.getenv("FARM_TEMP_RESUME_C", "40"))

DATA_FILES = ("accounts.json", "devices.json", "groups.json", "tags.json",
              "schedules.json", "network.json")


def _migrate_legacy_data() -> None:
    """До раскладки backend/frontend данные лежали в корне проекта. Переносим
    их в data/ один раз — иначе после обновления ферма «забыла» бы аккаунты,
    имена телефонов и расписание."""
    if os.getenv("FARM_DATA_DIR"):
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES + ("artifacts",):
        old, new = PROJECT_DIR / name, DATA_DIR / name
        if old.exists() and not new.exists():
            old.rename(new)


_migrate_legacy_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
GUARDS_DIR.mkdir(parents=True, exist_ok=True)

# Зависший uiautomator: лестница пауз между повторами dump_hierarchy и число
# подряд идущих провалов, после которого сервис перезапускается.
DUMP_RETRY_DELAYS = tuple(float(x) for x in os.getenv("FARM_DUMP_RETRY_DELAYS", "1,2,3,5").split(",") if x.strip())
# Сколько секунд после провала лестницы дамп идёт сразу голым adb: иначе на
# каждый клик при мёртвом uiautomator уходит около минуты.
DUMP_DEAD_TTL = float(os.getenv("FARM_DUMP_DEAD_TTL", "20"))
DUMP_RECOVER_AFTER = int(os.getenv("FARM_DUMP_RECOVER_AFTER", "2"))
# Защищённый экран: сколько секунд верим последнему кадру, что экран защищён.
SECURE_TTL = float(os.getenv("FARM_SECURE_TTL", "10"))
