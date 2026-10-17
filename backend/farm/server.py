"""Точка входа: сборка FastAPI-приложения."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api, config, security
from .devices import net, registry
from .schedule import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("farm.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.start()
    net.start()
    scheduler.start()
    log.info("ADB: %s", registry.adb_version)
    log.info("API: http://%s:%s/api", config.HOST, config.PORT)
    if config.SERVE_FRONTEND:
        log.info("Сайт: http://%s:%s", config.HOST, config.PORT)
    log.info("Данные: %s", config.DATA_DIR)
    if not security.is_loopback(config.HOST) and not security.token():
        log.warning("Ферма открыта в сеть (FARM_HOST=%s) без FARM_TOKEN: любой в "
                    "этой сети управляет телефонами и видит пароли аккаунтов. "
                    "Задайте FARM_TOKEN или верните FARM_HOST=127.0.0.1.", config.HOST)
    yield
    scheduler.stop()
    net.stop()
    registry.stop()


def create_app() -> FastAPI:
    application = FastAPI(title="Android Farm", version="0.1.0", lifespan=lifespan)
    application.include_router(api.router)

    # Сайт (frontend/) — обычные статические файлы. Монтируем последним и на
    # корень: всё, что не /api, — это сайт. Без него сервер — чистый API.
    if config.SERVE_FRONTEND and config.FRONTEND_DIR.is_dir():
        application.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
                          name="frontend")

    # Без этого браузер держал старые JS/CSS из кэша и после обновления
    # фермы показывал прежний интерфейс. no-cache = «спроси сервер»: файл
    # не перекачивается, если не изменился (ETag), так что это дёшево.
    @application.middleware("http")
    async def static_revalidate(request, call_next):  # noqa: ANN001
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Последним, чтобы оборачивать всё остальное: Host/Origin/токен
    # проверяются до любого обработчика, включая статику.
    application.middleware("http")(security.guard)

    @application.exception_handler(Exception)
    async def unhandled(request, exc):  # noqa: ANN001
        log.exception("необработанная ошибка на %s", request.url.path)
        return JSONResponse({"detail": str(exc)}, status_code=500)

    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
