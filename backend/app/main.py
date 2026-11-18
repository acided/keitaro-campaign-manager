from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import router
from app.config import settings
from app.errors import DomainError
from app.keitaro import KeitaroClient, KeitaroError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.keitaro = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key)
    yield
    await app.state.keitaro.close()


app = FastAPI(title="Keitaro campaign manager", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def same_site_only(request: Request, call_next):
    """There is no login, so any page open in the browser could POST here (Push is a body-less
    POST, no CORS preflight) or rebind a domain to 127.0.0.1. Answer only to our own host names,
    and accept writes only from our own pages (browsers always send Origin on cross-site POSTs)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in settings.allowed_hosts:
        return JSONResponse({"detail": "Unknown host"}, status_code=400)
    origin = request.headers.get("origin")
    cross_site = origin and urlsplit(origin).hostname not in settings.allowed_hosts
    if request.method not in SAFE_METHODS and cross_site:
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


@app.exception_handler(DomainError)
@app.exception_handler(KeitaroError)
async def error_response(_: Request, exc: DomainError | KeitaroError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.exception_handler(IntegrityError)
async def concurrent_change(_: Request, __: IntegrityError) -> JSONResponse:
    # e.g. two first Fetches of one campaign at once: the second one loses the insert
    return JSONResponse({"detail": "A concurrent request changed the same data, try again"}, status_code=409)
