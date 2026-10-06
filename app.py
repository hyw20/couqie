from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.blender_runner import OUTPUT, find_blender, run_stage
from engine.gmod import probe as probe_gmod
from engine.models import list_models, resolve_cast, save_upload
from engine.parser import actions_to_payload, parse_instruction

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

app = FastAPI(title="Blender 指令小剧场")
OUTPUT.mkdir(parents=True, exist_ok=True)
(OUTPUT / "frames").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
app.mount("/media/frames", StaticFiles(directory=str(OUTPUT / "frames")), name="frames")


class PlayRequest(BaseModel):
    instruction: str
    model: str | None = None
    models: list[str] | None = None


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/status")
def status():
    try:
        blender = str(find_blender())
        ready = True
        error = ""
    except FileNotFoundError as exc:
        blender = ""
        ready = False
        error = str(exc)
    return {
        "ready": ready,
        "blender": blender,
        "error": error,
        **probe_gmod(),
    }


@app.get("/api/models")
def models():
    return {"models": list_models()}


@app.post("/api/models")
async def upload_model(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    try:
        path = save_upload(file.filename or "model.glb", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "name": path.name, "models": list_models()}


@app.post("/api/play")
def play(req: PlayRequest):
    instruction = (req.instruction or "").strip()
    if not instruction:
        raise HTTPException(400, "请输入指令")
    actions = parse_instruction(instruction)
    try:
        cast = resolve_cast(req.models, req.model)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    result = run_stage(
        actions_to_payload(actions),
        instruction,
        cast[0]["model_path"] or None,
        cast,
    )
    if not result.get("ok"):
        raise HTTPException(500, detail=result)
    video = Path(result["video"]) if result.get("video") else OUTPUT / "stage.mp4"
    frame_count = int(result.get("frame_count") or 0)
    return {
        "ok": True,
        "instruction": instruction,
        "actions": actions_to_payload(actions),
        "timeline": result.get("timeline", []),
        "video_url": "/media/stage.mp4" if video.exists() else "",
        "video_error": result.get("video_error", ""),
        "frame_count": frame_count,
        "blend": result.get("blend"),
        "blender": result.get("blender"),
        "frames": result.get("frames"),
        "model": ", ".join(item["label"] for item in cast),
    }


@app.get("/media/stage.mp4")
def media():
    path = OUTPUT / "stage.mp4"
    if not path.exists():
        raise HTTPException(404, "还没有成片")
    return FileResponse(path, media_type="video/mp4")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
