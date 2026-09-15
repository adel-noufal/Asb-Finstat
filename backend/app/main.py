import asyncio
import re

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .config import settings
from .pipeline.company_search import search_companies
from .pipeline.runner import run_pipeline

app = FastAPI(title="asb-finstat")


@app.get("/")
async def health():
    return {"ok": True}


@app.get("/artifacts/{artifact_id}/{filename}")
async def extraction_artifact(artifact_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", artifact_id) or filename not in {"report.json", "report.xlsx"}:
        raise HTTPException(status_code=404, detail="Artifact not found")
    root = settings.extraction_dir.resolve()
    path = (root / artifact_id / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = "application/json" if filename.endswith(".json") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=filename, media_type=media_type)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    pipeline_task: asyncio.Task | None = None
    search_task: asyncio.Task | None = None

    async def company_search(msg: dict):
        try:
            result = await search_companies(msg.get("country"), msg.get("query"), msg.get("countryCode"))
            await ws.send_json({"type": "companies", "requestId": msg.get("requestId"),
                                **result.model_dump()})
        except ValueError as exc:
            await ws.send_json({"type": "companies", "requestId": msg.get("requestId"),
                                "companies": [], "error": str(exc)})
        except Exception:
            await ws.send_json({"type": "companies", "requestId": msg.get("requestId"),
                                "companies": [], "error": "Company search is unavailable. Please try again."})

    async def cancel_search():
        if search_task and not search_task.done():
            search_task.cancel()
            await asyncio.gather(search_task, return_exceptions=True)

    async def emit(step: str, status: str, message: str, data: dict | None = None):
        await ws.send_json({"type": "step_update", "step": step, "status": status,
                            "message": message, "data": data})

    try:
        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type")
            if msg_type == "search_companies":
                await cancel_search()
                search_task = asyncio.create_task(company_search(msg))
            elif msg_type == "cancel_search":
                await cancel_search()
            elif msg_type == "run_pipeline":
                await cancel_search()
                if pipeline_task and not pipeline_task.done():
                    await emit("pipeline", "error", "A pipeline is already running on this connection")
                    continue
                pipeline_task = asyncio.create_task(run_pipeline(msg["company"], msg["country"], emit))
            else:
                await emit("pipeline", "error", f"Unknown message type: {msg_type}")
    except WebSocketDisconnect:
        pass
    finally:
        await cancel_search()
        if pipeline_task and not pipeline_task.done():
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
