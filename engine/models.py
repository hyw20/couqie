from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
ALLOWED = {".blend", ".fbx", ".glb", ".gltf", ".obj"}


def ensure_models_dir() -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    return MODELS


def list_models() -> list[dict]:
    ensure_models_dir()
    items = []
    for path in sorted(MODELS.iterdir()):
        if path.is_file() and path.suffix.lower() in ALLOWED:
            items.append({"name": path.name, "path": str(path), "suffix": path.suffix.lower()})
    return items


def resolve_model(name: str | None) -> Path | None:
    if not name or name in {"__default__", "默认方块人"}:
        return None
    ensure_models_dir()
    path = (MODELS / Path(name).name).resolve()
    if MODELS.resolve() not in path.parents and path.parent != MODELS.resolve():
        raise ValueError("非法模型路径")
    if not path.exists() or path.suffix.lower() not in ALLOWED:
        raise FileNotFoundError("找不到该模型，请先上传 glb/fbx/blend")
    return path


def save_upload(filename: str, data: bytes) -> Path:
    ensure_models_dir()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("只接受 .blend / .fbx / .glb / .gltf / .obj")
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-")
    if not safe:
        safe = f"model{suffix}"
    dest = MODELS / safe
    dest.write_bytes(data)
    return dest


def resolve_cast(names: list[str] | None, legacy: str | None = None) -> list[dict]:
    raw = [n for n in (names or []) if n is not None]
    if not raw:
        raw = [legacy or ""]
    out: list[dict] = []
    for n in raw[:6]:
        if not n or n in {"__default__", "__default2__", "默认方块人", "再加一名方块人"}:
            out.append({"model_path": "", "label": "默认方块人"})
            continue
        # *_arms.glb are Garry's Mod first-person arm models (43 bones, hands only, no
        # torso/legs). On a shared stage they read as a floating triangle, so they are not
        # offered as stage characters.
        if n.lower().endswith("_arms.glb"):
            continue
        path = resolve_model(n)
        out.append({"model_path": str(path), "label": n})
    return out or [{"model_path": "", "label": "默认方块人"}]
