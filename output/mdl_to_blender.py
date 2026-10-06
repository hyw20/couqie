"""Build the model in Blender from the MDL data, then let Blender export the GLB.

Hand-writing a glTF container is the wrong rung: the scene graph needs a mesh node, skins
need joint bookkeeping, and importers validate strictly. Blender already does all of it.

Run:  blender -b --factory-startup --python output/mdl_to_blender.py -- <src> <texdir> <out.glb> <name>

The MDL/VVD/VTX parsing lives in mdl2glb.Model and is unchanged -- it is verified.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdl2glb import TEX_ALIASES, Model, is_outline_material  # noqa: E402

UNIT = 0.0254


def build(src: Path, tex_dir: Path, out_glb: Path, name: str) -> None:
    m = Model(src)
    meshes = m.meshes()
    pos, nrm, uv, joints, weights = m.vertices()
    tris = m.triangles(meshes, pos)
    bones = m.bones()
    texnames = m.textures()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # ---- skeleton ----
    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new(name, arm_data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    made = []
    for i, b in enumerate(bones):
        e = eb.new(b["name"])
        world = Matrix(b["world"])
        head = world.to_translation()
        axis = world.to_3x3() @ Vector((0.0, 0.05, 0.0))
        if axis.length < 1e-5:
            axis = Vector((0.0, 0.05, 0.0))
        e.head = head
        e.tail = head + axis
        e.matrix = world
        made.append(e)
    for i, b in enumerate(bones):
        p = b["parent"]
        if 0 <= p < len(bones):
            made[i].parent = made[p]
            made[i].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    # ---- meshes, one per material group ----
    mat_objs = {}
    for mi, tv in tris:
        if not tv:
            continue
        tname = texnames[mi["mat"]] if mi["mat"] < len(texnames) else "body"
        if is_outline_material(tname):
            continue
        g0, nv = mi["base"], mi["nv"]
        me = bpy.data.meshes.new(f"{name}_{mi['mat']}_{len(mat_objs)}")
        obj = bpy.data.objects.new(me.name, me)
        scene.collection.objects.link(obj)

        faces = [(tv[3 * k], tv[3 * k + 1], tv[3 * k + 2]) for k in range(len(tv) // 3)]
        me.from_pydata(
            [(pos[3 * g], pos[3 * g + 1], pos[3 * g + 2]) for g in range(g0, g0 + nv)],
            [],
            [(a - g0, b - g0, c - g0) for a, b, c in faces],
        )
        me.update(calc_edges=True)

        uv_layer = me.uv_layers.new(name="UVMap")
        for li in range(len(me.loops)):
            gi = g0 + me.loops[li].vertex_index
            uv_layer.data[li].uv = (uv[2 * gi], uv[2 * gi + 1])

        # Vertex groups follow the MDL bone ids AND weights. 64% of these vertices are
        # blended across two or three bones, so hard-coding 1.0 on the primary bone tears
        # the surface into facets -- that was the "diamond shards" symptom.
        for b in range(m.numbones):
            members: dict[int, float] = {}
            for g in range(g0, g0 + nv):
                for j in range(3):
                    wgt = weights[4 * g + j]
                    if wgt > 1e-4 and joints[4 * g + j] == b:
                        local = g - g0
                        if members.get(local, 0.0) < wgt:
                            members[local] = wgt
            if members:
                vg = obj.vertex_groups.new(name=bones[b]["name"])
                for local, wgt in members.items():
                    vg.add([local], wgt, "REPLACE")

        # A few source vertices carry all-zero weights; bind them fully to their primary
        # bone so they do not float loose when the armature deforms.
        loose = [
            g - g0
            for g in range(g0, g0 + nv)
            if not any(weights[4 * g + j] > 1e-4 for j in range(3))
        ]
        if loose:
            for local in loose:
                g = g0 + local
                bid = min(joints[4 * g], m.numbones - 1)
                name = bones[bid]["name"]
                vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                vg.add([local], 1.0, "REPLACE")

        # material
        tname = texnames[mi["mat"]] if mi["mat"] < len(texnames) else "body"
        alias = TEX_ALIASES.get(tname, tname)
        img = None
        seen = []
        for key in (tname, alias, "left_eye" if tname == "eyes" else "", "right_eye" if tname == "eyes" else ""):
            if not key or key in seen:
                continue
            seen.append(key)
            for ext in (".tga", ".png"):
                p = tex_dir / f"{key}{ext}"
                if p.exists():
                    img = bpy.data.images.load(str(p))
                    break
            if img:
                break
        mat = bpy.data.materials.new(tname)
        mat.use_backface_culling = False
        if img:
            mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
                1.0, 1.0, 1.0, 1.0
            )
            tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex_node.image = img
            mat.node_tree.links.new(
                tex_node.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"]
            )
        me.materials.append(mat)
        mat_objs[mi["mat"]] = obj

    # ---- skin ----
    bpy.context.view_layer.objects.active = arm
    for obj in mat_objs.values():
        mod = obj.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        obj.parent = arm

    arm_data.pose_position = "POSE"
    bpy.context.view_layer.update()

    out_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out_glb),
        export_format="GLB",
        use_selection=False,
        export_skins=True,
        export_animations=False,
        export_influence_nb=4,
        export_yup=True,
        export_apply=False,
    )

    nt = sum(len(o.data.polygons) for o in mat_objs.values())
    print(
        f"BUILT name={name} bones={len(bones)} verts={len(pos)//3} "
        f"objects={len(mat_objs)} tris={nt} out={out_glb} bytes={out_glb.stat().st_size}"
    )


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1 :]
    # Blender runs with its own cwd, so resolve every path against the project root.
    root = Path(__file__).resolve().parent.parent
    src = Path(argv[0])
    if not src.is_absolute():
        src = root / src
    tex = Path(argv[1])
    if not tex.is_absolute():
        tex = root / tex
    out = Path(argv[2])
    if not out.is_absolute():
        out = root / out
    build(src, tex, out, argv[3] if len(argv) > 3 else "Model")