from fastapi import APIRouter

from config import endpoints

router = APIRouter()


@router.get(endpoints.HTTP_HEALTH)
def health() -> dict:
    """Report the current host service health status."""
    return {"status": "ok"}
