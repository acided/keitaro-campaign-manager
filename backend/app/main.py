from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.config import settings
from app.errors import DomainError
from app.keitaro import KeitaroClient, KeitaroError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.keitaro = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key)
    yield
    await app.state.keitaro.close()


app = FastAPI(title="Keitaro campaign manager", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(DomainError)
@app.exception_handler(KeitaroError)
async def error_response(_: Request, exc: DomainError | KeitaroError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
