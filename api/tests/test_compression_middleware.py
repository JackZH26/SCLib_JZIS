"""API compression is wired outside the session layer and inside CORS."""
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from main import app


def test_api_registers_gzip_with_balanced_compression_level():
    middleware = app.user_middleware
    classes = [entry.cls for entry in middleware]

    assert classes.index(CORSMiddleware) < classes.index(GZipMiddleware)
    assert classes.index(GZipMiddleware) < classes.index(SessionMiddleware)

    gzip = next(entry for entry in middleware if entry.cls is GZipMiddleware)
    assert gzip.kwargs["minimum_size"] == 1024
    assert gzip.kwargs["compresslevel"] == 6
