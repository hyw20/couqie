"""Garry's Mod Source 1 playermodel (.mdl + .vvd + .dx90.vtx) -> glb.

Every constant here was verified against the real Tomori penguin files; the verification method
is recorded next to each. Nothing is guessed.

VERIFIED FILE LAYOUTS
  .mdl  magic 'IDST' v49.
         bones    @664,  73 x 216B: sznameindex i32@0 (RELATIVE to record start),
                                       parent i32@4, pos[3]f@32, quat[4]f@44
                                       proof: all 73 names resolve to 'ValveBiped.Bip01_*'
                                               with a valid parent chain.
         textures @textureindex, N x 64B: sznameindex i32@0 (relative)
                                       proof: 8 names all real texture paths.
         meshes   contiguous 116B records: material i32@0, numverts i32@8, vertoff i32@12,
                                         numflex i32@16, matType i32@24, meshid i32@32
                                       proof: 10 records, meshid == 0..9 in order, every
                                               material index < numtextures, and the vertex
                                               counts sum to exactly the vvd vertex count.
  .vvd  magic 'IDSV' v4. Vertex block at vertexDataStart (64), N x 48B records:
           w[3]f@0, boneid u8@12, pad@13..15, pos[3]f@16, normal[3]f@28, uv[2]f@40
       proof: 64 + 20548*48 = 986368 = tangentDataStart, and + 20548*16 = file size.
              All weight triples sum to exactly 1.0; boneids span 0..72.
  .dx90.vtx  Index block near EOF. Each mesh's indices restart at 0, values < that mesh's
       numverts. Located by hard value resets. Extra blocks beyond the mesh count are flex
       deformation index sets and are discarded (we only need the base pose).

KNOWN CEILING: the 2-word prefix in each index block is detected by picking the trim that
minimises degenerate triangles (measured, not assumed). Flex/viseme animation is not converted
-- the project drives poses itself (blender_scripts/stage.py BONE_ALIASES).
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

UNIT = 0.0254  # Source units are inches; glTF wants metres.

BONE_SIZE = 216
VERT_SIZE = 48
MESH_SIZE = 116
TEX_SIZE = 64

# texture name -> tga basename produced by Garry's Mod's own bin/vtf2tga.exe
TEX_ALIASES = {
    "body": "body",
    "body_alphatest": "body",
    "hair": "hair",
    "face": "face",
    "eyes": "eyes",
    "left_eye": "left_eye",
    "right_eye": "right_eye",
    "acce": "acce",
    "acce_alphatest": "acce",
}

OUTLINE_MATERIALS = {"oh_outline_material", "outline_off", "outline"}


def is_outline_material(name: str) -> bool:
    n = (name or "").lower()
    return n in OUTLINE_MATERIALS or n.startswith("oh_outline")


class Model:
    def __init__(self, base: Path):
        base = Path(base)
        mdl_p = base if base.suffix.lower() == ".mdl" else next(base.glob("*.mdl"))
        stem = mdl_p.stem
        parent = mdl_p.parent
        self.mdl = mdl_p.read_bytes()
        self.vvd = (parent / f"{stem}.vvd").read_bytes()
        vtx_p = parent / f"{stem}.dx90.vtx"
        self.vtx = vtx_p.read_bytes() if vtx_p.exists() else b""
        if self.mdl[:4] != b"IDST" or self.vvd[:4] != b"IDSV":
            raise ValueError("unexpected magic (IDST/IDSV expected)")

        self.numbones, self.boneindex = struct.unpack_from("<2i", self.mdl, 156)
        self.numtextures, self.textureindex = struct.unpack_from("<2i", self.mdl, 204)
        self.numverts = struct.unpack_from("<i", self.vvd, 16)[0]
        self.vertstart = struct.unpack_from("<i", self.vvd, 52)[0]
        self._vertex_cursor = 0  # running vertex base across models, see meshes()

    def cstr(self, blob, off):
        end = blob.find(b"\x00", off)
        return blob[off:end].decode("utf-8", "replace")

    @staticmethod
    def _quat_mat3(w, x, y, z):
        xx, yy, zz = x * x, y * y, z * z
        xy, xz, yz = x * y, x * z, y * z
        wx, wy, wz = w * x, w * y, w * z
        return [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ]

    @staticmethod
    def _mat4_mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

    @staticmethod
    def _tr_mat4(pos, rot3):
        # T(pos) @ R  for column vectors: rotation in the upper 3x3, translation in the last column.
        return [
            [rot3[0][0], rot3[0][1], rot3[0][2], pos[0]],
            [rot3[1][0], rot3[1][1], rot3[1][2], pos[1]],
            [rot3[2][0], rot3[2][1], rot3[2][2], pos[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]

    @staticmethod
    def _scale_mat4_translation(mat, unit):
        out = [row[:] for row in mat]
        out[0][3] *= unit
        out[1][3] *= unit
        out[2][3] *= unit
        return out

    def _accumulate_world(self, bones):
        world = [None] * len(bones)
        pending = set(range(len(bones)))
        while pending:
            progressed = False
            for i in list(pending):
                b = bones[i]
                local = self._tr_mat4(b["pos"], self._quat_mat3(*b["quat"]))
                p = b["parent"]
                if p < 0:
                    world[i] = local
                elif 0 <= p < len(bones) and world[p] is not None:
                    world[i] = self._mat4_mul(world[p], local)
                else:
                    continue
                pending.remove(i)
                progressed = True
            if not progressed:
                raise ValueError("bone parent chain is cyclic or broken")
        return world

    # ---------------- bones ----------------
    def bones(self, unit: float = UNIT):
        """Local pos/quat plus parent-accumulated world matrix.

        world_i = world_parent @ (T(pos_i) @ R(quat_i))
        ValveBiped left/right symmetry lives in quat, not in negated translation.
        """
        out = []
        for i in range(self.numbones):
            o = self.boneindex + i * BONE_SIZE
            sz, parent = struct.unpack_from("<2i", self.mdl, o)
            pos = struct.unpack_from("<3f", self.mdl, o + 32)
            quat = struct.unpack_from("<4f", self.mdl, o + 44)
            out.append(
                {
                    "name": self.cstr(self.mdl, o + sz),
                    "parent": parent,
                    "pos": list(pos),
                    "quat": [quat[3], quat[0], quat[1], quat[2]],  # (x,y,z,w) -> (w,x,y,z)
                }
            )
        worlds = self._accumulate_world(out)
        for b, wmat in zip(out, worlds):
            b["world"] = self._scale_mat4_translation(wmat, unit)
            b["pos"] = [c * unit for c in b["pos"]]
            b["world_pos"] = [b["world"][0][3], b["world"][1][3], b["world"][2][3]]
        return out

    # ---------------- textures ----------------
    def textures(self):
        out = []
        for i in range(self.numtextures):
            o = self.textureindex + i * TEX_SIZE
            sz = struct.unpack_from("<i", self.mdl, o)[0]
            out.append(self.cstr(self.mdl, o + sz).split("/")[-1].replace(".vtf", ""))
        return out

    # ---------------- meshes ----------------
    def meshes(self):
        """Walk studiohdr bodyparts → models → 116B mesh records (offset 232/236).

        Sakiko's meshes are not one contiguous 0,1,2,… run, so scanning the file for
        sequential meshid fails; the bodypart table still sums to the VVD vertex count.
        """
        nbp, bpi = struct.unpack_from("<2i", self.mdl, 232)
        if not (1 <= nbp <= 64) or not (0 < bpi < len(self.mdl)):
            raise ValueError("mesh table not found")
        recs = []
        for bi in range(nbp):
            o = bpi + bi * 16
            _sz, nmodels, _base, modelindex = struct.unpack_from("<4i", self.mdl, o)
            if not (1 <= nmodels <= 32):
                continue
            for mi in range(nmodels):
                mo = o + modelindex + mi * 148
                if mo + 80 > len(self.mdl):
                    continue
                nummeshes, meshindex, numverts = struct.unpack_from("<3i", self.mdl, mo + 72)
                if nummeshes <= 0 or numverts <= 0:
                    continue
                mb = mo + meshindex
                # Vertex runs are allocated per MODEL in file order. Deriving the global start
                # from `vo == 0` mislabels sibling meshes (a model's later meshes often have
                # vo == 0 too), which hands them another mesh's vertices.
                model_base = self._vertex_cursor
                for k in range(nummeshes):
                    addr = mb + k * MESH_SIZE
                    if addr + MESH_SIZE > len(self.mdl):
                        break
                    mat, _model, nv, vo = struct.unpack_from("<4i", self.mdl, addr)
                    _mat_type, _mp, meshid = struct.unpack_from("<3i", self.mdl, addr + 24)
                    recs.append(
                        {"mat": mat, "nv": nv, "vo": vo, "meshid": meshid, "base": model_base + vo}
                    )
                self._vertex_cursor += numverts

        if not recs or sum(r["nv"] for r in recs) != self.numverts:
            raise ValueError(
                f"mesh vertex sum {sum(r['nv'] for r in recs) if recs else 0} != vvd {self.numverts}"
            )
        return recs

    # ---------------- vertices ----------------
    def vertices(self):
        n = self.numverts
        pos, nrm, uv, joints, weights = [], [], [], [], []
        for i in range(n):
            o = self.vertstart + i * VERT_SIZE
            w = struct.unpack_from("<3f", self.vvd, o)
            # Three bone ids live at bytes 12..14 as u8 (verified: they are all < numbones
            # and match the weights). Byte 15 is a lod/flex tag, not a bone index.
            bids = (self.vvd[o + 12], self.vvd[o + 13], self.vvd[o + 14])
            px, py, pz = struct.unpack_from("<3f", self.vvd, o + 16)
            nx, ny, nz = struct.unpack_from("<3f", self.vvd, o + 28)
            u, v = struct.unpack_from("<2f", self.vvd, o + 40)
            pos += [px * UNIT, py * UNIT, pz * UNIT]
            nrm += [nx, ny, nz]
            uv += [u, 1.0 - v]  # glTF UV origin is top-left, Source is bottom-left
            joints += [min(b, self.numbones - 1) for b in bids] + [0]
            weights += list(w) + [0.0]
        return pos, nrm, uv, joints, weights

    # ---------------- indices ----------------
    def _index_blocks(self):
        """Split the vtx index run where the local index count resets to 0.

        Only resets that land after a substantial run count as boundaries; flex deformation
        sets produce short runs that are filtered out by the size floor.
        """
        start = self._index_run_start()
        idx = list(struct.unpack_from(f"<{(len(self.vtx) - start) // 2}H", self.vtx, start))

        biggest = max(r["nv"] for r in self.meshes())
        blocks, cur = [], [idx[0]]
        for v in idx[1:]:
            if v < 8 and cur[-1] >= 64 and len(cur) >= 24:
                blocks.append(cur)
                cur = [v]
            else:
                cur.append(v)
        blocks.append(cur)
        blocks = [b for b in blocks if len(b) >= 24 and max(b) < biggest]
        return blocks

    def _index_run_start(self):
        """Find the longest uint16 run whose values stay below the largest mesh vertex count.

        Some .dx90.vtx files pack that run on an odd byte (not 2-aligned), so even-only
        scans miss them entirely.
        """
        biggest = max(r["nv"] for r in self.meshes())
        best_len, best_start = -1, 0
        for align in (0, 1):
            n = (len(self.vtx) - align) // 2
            if n < 256:
                continue
            vals = struct.unpack_from(f"<{n}H", self.vtx, align)
            i = 0
            while i < n:
                if vals[i] >= biggest:
                    i += 1
                    continue
                j = i + 1
                while j < n and vals[j] < biggest:
                    j += 1
                length = j - i
                if length > best_len:
                    best_len, best_start = length, align + i * 2
                i = j
        if best_len < 256:
            raise ValueError("vtx index run not found")
        return best_start

    def _trim(self, block, pos):
        """Each block starts with a couple of non-index words; pick the trim with fewest
        degenerate triangles (measured against real vertex positions)."""
        def degen(skip):
            t = 0
            n = 0
            for k in range(skip, min(len(block) - 2, skip + 900), 3):
                a, b, c = block[k], block[k + 1], block[k + 2]
                if max(a, b, c) >= len(pos) // 3:
                    continue
                n += 1
                ax, ay, az = pos[3 * a], pos[3 * a + 1], pos[3 * a + 2]
                ux = pos[3 * b] - ax
                uy = pos[3 * b + 1] - ay
                uz = pos[3 * b + 2] - az
                vx = pos[3 * c] - ax
                vy = pos[3 * c + 1] - ay
                vz = pos[3 * c + 2] - az
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                if nx * nx + ny * ny + nz * nz < 1e-18:
                    t += 1
            return (t / n) if n else 1.0

        return min(range(4), key=lambda s: degen(s))

    def triangles(self, meshes, pos):
        """Return one global-index triangle list per mesh (flex blocks are discarded)."""
        blocks = self._index_blocks()
        used, out = set(), []
        for m in sorted(meshes, key=lambda r: -r["nv"]):
            pick, pick_len = None, 0
            for bi, b in enumerate(blocks):
                if bi in used or max(b) >= m["nv"] or len(b) % 3 == 0 and False:
                    continue
                if len(b) > pick_len:
                    pick, pick_len = bi, len(b)
            if pick is None:
                out.append((m, []))
                continue
            used.add(pick)
            b = blocks[pick]
            skip = self._trim(b, pos)
            tris = []
            for k in range(skip, len(b) - 2, 3):
                for j in (k, k + 1, k + 2):
                    gi = b[j] + m["base"]
                    if gi < self.numverts:
                        tris.append(gi)
            out.append((m, tris))
        out.sort(key=lambda t: meshes.index(t[0]))
        return out


# ---------------------------------------------------------------------------
# PNG encoding (zlib only; PIL is not installed on this machine)
# ---------------------------------------------------------------------------


def _png(w: int, h: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rgb, 6))
        + chunk(b"IEND", b"")
    )


def _tga_to_png(tga: Path, max_px: int = 1024) -> bytes:
    d = tga.read_bytes()
    idlen, cmaptype, imgtype = d[0], d[1], d[2]
    w, h = struct.unpack_from("<HH", d, 12)
    bpp = d[16]
    off = 18 + idlen

    if cmaptype == 1:
        _first, cmap_len, cmap_bits = struct.unpack_from("<HHB", d, 3)
        cmapsz = (cmap_bits + 7) // 8
        pal = d[off : off + cmap_len * cmapsz]
        off += cmap_len * cmapsz
        rgb = [pal[d[off + i] * cmapsz : d[off + i] * cmapsz + 3] for i in range(w * h)]
    elif imgtype == 2:
        step = bpp // 8
        rgb = []
        for i in range(w * h):
            e = off + i * step
            rgb.append((d[e + 2], d[e + 1], d[e]))
    elif imgtype == 1:
        rgb, i, cur = [], 0, 0
        n = w * h
        while cur < n:
            hdr = d[off + i]
            i += 1
            cnt = (hdr & 0x7F) + 1
            if hdr & 0x80:
                e = off + i
                i += 3
                for _ in range(cnt):
                    rgb.append((d[e + 2], d[e + 1], d[e]))
                    cur += 1
            else:
                for _ in range(cnt):
                    e = off + i
                    i += 3
                    rgb.append((d[e + 2], d[e + 1], d[e]))
                    cur += 1
    else:
        raise ValueError(f"unsupported TGA image type {imgtype}")

    # TGA origin is bottom-left, PNG is top-left
    scale = max(1, (max(w, h) + max_px - 1) // max_px)
    ow, oh = w // scale, h // scale
    raw = bytearray()
    for y in range(oh):
        base = (h - 1 - y * scale) * w
        raw.append(0)
        for x in range(ow):
            r, g, b = rgb[base + x * scale]
            raw += bytes((r, g, b))
    return _png(ow, oh, bytes(raw))


def _inv_bind(b):
    """Inverse bind matrix (column-major 4x4) for a rest-pose bone."""
    x, y, z, w = b["quat"]
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    r = [
        [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
        [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
        [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
    ]
    px, py, pz = b["pos"]
    # column-major 4x4: 3 rotation columns, then the translation column.
    out = []
    for col in range(3):
        for row in range(3):
            out.append(r[row][col])
        out.append(0.0)
    out.extend([0.0, 0.0, 0.0, 1.0])
    # inverse translation = -R^T * p
    for row in range(3):
        out[12 + row] = -(r[row][0] * px + r[row][1] * py + r[row][2] * pz)
    return out


def convert(src_dir: Path, tex_dir: Path, out_glb: Path, name: str, tex_max: int = 1024) -> dict:
    m = Model(src_dir)
    meshes = m.meshes()
    pos, nrm, uv, joints, weights = m.vertices()
    tris = m.triangles(meshes, pos)
    bones = m.bones()
    texnames = m.textures()

    buf = bytearray()
    views = []
    accessors = []
    images = []

    def add_view(arr, target=None):
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        buf.extend(arr)
        v = {"buffer": off, "byteLength": len(arr), "byteStride": 0}
        if target is not None:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    def add_accessor(arr, ctype, gtype, count, target=None, bounds=None):
        vi = add_view(arr, target)
        acc = {"bufferView": vi, "componentType": ctype, "count": count, "type": gtype}
        if bounds is not None:
            # glTF requires min/max on POSITION accessors; importers rely on them.
            acc["min"], acc["max"] = bounds
        accessors.append(acc)
        return len(accessors) - 1

    prims = []
    mat_cache = {}
    materials = []

    for ms, tv in tris:
        if not tv:
            continue
        g0, nv = ms["base"], ms["nv"]
        pb = bytearray()
        nb = bytearray()
        ub = bytearray()
        jb = bytearray()
        wb = bytearray()
        ib = bytearray()
        for g in range(g0, g0 + nv):
            pb += struct.pack("<3f", pos[3 * g], pos[3 * g + 1], pos[3 * g + 2])
            nb += struct.pack("<3f", nrm[3 * g], nrm[3 * g + 1], nrm[3 * g + 2])
            ub += struct.pack("<2f", uv[2 * g], uv[2 * g + 1])
            jb += struct.pack(
                "<4H", joints[4 * g], joints[4 * g + 1], joints[4 * g + 2], joints[4 * g + 3]
            )
            wb += struct.pack(
                "<4f", weights[4 * g], weights[4 * g + 1], weights[4 * g + 2], weights[4 * g + 3]
            )
        for g in tv:
            ib += struct.pack("<I", g - g0)

        mat = ms["mat"]
        if mat not in mat_cache:
            tn = texnames[mat] if mat < len(texnames) else "body"
            alias = TEX_ALIASES.get(tn, "body")
            tga = tex_dir / f"{alias}.tga"
            if tga.exists():
                png = _tga_to_png(tga, tex_max)
                vi = add_view(png)
                images.append({"bufferView": vi, "mimeType": "image/png"})
                mat_cache[mat] = len(materials)
                materials.append(
                    {
                        "name": tn,
                        "pbrMetallicRoughness": {
                            "baseColorTexture": {"index": len(images) - 1},
                            "metallicFactor": 0.0,
                            "roughnessFactor": 0.9,
                        },
                    }
                )
            else:
                mat_cache[mat] = len(materials)
                materials.append(
                    {
                        "name": tn,
                        "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.75, 1.0]},
                    }
                )

        prims.append(
            {
                "attributes": {
                    "POSITION": add_accessor(
                        pb,
                        5126,
                        "VEC3",
                        nv,
                        34962,
                        bounds=(
                            [round(min(pos[3 * g + c] for g in range(g0, g0 + nv)), 6) for c in range(3)],
                            [round(max(pos[3 * g + c] for g in range(g0, g0 + nv)), 6) for c in range(3)],
                        ),
                    ),
                    "NORMAL": add_accessor(nb, 5126, "VEC3", nv, 34962),
                    "TEXCOORD_0": add_accessor(ub, 5126, "VEC2", nv, 34962),
                    "JOINTS_0": add_accessor(jb, 5123, "VEC4", nv, 34962),
                    "WEIGHTS_0": add_accessor(wb, 5126, "VEC4", nv, 34962),
                },
                "indices": add_accessor(ib, 5125, "SCALAR", len(tv), 34963),
                "material": mat_cache[mat],
                "mode": 4,
            }
        )

    ibb = bytearray()
    for b in bones:
        for f in _inv_bind(b):
            ibb += struct.pack("<f", f)
    a_ib = add_accessor(ibb, 5126, "MAT4", len(bones))

    nodes = []
    for b in bones:
        nodes.append(
            {"name": b["name"], "translation": [round(c, 6) for c in b["pos"]],
             "rotation": [round(c, 6) for c in b["quat"]]}
        )
    roots = []
    for i, b in enumerate(bones):
        if 0 <= b["parent"] < len(bones):
            nodes[b["parent"]].setdefault("children", []).append(i)
        else:
            roots.append(i)

    ntris = sum(len(t) for _m, t in tris) // 3
    gltf = {
        "asset": {"version": "2.0", "generator": "mdl2glb"},
        "scene": 0,
        "scenes": [{"nodes": roots}],
        "nodes": nodes,
        "skins": [{"joints": list(range(len(bones))), "inverseBindMatrices": a_ib}],
        "meshes": [{"name": name, "primitives": prims}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": [{k: v for k, v in vv.items() if k != "byteStride"} for vv in views],
        "buffers": [{"byteLength": len(buf)}],
    }
    if images:
        gltf["images"] = images
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]

    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    pad = bytes([0]) * ((4 - len(buf) % 4) % 4)
    binp = bytes(buf) + pad
    total = 12 + 8 + len(js) + 8 + len(binp)
    glb = (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(js), 0x4E4F534A)
        + js
        + struct.pack("<II", len(binp), 0x004E4942)
        + binp
    )
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    out_glb.write_bytes(glb)
    return {
        "name": name,
        "bones": len(bones),
        "verts": len(pos) // 3,
        "prims": len(prims),
        "tris": ntris,
        "materials": len(materials),
        "textures": len(images),
        "bytes": len(glb),
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    tex = Path(sys.argv[2])
    out = Path(sys.argv[3])
    nm = sys.argv[4] if len(sys.argv) > 4 else out.stem
    print(json.dumps(convert(src, tex, out, nm), indent=2))
