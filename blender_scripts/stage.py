"""Blender 后台脚本：搭一个简易人偶，按指令关键帧，渲染小剧场。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector


def job_path() -> Path:
    argv = sys.argv
    if "--" in argv:
        return Path(argv[argv.index("--") + 1])
    return Path(__file__).resolve().parent.parent / "output" / "job.json"


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.meshes) + list(bpy.data.armatures) + list(bpy.data.materials):
        bpy.data.batch_remove([block])


def make_mat(name: str, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    return mat


def add_cube(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(location=loc, scale=scale)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def bind_to_bone(obj, arm, bone):
    con = obj.constraints.new("CHILD_OF")
    con.target = arm
    con.subtarget = bone
    if hasattr(con, "set_inverse_pending"):
        con.set_inverse_pending = True
    else:
        bpy.context.view_layer.update()
        pb = arm.pose.bones[bone]
        con.inverse_matrix = (arm.matrix_world @ pb.matrix).inverted() @ obj.matrix_world


def add_sphere(name, loc, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def create_rig(name: str = "Actor", cloth_rgb=(0.35, 0.45, 0.78)):
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 1.05))
    arm = bpy.context.object
    arm.name = name
    bpy.ops.armature.select_all(action="SELECT")
    bpy.ops.armature.delete()

    eb = arm.data.edit_bones

    def bone(bname, head, tail, parent=None, roll=0.0):
        b = eb.new(bname)
        b.head = head
        b.tail = tail
        b.roll = roll
        if parent:
            b.parent = eb[parent]
        return b

    bone("Root", (0, 0, 0.0), (0, 0, 0.2))
    bone("Spine", (0, 0, 0.2), (0, 0, 0.85), "Root")
    bone("Head", (0, 0, 0.85), (0, 0, 1.2), "Spine")
    bone("Jaw", (0, -0.02, 1.02), (0, -0.10, 0.96), "Head")
    bone("L_Eye", (0.05, -0.12, 1.12), (0.05, -0.18, 1.12), "Head")
    bone("R_Eye", (-0.05, -0.12, 1.12), (-0.05, -0.18, 1.12), "Head")
    bone("L_Brow", (0.05, -0.13, 1.18), (0.05, -0.18, 1.18), "Head")
    bone("R_Brow", (-0.05, -0.13, 1.18), (-0.05, -0.18, 1.18), "Head")
    bone("Mouth", (0, -0.13, 1.02), (0, -0.18, 1.02), "Head")
    # 手臂侧平举，沿 X 轴，挥手时绕 Y/Z 转才不会拧进身体
    bone("L_UpperArm", (0.22, 0, 0.78), (0.50, 0, 0.78), "Spine")
    bone("L_ForeArm", (0.50, 0, 0.78), (0.76, 0, 0.78), "L_UpperArm")
    bone("R_UpperArm", (-0.22, 0, 0.78), (-0.50, 0, 0.78), "Spine")
    bone("R_ForeArm", (-0.50, 0, 0.78), (-0.76, 0, 0.78), "R_UpperArm")
    bone("L_Thigh", (0.1, 0, 0.2), (0.1, 0, -0.2), "Root")
    bone("L_Shin", (0.1, 0, -0.2), (0.1, 0, -0.55), "L_Thigh")
    bone("R_Thigh", (-0.1, 0, 0.2), (-0.1, 0, -0.2), "Root")
    bone("R_Shin", (-0.1, 0, -0.2), (-0.1, 0, -0.55), "R_Thigh")

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    for pbone in arm.pose.bones:
        pbone.rotation_mode = "XYZ"

    skin = make_mat(f"{name}_Skin", (0.95, 0.82, 0.72))
    cloth = make_mat(f"{name}_Cloth", cloth_rgb)
    hair = make_mat(f"{name}_Hair", (0.18, 0.14, 0.16))
    shoe = make_mat(f"{name}_Shoe", (0.12, 0.12, 0.14))
    ink = make_mat(f"{name}_Ink", (0.08, 0.08, 0.09))
    white = make_mat(f"{name}_White", (0.95, 0.95, 0.96))
    lip = make_mat(f"{name}_Lip", (0.72, 0.28, 0.32))

    z = 1.05
    parts = [
        (f"{name}_torso", (0, 0, z + 0.47), (0.22, 0.12, 0.32), cloth, "Spine"),
        (f"{name}_head", (0, 0, z + 1.07), (0.16, 0.16, 0.16), skin, "Head"),
        (f"{name}_hair", (0, 0.04, z + 1.19), (0.17, 0.18, 0.08), hair, "Head"),
        (f"{name}_larm", (0.36, 0, z + 0.78), (0.14, 0.065, 0.065), cloth, "L_UpperArm"),
        (f"{name}_lfarm", (0.63, 0, z + 0.78), (0.13, 0.055, 0.055), skin, "L_ForeArm"),
        (f"{name}_rarm", (-0.36, 0, z + 0.78), (0.14, 0.065, 0.065), cloth, "R_UpperArm"),
        (f"{name}_rfarm", (-0.63, 0, z + 0.78), (0.13, 0.055, 0.055), skin, "R_ForeArm"),
        (f"{name}_lthigh", (0.1, 0, z), (0.08, 0.08, 0.18), cloth, "L_Thigh"),
        (f"{name}_lshin", (0.1, 0, z - 0.37), (0.07, 0.07, 0.16), cloth, "L_Shin"),
        (f"{name}_rthigh", (-0.1, 0, z), (0.08, 0.08, 0.18), cloth, "R_Thigh"),
        (f"{name}_rshin", (-0.1, 0, z - 0.37), (0.07, 0.07, 0.16), cloth, "R_Shin"),
        (f"{name}_lfoot", (0.1, 0.04, z - 0.57), (0.08, 0.14, 0.04), shoe, "L_Shin"),
        (f"{name}_rfoot", (-0.1, 0.04, z - 0.57), (0.08, 0.14, 0.04), shoe, "R_Shin"),
        (f"{name}_lbrow", (0.05, -0.16, z + 1.16), (0.045, 0.015, 0.012), ink, "L_Brow"),
        (f"{name}_rbrow", (-0.05, -0.16, z + 1.16), (0.045, 0.015, 0.012), ink, "R_Brow"),
        (f"{name}_mouth", (0, -0.17, z + 0.98), (0.055, 0.02, 0.012), lip, "Mouth"),
    ]
    for mesh_name, loc, scale, mat, bone_name in parts:
        obj = add_cube(mesh_name, loc, scale, mat)
        bind_to_bone(obj, arm, bone_name)

    for mesh_name, loc, radius, mat, bone_name in (
        (f"{name}_leye_w", (0.05, -0.155, z + 1.10), 0.038, white, "L_Eye"),
        (f"{name}_reye_w", (-0.05, -0.155, z + 1.10), 0.038, white, "R_Eye"),
        (f"{name}_leye", (0.05, -0.18, z + 1.10), 0.022, ink, "L_Eye"),
        (f"{name}_reye", (-0.05, -0.18, z + 1.10), 0.022, ink, "R_Eye"),
    ):
        obj = add_sphere(mesh_name, loc, radius, mat)
        bind_to_bone(obj, arm, bone_name)

    bpy.context.view_layer.update()
    return arm


BONE_ALIASES = {
    "Root": ["Root", "ValveBiped.Bip01_Pelvis", "bip_pelvis", "Hips", "mixamorig:Hips", "Pelvis"],
    "Spine": ["Spine", "ValveBiped.Bip01_Spine2", "ValveBiped.Bip01_Spine1", "spine", "mixamorig:Spine"],
    "Head": ["Head", "ValveBiped.Bip01_Head1", "head", "mixamorig:Head"],
    "L_UpperArm": ["L_UpperArm", "ValveBiped.Bip01_L_UpperArm", "mixamorig:LeftArm", "bip_upperArm_L"],
    "L_ForeArm": ["L_ForeArm", "ValveBiped.Bip01_L_Forearm", "mixamorig:LeftForeArm", "bip_lowerArm_L"],
    "R_UpperArm": ["R_UpperArm", "ValveBiped.Bip01_R_UpperArm", "mixamorig:RightArm", "bip_upperArm_R"],
    "R_ForeArm": ["R_ForeArm", "ValveBiped.Bip01_R_Forearm", "mixamorig:RightForeArm", "bip_lowerArm_R"],
    "L_Thigh": ["L_Thigh", "ValveBiped.Bip01_L_Thigh", "mixamorig:LeftUpLeg", "bip_hip_L"],
    "L_Shin": ["L_Shin", "ValveBiped.Bip01_L_Calf", "mixamorig:LeftLeg", "bip_knee_L"],
    "R_Thigh": ["R_Thigh", "ValveBiped.Bip01_R_Thigh", "mixamorig:RightUpLeg", "bip_hip_R"],
    "R_Shin": ["R_Shin", "ValveBiped.Bip01_R_Calf", "mixamorig:RightLeg", "bip_knee_R"],
    "Jaw": ["Jaw", "jaw", "ValveBiped.Bip01_Jaw"],
    "L_Eye": ["L_Eye", "LeftEye", "eye_L"],
    "R_Eye": ["R_Eye", "RightEye", "eye_R"],
    "L_Brow": ["L_Brow", "LeftBrow", "brow_L"],
    "R_Brow": ["R_Brow", "RightBrow", "brow_R"],
    "Mouth": ["Mouth", "mouth"],
}


def is_valvebiped(arm) -> bool:
    """True for Source/ValveBiped rigs, which differ from the built-in block figure."""
    return any(n.startswith("ValveBiped") for n in arm.pose.bones.keys())


def bone_name(arm, logical: str) -> str | None:
    if logical in arm.pose.bones:
        return logical
    names = list(arm.pose.bones.keys())
    for alias in BONE_ALIASES.get(logical, [logical]):
        if alias in arm.pose.bones:
            return alias
        alias_l = alias.lower()
        for n in names:
            if alias_l == n.lower() or n.lower().endswith(alias_l):
                return n
    return None


def is_valve(arm) -> bool:
    return any(n.startswith("ValveBiped") for n in arm.pose.bones.keys())


def remap_euler(arm, logical, euler):
    """Cube-doll hinges sit on local X; ValveBiped bones point along +X, so the same hinge is Z."""
    if not is_valve(arm):
        return euler
    x, y, z = euler
    if logical in {"L_ForeArm", "R_ForeArm", "L_Shin", "R_Shin"}:
        return (z, y, x)
    if logical in {"L_UpperArm", "R_UpperArm", "L_Thigh", "R_Thigh"}:
        return (z, x, y)
    return euler


def set_rot(arm, bone, euler, frame):
    real = bone_name(arm, bone)
    if not real:
        return
    pb = arm.pose.bones[real]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = Euler(remap_euler(arm, bone, euler))
    pb.keyframe_insert(data_path="rotation_euler", frame=frame)


def set_loc(arm, bone, loc, frame):
    real = bone_name(arm, bone)
    if not real:
        return
    pb = arm.pose.bones[real]
    pb.location = loc
    pb.keyframe_insert(data_path="location", frame=frame)


def set_scale(arm, bone, scale, frame):
    real = bone_name(arm, bone)
    if not real:
        return
    pb = arm.pose.bones[real]
    pb.scale = scale
    pb.keyframe_insert(data_path="scale", frame=frame)


def reset_pose(arm, frame):
    for bone in arm.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = Euler((0, 0, 0))
        bone.location = (0, 0, 0)
        bone.scale = (1.0, 1.0, 1.0)
        bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        bone.keyframe_insert(data_path="location", frame=frame)
        bone.keyframe_insert(data_path="scale", frame=frame)


def apply_action(arm, name, start, frames):
    end = start + frames
    reset_pose(arm, start)
    mid = start + frames // 2
    q = frames // 4

    if name == "wave":
        # ValveBiped rigs rest in a T-pose, so the arm has to be raised first; without this
        # only the forearm swings and the character looks like it is twitching.
        raise_arm = -70 if is_valvebiped(arm) else -20
        set_rot(arm, "R_UpperArm", (math.radians(raise_arm), 0, math.radians(-25)), start)
        set_rot(arm, "R_UpperArm", (math.radians(raise_arm), 0, math.radians(-25)), end)
        set_rot(arm, "L_UpperArm", (math.radians(raise_arm), 0, math.radians(25)), start)
        set_rot(arm, "L_UpperArm", (math.radians(raise_arm), 0, math.radians(25)), end)
        set_rot(arm, "R_ForeArm", (math.radians(15), 0, 0), start)
        set_rot(arm, "R_ForeArm", (math.radians(-55), 0, 0), start + q)
        set_rot(arm, "R_ForeArm", (math.radians(55), 0, 0), mid)
        set_rot(arm, "R_ForeArm", (math.radians(-55), 0, 0), start + 3 * q)
        set_rot(arm, "L_ForeArm", (math.radians(15), 0, 0), start)
        set_rot(arm, "L_ForeArm", (math.radians(-55), 0, 0), start + q)
        set_rot(arm, "L_ForeArm", (math.radians(55), 0, 0), mid)
        set_rot(arm, "L_ForeArm", (math.radians(-55), 0, 0), start + 3 * q)
        set_rot(arm, "R_ForeArm", (0, 0, 0), end)
        set_rot(arm, "L_ForeArm", (0, 0, 0), end)
    elif name == "bow":
        set_rot(arm, "Spine", (math.radians(18), 0, 0), start)
        set_rot(arm, "Spine", (math.radians(55), 0, 0), mid)
        set_rot(arm, "Head", (math.radians(10), 0, 0), mid)
        set_rot(arm, "Spine", (0, 0, 0), end)
        set_rot(arm, "Head", (0, 0, 0), end)
    elif name == "nod":
        set_rot(arm, "Head", (math.radians(18), 0, 0), mid)
        set_rot(arm, "Head", (0, 0, 0), end)
    elif name == "shake":
        set_rot(arm, "Head", (0, 0, math.radians(-25)), start + q)
        set_rot(arm, "Head", (0, 0, math.radians(25)), mid)
        set_rot(arm, "Head", (0, 0, 0), end)
    elif name == "sit":
        set_rot(arm, "L_Thigh", (math.radians(-80), 0, 0), mid)
        set_rot(arm, "R_Thigh", (math.radians(-80), 0, 0), mid)
        set_rot(arm, "L_Shin", (math.radians(70), 0, 0), mid)
        set_rot(arm, "R_Shin", (math.radians(70), 0, 0), mid)
        set_loc(arm, "Root", (0, 0, -0.25), mid)
        set_rot(arm, "L_Thigh", (math.radians(-80), 0, 0), end)
        set_rot(arm, "R_Thigh", (math.radians(-80), 0, 0), end)
        set_loc(arm, "Root", (0, 0, -0.25), end)
    elif name == "jump":
        set_loc(arm, "Root", (0, 0, 0), start)
        set_loc(arm, "Root", (0, 0, 0.45), mid)
        set_loc(arm, "Root", (0, 0, 0), end)
        set_rot(arm, "L_Thigh", (math.radians(-30), 0, 0), start + q)
        set_rot(arm, "R_Thigh", (math.radians(-30), 0, 0), start + q)
    elif name == "spin":
        set_rot(arm, "Root", (0, 0, 0), start)
        set_rot(arm, "Root", (0, 0, math.radians(360)), end)
    elif name == "walk":
        set_rot(arm, "L_Thigh", (math.radians(28), 0, 0), start + q)
        set_rot(arm, "R_Thigh", (math.radians(-28), 0, 0), start + q)
        set_rot(arm, "L_Thigh", (math.radians(-28), 0, 0), mid)
        set_rot(arm, "R_Thigh", (math.radians(28), 0, 0), mid)
        set_rot(arm, "L_Thigh", (math.radians(28), 0, 0), start + 3 * q)
        set_rot(arm, "R_Thigh", (math.radians(-28), 0, 0), start + 3 * q)
        set_rot(arm, "L_UpperArm", (0, 0, math.radians(18)), start + q)
        set_rot(arm, "R_UpperArm", (0, 0, math.radians(-18)), start + q)
        reset_pose(arm, end)
    elif name == "clap":
        set_rot(arm, "L_UpperArm", (0, math.radians(-35), math.radians(25)), mid)
        set_rot(arm, "R_UpperArm", (0, math.radians(35), math.radians(-25)), mid)
        set_rot(arm, "L_ForeArm", (math.radians(40), 0, 0), mid)
        set_rot(arm, "R_ForeArm", (math.radians(-40), 0, 0), mid)
        reset_pose(arm, end)
    elif name == "blink":
        set_scale(arm, "L_Eye", (1.0, 1.0, 0.12), mid)
        set_scale(arm, "R_Eye", (1.0, 1.0, 0.12), mid)
        set_scale(arm, "L_Eye", (1.0, 1.0, 1.0), end)
        set_scale(arm, "R_Eye", (1.0, 1.0, 1.0), end)
    elif name == "wink":
        set_scale(arm, "L_Eye", (1.0, 1.0, 0.12), mid)
        set_scale(arm, "L_Eye", (1.0, 1.0, 1.0), end)
    elif name == "smile":
        set_scale(arm, "Mouth", (1.35, 1.0, 0.7), mid)
        set_rot(arm, "L_Brow", (0, 0, math.radians(12)), mid)
        set_rot(arm, "R_Brow", (0, 0, math.radians(-12)), mid)
        reset_pose(arm, end)
    elif name == "talk":
        set_rot(arm, "Jaw", (math.radians(18), 0, 0), start + q)
        set_rot(arm, "Mouth", (math.radians(12), 0, 0), start + q)
        set_scale(arm, "Mouth", (1.1, 1.4, 1.0), start + q)
        set_rot(arm, "Jaw", (0, 0, 0), mid)
        set_rot(arm, "Jaw", (math.radians(16), 0, 0), start + 3 * q)
        reset_pose(arm, end)
    elif name == "angry":
        set_rot(arm, "L_Brow", (0, 0, math.radians(-22)), mid)
        set_rot(arm, "R_Brow", (0, 0, math.radians(22)), mid)
        set_scale(arm, "Mouth", (0.7, 1.0, 1.2), mid)
        reset_pose(arm, end)
    else:
        set_rot(arm, "Spine", (math.radians(4), 0, math.radians(3)), mid)
        reset_pose(arm, end)
    return end


def setup_stage(count: int = 1):
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0.0))
    floor = bpy.context.object
    floor.name = "Floor"
    floor.data.materials.append(make_mat("Floor", (0.86, 0.82, 0.76)))

    bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 3.4, 2.2), rotation=(math.radians(90), 0, 0))
    wall = bpy.context.object
    wall.name = "Backdrop"
    wall.data.materials.append(make_mat("Backdrop", (0.55, 0.62, 0.58)))

    bpy.ops.object.light_add(type="AREA", location=(2.2, -1.8, 4.2))
    key = bpy.context.object
    key.data.energy = 450
    key.data.size = 3

    bpy.ops.object.light_add(type="AREA", location=(-2.4, 1.6, 3.4))
    fill = bpy.context.object
    fill.data.energy = 180
    fill.data.size = 4

    target = Vector((0.0, 0.0, 1.35))
    cam_y = -5.6 - 0.8 * max(0, count - 1)
    bpy.ops.object.camera_add(location=(2.8 + 0.4 * count, cam_y, 2.15))
    cam = bpy.context.object
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam


def import_model(path: Path, name: str = "Actor", offset_x: float = 0.0) -> tuple:
    suffix = path.suffix.lower()
    before = set(bpy.data.objects)
    actions_before = set(bpy.data.actions.keys())
    if suffix == ".blend":
        with bpy.data.libraries.load(str(path), link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise ValueError(f"暂不支持 {suffix}，请先转成 .glb / .fbx / .blend")

    imported = [obj for obj in bpy.data.objects if obj not in before]
    for obj in list(imported):
        if obj.type != "MESH":
            continue
        mats = [slot.material.name if slot.material else "" for slot in obj.material_slots]
        if mats and all(name.startswith("OH_Outline") for name in mats):
            imported.remove(obj)
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [obj for obj in imported if obj.type == "MESH"]
    arms = [obj for obj in imported if obj.type == "ARMATURE"]
    if not imported:
        raise ValueError("模型文件里没有可用物体")

    # GMod PMs ship cloth panels (Sm_PDSkirt_*, physics/flex skirts) whose vertices carry no
    # skin weights. Left unbound they hang in world space and read as a big white sail, so
    # assign each vertex to the nearest cloth/drive bone, falling back to the pelvis. They must
    # stay in `meshes`: the bounding box below is computed from these objects and dropping them
    # distorts the framing.
    armature = next((o for o in imported if o.type == "ARMATURE"), None)
    if armature is not None:
        heads = [(b.name, armature.matrix_world @ b.head_local) for b in armature.data.bones]
        cloth = [(n, p) for n, p in heads if any(k in n.lower() for k in ("skirt", "dress", "cloth"))]
        pelvis = next((n for n, _ in heads if n.endswith("Pelvis") or n == "Root"), None)
        targets = cloth or ([(pelvis, Vector((0.0, 0.0, 0.0)))] if pelvis else [])
        if targets:
            for obj in meshes:
                if obj.vertex_groups:
                    continue
                vgs = {n: obj.vertex_groups.new(name=n) for n, _ in targets}
                for v in obj.data.vertices:
                    wp = obj.matrix_world @ v.co
                    best = min(targets, key=lambda g: (g[1] - wp).length)[0]
                    vgs[best].add([v.index], 1.0, "REPLACE")

    coords = []
    for obj in meshes or imported:
        mw = obj.matrix_world
        for corner in obj.bound_box:
            coords.append(mw @ Vector(corner))
    min_c = Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords)))
    max_c = Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords)))
    size = max_c - min_c
    height = max(size.z, 0.001)
    scale = 1.7 / height if height > 0.01 else 1.0
    center = (min_c + max_c) * 0.5

    roots = [obj for obj in imported if obj.parent is None]
    bpy.ops.object.empty_add(location=(0.0, 0.0, 0.0))
    wrapper = bpy.context.object
    wrapper.empty_display_size = 0.05
    wrapper.name = f"{name}_Root"
    for obj in roots:
        mw = obj.matrix_world.copy()
        obj.parent = wrapper
        obj.matrix_world = mw

    wrapper.location -= center
    wrapper.location.z += size.z * 0.5
    wrapper.scale *= scale
    wrapper.location *= scale
    bpy.context.view_layer.update()
    wrapper.location.x += offset_x

    actor = arms[0] if arms else wrapper
    actor.name = name

    # 收集模型自带动画（glTF/FBX 导入后新增的 actions），然后清掉骨架上的默认绑定：
    # glTF 导入器会把第一个动画挂到 armature 的 animation_data.action / NLA 上，渲染时会
    # 与我们的程序化关键帧叠加打架。自带动画只在指令明确引用时才用（见 apply_model_action）。
    model_actions = [a for a in bpy.data.actions if a.name not in actions_before]
    for obj in imported:
        if obj.type == "ARMATURE" and obj.animation_data:
            if obj.animation_data.action:
                obj.animation_data.action = None
            for track in list(obj.animation_data.nla_tracks):
                obj.animation_data.nla_tracks.remove(track)
    return actor, imported, model_actions


def apply_object_action(obj, name, start, frames):
    end = start + frames
    mid = start + frames // 2
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0, 0, 0)
    obj.location = obj.location.copy()
    obj.keyframe_insert(data_path="rotation_euler", frame=start)
    obj.keyframe_insert(data_path="location", frame=start)
    if name == "spin":
        obj.rotation_euler = (0, 0, math.radians(360))
        obj.keyframe_insert(data_path="rotation_euler", frame=end)
    elif name == "jump":
        base = obj.location.copy()
        obj.location = (base.x, base.y, base.z + 0.45)
        obj.keyframe_insert(data_path="location", frame=mid)
        obj.location = base
        obj.keyframe_insert(data_path="location", frame=end)
    elif name == "bow":
        obj.rotation_euler = (math.radians(35), 0, 0)
        obj.keyframe_insert(data_path="rotation_euler", frame=mid)
        obj.rotation_euler = (0, 0, 0)
        obj.keyframe_insert(data_path="rotation_euler", frame=end)
    else:
        obj.rotation_euler = (math.radians(6), 0, math.radians(8))
        obj.keyframe_insert(data_path="rotation_euler", frame=mid)
        obj.rotation_euler = (0, 0, 0)
        obj.keyframe_insert(data_path="rotation_euler", frame=end)
    return end


# 逻辑动作名 -> 模型自带动画名的关键词（子串匹配，大小写不敏感）
MODEL_ACTION_KEYWORDS = {
    "wave": ("wave", "greet", "hello", "hello_"),
    "walk": ("walk",),
    "idle": ("idle",),
    "spin": ("spin", "turn", "dance"),
    "jump": ("jump",),
    "talk": ("talk", "idle"),  # 这类模型多没有说话动画，退回待机
    "bow": ("bow", "nodge", "thank"),
    "nod": ("nod", "yes"),
    "shake": ("shake", "no"),
    "clap": ("clap",),
    "sit": ("sit",),
    "angry": ("anger", "fight"),
    "smile": ("smile", "happy", "joy"),
}


def match_model_action(model_actions, logical: str):
    """Find a clip shipped with the model matching a logical action, exact name first."""
    keys = MODEL_ACTION_KEYWORDS.get(logical)
    if not keys:
        return None
    # glTF import names actions "ArmatureName|ClipName"; keep the clip part
    names = [(a, a.name.split("|")[-1].lower()) for a in model_actions]
    for key in keys:
        for act, nm in names:  # exact match first
            if nm == key:
                return act
    for key in keys:
        for act, nm in names:  # then substring
            if key in nm:
                return act
    return None


def apply_model_action(actor, act, start, frames):
    """Play a model-authored clip on [start, start+frames] as an NLA strip.

    Using NLA (rather than baking pose keys) means no bone renaming is needed — the clip was
    authored for this exact armature. REPLACE blend + NOT_HOLD extrapolation keeps it from
    leaking outside its own time window, so neighbouring procedural actions are unaffected.
    """
    import_ = actor.animation_data or actor.animation_data_create()
    track = import_.nla_tracks.new()
    strip = track.strips.new(act.name, 1, act)
    strip.action = act
    src = max(1, int(act.frame_range[1] - act.frame_range[0]))
    strip.frame_start = start
    strip.frame_end = start + frames
    strip.scale = frames / src
    strip.blend_type = "REPLACE"
    strip.extrapolation = "NOTHING"
    strip.influence = 1.0
    strip.use_animated_time = False
    return start + frames


# 逻辑表情动作 -> blendshape 名关键词（匹配 mesh 的 shape keys）
EXPRESSION_KEYWORDS = {
    "blink": ("blink", "eyeblink", "eyeclose", "closeeye", "eye_close"),
    "wink": ("wink",),
    "smile": ("smile", "happy", "joy", "laugh"),
    "talk": ("mouthopen", "mouth_open", "mouth", "jawopen", "talk", "aa", "viseme"),
    "angry": ("anger", "browdown", "brow_down", "frown", "angry"),
}


def apply_expression_action(meshes, logical, start, frames):
    """Drive real facial blendshapes for blink/wink/smile/talk/angry, if the model has them.

    Falls back silently when a model ships no such shape key — the block-figure still animates
    the Jaw bone via apply_action, so nothing is lost for low-asset models.
    """
    keys = EXPRESSION_KEYWORDS.get(logical)
    if not keys:
        return
    mid = start + frames // 2
    for obj in meshes:
        sk = obj.data.shape_keys
        if sk is None:
            continue
        hits = [kb for kb in sk.key_blocks if any(k in kb.name.lower() for k in keys)]
        if not hits:
            continue
        # Blender 5.x no longer auto-creates animation_data/action on shape-key keyframe_insert,
        # so the first insert would be dropped silently. Create and bind an action up front.
        if sk.animation_data is None:
            sk.animation_data_create()
        if sk.animation_data.action is None:
            act = bpy.data.actions.new(f"{obj.name}_ShapeKeys")
            sk.animation_data.action = act
            act.use_fake_user = True
        for kb in hits:
            kb.value = 0.0
            kb.keyframe_insert(data_path="value", frame=start)
            kb.value = 1.0
            kb.keyframe_insert(data_path="value", frame=mid)
            kb.value = 0.0
            kb.keyframe_insert(data_path="value", frame=start + frames)


def _action_has_curves(act) -> bool:
    """Blender 4.4+ slotted actions keep fcurves under layers[].strips[].channelbags[].

    Plain `act.fcurves` no longer exists on the Action itself in 5.x, so probe the tree.
    """
    try:
        if act.fcurves:
            return True
    except AttributeError:
        pass
    for layer in getattr(act, "layers", ()) or ():
        for strip in getattr(layer, "strips", ()) or ():
            for bag in getattr(strip, "channelbags", ()) or ():
                if bag.fcurves:
                    return True
                for chan in getattr(bag, "channels", ()) or ():
                    if getattr(chan, "fcurves", None):
                        return True
    return False


def push_active_to_nla(obj):
    """Move an object's active action (procedural keyframes) into an NLA strip.

    Blender 5.x evaluates `animation_data.action` as a base layer on top of the NLA stack; as
    soon as any procedural keyframe lands there (e.g. blink sets eye-scale), the whole NLA
    evaluation collapses and model-authored strips stop animating. So after all actions are
    scheduled, we push the active action into its own strip and clear the slot.
    """
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return
    act = ad.action
    if not _action_has_curves(act):
        ad.action = None
        return
    track = ad.nla_tracks.new()
    strip = track.strips.new(act.name, int(act.frame_range[0]), act)
    strip.action = act
    strip.frame_start = int(act.frame_range[0])
    strip.frame_end = int(act.frame_range[1])
    strip.scale = 1.0
    strip.blend_type = "REPLACE"
    strip.extrapolation = "NOTHING"
    ad.action = None


def configure_render(scene, start, end, video_path: Path):
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"

    scene.frame_start = start
    scene.frame_end = max(start + 1, end)
    scene.render.fps = 24
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(video_path)


CLOTH_COLORS = [
    (0.35, 0.45, 0.78),
    (0.72, 0.38, 0.36),
    (0.38, 0.62, 0.48),
    (0.55, 0.42, 0.72),
]


def uses_armature(actor) -> bool:
    return actor.type == "ARMATURE" and bool(
        bone_name(actor, "Head") or bone_name(actor, "R_UpperArm") or bone_name(actor, "Spine")
    )


def main():
    job_file = job_path()
    job = json.loads(job_file.read_text(encoding="utf-8"))
    out_dir = Path(job["output_dir"])
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        for old in frames_dir.glob("*.png"):
            old.unlink()
    frames_dir.mkdir(parents=True, exist_ok=True)
    blend = out_dir / "stage.blend"

    clear_scene()
    cast = job.get("cast") or [{"model_path": job.get("model_path") or ""}]
    n = max(1, min(6, len(cast)))
    setup_stage(n)
    actors = []
    for i, slot in enumerate(cast[:n]):
        x = (i - (n - 1) / 2) * 1.45
        path = (slot or {}).get("model_path") or ""
        if path:
            actor, imported, model_actions = import_model(Path(path), name=f"Actor{i}", offset_x=x)
            actors.append((actor, uses_armature(actor), model_actions, imported))
        else:
            actor = create_rig(f"Actor{i}", CLOTH_COLORS[i % len(CLOTH_COLORS)])
            actor.location.x = x
            actors.append((actor, True, [], []))

    frame = 1
    timeline = []
    for action in job.get("actions", []):
        repeats = int(action.get("repeats") or 1)
        frames = int(action.get("frames") or 24)
        for _ in range(repeats):
            start = frame
            end = start
            for actor, is_arm, model_actions, imported in actors:
                logical = action["name"]
                used = None
                if is_arm:
                    # Prefer a clip the model itself ships (walk/run/idle/wave...) so it looks
                    # like the authored character; fall back to our procedural bones otherwise.
                    clip = match_model_action(model_actions, logical)
                    if clip is not None:
                        used = f"model:{clip.name}"
                        end = apply_model_action(actor, clip, start, frames)
                    else:
                        end = apply_action(actor, logical, start, frames)
                    if logical in EXPRESSION_KEYWORDS:
                        meshes = [o for o in imported if o.type == "MESH"]
                        apply_expression_action(meshes, logical, start, frames)
                else:
                    end = apply_object_action(actor, logical, start, frames)
            timeline.append({"name": action["name"], "start": start, "end": end, "source": used})
            frame = end + 2

    scene = bpy.context.scene
    for actor, _is_arm, _acts, _imported in actors:
        push_active_to_nla(actor)
    configure_render(scene, 1, frame, frames_dir / "frame_")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.render.render(animation=True)

    result = {
        "ok": True,
        "frames_dir": str(frames_dir),
        "blend": str(blend),
        "frames": frame,
        "timeline": timeline,
        "instruction": job.get("instruction", ""),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
