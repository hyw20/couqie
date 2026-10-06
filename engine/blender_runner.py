from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "blender_scripts" / "stage.py"
# 工程在桌面目录下时，渲染帧会让资源管理器反复刷新图标
OUTPUT = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "couqie-stage"


def find_blender() -> Path:
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).exists():
        return Path(env)

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    foundation = program_files / "Blender Foundation"
    if foundation.exists():
        for folder in sorted(foundation.glob("Blender*"), reverse=True):
            exe = folder / "blender.exe"
            if exe.exists():
                return exe

    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
    for exe in local.glob("Blender*/blender.exe"):
        return exe

    which = subprocess.run(["where", "blender"], capture_output=True, text=True, shell=True)
    if which.returncode == 0:
        line = which.stdout.strip().splitlines()[0]
        if line and Path(line).exists():
            return Path(line)

    raise FileNotFoundError("未找到 Blender，请确认安装完成后再试。")


def run_stage(
    actions: list[dict],
    instruction: str,
    model_path: str | None = None,
    cast: list[dict] | None = None,
) -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    job = OUTPUT / "job.json"
    job.write_text(
        json.dumps(
            {
                "actions": actions,
                "instruction": instruction,
                "output_dir": str(OUTPUT),
                "model_path": model_path or "",
                "cast": cast or [{"model_path": model_path or ""}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    blender = find_blender()
    cmd = [
        str(blender),
        "--background",
        "--python",
        str(SCRIPT),
        "--",
        str(job),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    result_path = OUTPUT / "result.json"
    result = {
        "ok": False,
        "blender": str(blender),
        "returncode": completed.returncode,
        "log_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }
    if not result_path.exists():
        result["error"] = "Blender 未写出结果，请看日志"
        return result
    result.update(json.loads(result_path.read_text(encoding="utf-8")))
    frames_dir = Path(result.get("frames_dir") or (OUTPUT / "frames"))
    pngs = sorted(frames_dir.glob("frame_*.png"))
    if not pngs:
        result["ok"] = False
        result["error"] = "没有渲染出帧"
        return result
    result["ok"] = True
    result["frame_count"] = len(pngs)
    result["video"] = None
    try:
        import imageio_ffmpeg

        video = OUTPUT / "stage.mp4"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        encode = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-framerate",
                "24",
                "-i",
                str(frames_dir / "frame_%04d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if encode.returncode == 0 and video.exists():
            result["video"] = str(video)
        else:
            result["video_error"] = (encode.stderr or encode.stdout or "")[-500:]
    except Exception as exc:
        # Surface this instead of silently dropping the mp4: the render still works, so a
        # missing ffmpeg dependency used to look like a success with no output file.
        result["video_error"] = f"{type(exc).__name__}: {exc}"
    return result
