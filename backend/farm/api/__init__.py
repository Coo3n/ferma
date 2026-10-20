"""REST-слой фермы, собранный из роутеров по зонам ответственности."""
from fastapi import APIRouter

from . import schedule
from . import (accounts, apks, bulk, detours, deviations, devices, files, jobs, network, recorder,
               scenarios, screen, system)

router = APIRouter()
router.include_router(system.router)
router.include_router(accounts.router)
router.include_router(bulk.router)
router.include_router(apks.router)
router.include_router(devices.router)
router.include_router(devices.tags_router)
router.include_router(network.router)
router.include_router(screen.router)
router.include_router(files.router)
router.include_router(screen.recordings_router)
router.include_router(scenarios.router)
router.include_router(jobs.router)
router.include_router(recorder.router)
router.include_router(detours.router)
router.include_router(deviations.router)
router.include_router(schedule.router)

__all__ = ["router"]
