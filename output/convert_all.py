"""Batch-convert every playermodel found under output/gmod_extract into models/*.glb.

Each character keeps its own texture directory (VTF -> TGA via Garry's Mod's own
bin/vtf2tga.exe, no downloads), then output/mdl_to_blender.py builds and exports the GLB.

Run:  py -3.12 output/convert_all.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GMOD_BIN = Path(r"C:\Program Files (x86)\Steam\steamapps\common\GarrysMod\bin")
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
EXTRACT = ROOT / "output" / "gmod_extract"
MODELS = ROOT / "models"
TEXROOT = ROOT / "output" / "textures_all"
VTF2TGA = GMOD_BIN / "vtf2tga.exe"


def find_models() -> list[tuple[str, Path, Path]]:
    """Return (char_name, mdl_path, vtf_dir) for every pm/npc model variant."""
    # Map every texture folder under materials/ by its folder name, longest match wins.
    tex_dirs: dict[str, Path] = {}
    for cand in EXTRACT.rglob("materials"):
        for sub in cand.rglob("*"):
            if sub.is_dir() and any(sub.rglob("*.vtf")):
                tex_dirs.setdefault(sub.name, sub)
    out = []
    for mdl in sorted(EXTRACT.rglob("*.mdl")):
        rel = mdl.relative_to(EXTRACT).parts
        variant = next((p for p in rel if p in ("pm", "npc", "arms")), None)
        if variant in (None, "npc"):
            continue  # npc duplicates the pm mesh
        # The character name lives in the FILE stem (e.g. tomori_live_clothing_pm), not in
        # the folder: one package can hold five characters under a shared folder.
        stem = mdl.stem
        for suffix in ("_pm", "_npc", "_arms"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        char = stem
        # The model stem may be "tomori_live_clothing" while the texture folder is "tomori";
        # try the longest folder name that is a prefix of the stem.
        vtf_dir = None
        for folder in sorted(tex_dirs, key=len, reverse=True):
            if char.startswith(folder):
                vtf_dir = tex_dirs[folder]
                break
        if vtf_dir is None:
            # fall back to the nearest materials/<anything> that holds this model's textures
            vtf_dir = next(EXTRACT.rglob("materials"))
        out.append((f"{char}_{variant}", mdl, vtf_dir))
    return out


def convert_textures(char: str, vtf_dir: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for vtf in vtf_dir.rglob("*.vtf"):
        name = vtf.stem
        if name in ("outline", "basewarp", "facewarp", "skinwarp", "none", "null"):
            continue  # warp/utility maps are not surface colour
        tga = dest / f"{name}.tga"
        if tga.exists() and tga.stat().st_size > 0:
            n += 1
            continue
        r = subprocess.run(
            [str(VTF2TGA), "-i", str(vtf), "-o", str(tga)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if tga.exists() and tga.stat().st_size > 0:
            n += 1
    return n


def main() -> None:
    found = find_models()
    print(f"found {len(found)} model variants")
    results = []
    for name, src, vtf_dir in found:
        tex = TEXROOT / name
        ntex = convert_textures(name, vtf_dir, tex)
        out = MODELS / f"{name}.glb"
        cmd = [
            str(BLENDER),
            "-b",
            "--factory-startup",
            "--python",
            str(ROOT / "output" / "mdl_to_blender.py"),
            "--",
            str(src),
            str(tex),
            str(out),
            name,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        built = next((l for l in p.stdout.splitlines() if l.startswith("BUILT")), "")
        err = next((l for l in p.stderr.splitlines() if "Error" in l), "")
        ok = out.exists() and out.stat().st_size > 100_000
        results.append((name, ok, ntex, built.strip()[:90] or err.strip()[:90]))
        print(f"{'OK ' if ok else 'FAIL'} {name:34s} tex={ntex:2d} {built.strip()[:80] or err.strip()[:80]}")
    (ROOT / "output" / "convert_report.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} converted")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
