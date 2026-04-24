"""WebSocket endpoint for real-time job progress updates."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# job_id -> set of connected websockets
_connections: dict[int, set[WebSocket]] = {}


@router.websocket("/ws/jobs/{job_id}")
async def job_ws(websocket: WebSocket, job_id: int):
    await websocket.accept()
    _connections.setdefault(job_id, set()).add(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections.get(job_id, set()).discard(websocket)


async def broadcast_to_job(message: dict[str, Any]) -> None:
    """Broadcast a progress message to all WebSocket clients watching a job."""
    job_id = message.get("job_id")
    if job_id is None:
        return
    sockets = _connections.get(job_id, set()).copy()
    payload = json.dumps(message)
    dead = set()
    for ws in sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _connections.get(job_id, set()).difference_update(dead)
