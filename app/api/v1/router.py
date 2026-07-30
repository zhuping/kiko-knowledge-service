from fastapi import APIRouter

from . import (
    admin_catalog,
    admin_operations,
    admin_packages,
    classifications,
    packages,
)

router = APIRouter(prefix="/api/v1")
router.include_router(packages.router)
router.include_router(classifications.router)
router.include_router(admin_packages.router)
router.include_router(admin_catalog.router)
router.include_router(admin_operations.router)
