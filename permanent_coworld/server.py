from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from permanent_coworld.config import DEFAULT_DATABASE, ROOT
from permanent_coworld.db import CoworldDatabase


def database_from_environment() -> CoworldDatabase:
    return CoworldDatabase(Path(os.environ.get("PERMANENT_COWORLD_DB", DEFAULT_DATABASE)))


db = database_from_environment()
app = FastAPI(title="Permanent Codrawing Coworld", version="0.1.0")


class PixelRequest(BaseModel):
    x: int
    y: int
    action: str


class MessageRequest(BaseModel):
    message: str


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ").strip()


@app.on_event("startup")
def startup() -> None:
    db.initialize()


@app.get("/")
def viewer() -> FileResponse:
    return FileResponse(ROOT / "static" / "viewer.html")


@app.get("/api/public/state")
def public_state() -> dict[str, object]:
    return db.state()


@app.get("/api/public/history")
def public_history(
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    return {"events": db.history(after=after, limit=limit)}


@app.get("/api/board")
def board(authorization: str | None = Header(default=None)) -> JSONResponse:
    status, payload = db.agent_state(bearer(authorization), endpoint="/api/board")
    return JSONResponse(payload, status_code=status)


@app.get("/api/score")
def score(authorization: str | None = Header(default=None)) -> JSONResponse:
    status, payload = db.agent_state(bearer(authorization), endpoint="/api/score")
    if status == 200:
        payload = {"score": payload["score"], "event_id": payload["event_id"], "you": payload["you"]}
    return JSONResponse(payload, status_code=status)


@app.get("/api/snapshot.png")
def snapshot(authorization: str | None = Header(default=None)) -> Response:
    status, payload = db.agent_snapshot(bearer(authorization))
    if status != 200:
        return JSONResponse(payload, status_code=status)
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/messages")
def messages(authorization: str | None = Header(default=None)) -> JSONResponse:
    status, payload = db.agent_state(bearer(authorization), endpoint="/api/messages")
    if status == 200:
        payload = {"messages": payload["messages"], "event_id": payload["event_id"], "you": payload["you"]}
    return JSONResponse(payload, status_code=status)


@app.post("/api/messages")
def post_message(
    request: MessageRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    status, payload = db.post_message(bearer(authorization), request.message)
    return JSONResponse(payload, status_code=status)


@app.post("/api/pixel")
def post_pixel(
    request: PixelRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    status, payload = db.put_pixel(
        bearer(authorization), x=request.x, y=request.y, action=request.action,
    )
    return JSONResponse(payload, status_code=status)
