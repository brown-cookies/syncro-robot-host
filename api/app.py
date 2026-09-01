from fastapi import FastAPI

from api.http import health

app = FastAPI(title="SYNCRO Host")

app.include_router(health.router)
