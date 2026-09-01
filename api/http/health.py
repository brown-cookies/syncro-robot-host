from fastapi import APIRouter

from config import endpoints

router = APIRouter()


@router.get(endpoints.HTTP_HEALTH)
def health() -> dict:
    return {"status": "ok"}
