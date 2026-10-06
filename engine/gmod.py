"""Detect a local Garry's Mod install and its downloaded workshop content."""

from __future__ import annotations

import os
import re
from pathlib import Path

# GMod's Steam AppID is 4000 (NOT 400) and its install dir is "GarrysMod" (no apostrophe).
APPID = "4000"
STEAM_ROOTS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
]


def _steam_stem() -> Path | None:
    try:
        p = Path(os.environ.get("SteamPath", ""))
        if p.exists():
            return p
    except OSError:
        pass
    return None


def find_install() -> Path | None:
    """Return the Garry's Mod install dir, or None if not installed."""
    roots = list(STEAM_ROOTS)
    extra = _steam_stem()
    if extra:
        roots.insert(0, extra)
    for root in roots:
        candidate = root / "steamapps" / "common" / "GarrysMod"
        if (candidate / "gmod_win64.exe").exists():
            return candidate
    return None


def _subscribed_ids(steamapps: Path) -> list[str]:
    """steamapps is the folder containing common/, workshop/ and appmanifest_*.acf.

    Returns item ids from the WorkshopItemsInstalled block. We deliberately do not try to
    also count WorkshopItemDetails: if the two disagree, treat the manifest as unusable
    rather than guessing which number is right.
    """
    acf = steamapps / "workshop" / f"appworkshop_{APPID}.acf"
    if not acf.exists():
        return []
    text = acf.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"WorkshopItemsInstalled"\s*\{', text)
    if not m:
        return []
    # Walk the brace depth to the matching close brace, so nested per-item blocks are skipped.
    depth, i = 0, m.end() - 1
    for j in range(m.end() - 1, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                block = text[m.end() : j]
                # top-level entries only: depth 1 in the block == the id lines
                ids = re.findall(r'^\t\t"(\d{6,})"\s*$', block, re.MULTILINE)
                return sorted(set(ids))
    return []


def probe() -> dict:
    """Report GMod install + workshop status for the /api/status endpoint."""
    install = find_install()
    if install is None:
        return {
            "gmod": False,
            "gmod_note": "未找到 Garry's Mod 安装（steamapps\\common\\GarrysMod）。装了之后可从工坊导出模型再上传。",
        }

    steamapps = install.parent.parent  # .../steamapps/common/GarrysMod -> .../steamapps
    content = steamapps / "workshop" / "content" / APPID
    ids = _subscribed_ids(steamapps)
    downloaded = sorted(p.name for p in content.iterdir()) if content.exists() else []

    if not ids:
        note = "GMod 已安装，但没检测到工坊订阅。"
    elif not downloaded:
        note = "GMod 已安装，工坊订阅还没下载完。"
    else:
        note = f"GMod 已安装，工坊已下载 {len(downloaded)} 个物品。工坊模型是 Source 1 .mdl，需转成 glb/fbx 后上传。"

    return {
        "gmod": True,
        "gmod_note": note,
        "gmod_install": str(install),
        "gmod_subscribed": len(ids),
        "gmod_downloaded": len(downloaded),
    }
