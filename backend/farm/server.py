"""Точка входа: сборка FastAPI-приложения."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import accounts, api, config, security, tls
from .devices import net, registry
from .schedule import SaveError as ScheduleSaveError, scheduler
from .limits import BodyLimits, TrafficLimits

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("farm.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    security.validate_network()
    registry.start()
    net.start()
    scheduler.start()
    log.info("ADB: %s", registry.adb_version)
    log.info("API: %s/api", tls.browser_url())
    if config.SERVE_FRONTEND:
        log.info("Сайт: %s", tls.browser_url())
    log.info("Данные: %s", config.DATA_DIR)
    yield
    scheduler.stop()
    net.stop()
    registry.stop()


def create_app() -> FastAPI:
    application = FastAPI(title="Android Farm", version="0.1.0", lifespan=lifespan)
    application.include_router(api.router)

    @application.exception_handler(accounts.SaveError)
    @application.exception_handler(ScheduleSaveError)
    async def persistence_save_failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    # Сайт (frontend/) — обычные статические файлы. Монтируем последним и на
    # корень: всё, что не /api, — это сайт. Без него сервер — чистый API.
    if config.SERVE_FRONTEND and config.FRONTEND_DIR.is_dir():
        application.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
                          name="frontend")

    # Ближе всего к обработчикам: HTTPException из receive() должна попадать
    # прямо в ExceptionMiddleware, а не в task group BaseHTTPMiddleware.
    application.add_middleware(BodyLimits)

    # Без этого браузер держал старые JS/CSS из кэша и после обновления
    # фермы показывал прежний интерфейс. no-cache = «спроси сервер»: файл
    # не перекачивается, если не изменился (ETag), так что это дёшево.
    @application.middleware("http")
    async def static_revalidate(request, call_next):  # noqa: ANN001
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Host/Origin/токен проверяются до чтения тела запроса.
    # проверяются до любого обработчика, включая статику.
    application.middleware("http")(security.guard)
    application.add_middleware(TrafficLimits)

    @application.exception_handler(Exception)
    async def unhandled(request, exc):  # noqa: ANN001
        log.exception("необработанная ошибка на %s", request.url.path)
        return security.protect_response(request, JSONResponse(
            {"detail": "Внутренняя ошибка сервера. Подробности в журнале фермы."}, status_code=500))

    return application


app = create_app()


def main() -> None:
    import uvicorn

    try:
        options = tls.uvicorn_options()
    except ValueError as exc:
        raise SystemExit(str(exc))
    uvicorn.run(app, **options)


if __name__ == "__main__":
    main()
