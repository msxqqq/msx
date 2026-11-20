# -*- coding: utf-8 -*-
"""Maya：按场景层级编号，逐帧导出世界旋转，复制 Niagara 四元数 Array。"""

import math
import uuid

import maya.cmds as cmds
import maya.api.OpenMaya as om


# ------------------------- 可调整的设置 -------------------------
START_FRAME = None       # None = 播放范围起点，例如 1
END_FRAME = None         # None = 播放范围终点，例如 60，包含该帧
FRAME_STEP = 1.0         # 每隔多少 Maya 帧采样一次
RENAME_OBJECTS = True    # 重命名为 index0、index1……，保留 namespace
AXIS_MODE = "maya_to_unreal"  # 必须和位置脚本一致；raw = 不转换坐标轴
# ---------------------------------------------------------------


def _selected_mesh_paths_in_hierarchy_order():
    """按 DAG 深度优先、同级节点的存储顺序返回被选中的 Mesh transform。"""
    selected_paths = set()
    for node in cmds.ls(selection=True, long=True, objectsOnly=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
        if not node or not cmds.objectType(node, isAType="transform"):
            continue
        meshes = cmds.listRelatives(
            node, shapes=True, noIntermediate=True, fullPath=True, type="mesh"
        ) or []
        if meshes:
            selected_paths.add(node)

    if not selected_paths:
        raise RuntimeError("请先选择一个或多个独立 Mesh 物件，不要只选择分组。")

    ordered = []
    iterator = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kTransform)
    while not iterator.isDone():
        path = iterator.getPath()
        if path.fullPathName() in selected_paths:
            if path.isInstanced():
                raise RuntimeError("请选择独立物件；当前选择包含实例：" + path.fullPathName())
            ordered.append(path)
        iterator.next()
    if len(ordered) != len(selected_paths):
        raise RuntimeError("有选择项无法在 DAG 中唯一定位，请选择物件的 transform。")
    return ordered


def _world_quaternion(path):
    # 从世界矩阵提取旋转，包含父级旋转及约束的最终结果。
    # rotation 返回四元数，不受物件 Euler Rotate Order 影响。
    transform = om.MTransformationMatrix(path.inclusiveMatrix())
    q = transform.rotation(asQuaternion=True)
    return (q.x, q.y, q.z, q.w)


def _convert_quaternion(quaternion, up_axis, axis_mode):
    x, y, z, w = quaternion
    if axis_mode == "maya_to_unreal":
        # 与位置脚本的轴映射相匹配：
        # Y-up 位置 (X,Z,Y) -> 四元数 (-X,-Z,-Y,W)
        # Z-up 位置 (X,-Y,Z) -> 四元数 (-X,Y,-Z,W)
        # 四元数的 XYZ 不能直接使用位置的轴交换规则。
        if up_axis == "y":
            x, y, z = -x, -z, -y
        else:
            x, y, z = -x, y, -z
    values = (x, y, z, w)
    if not all(math.isfinite(v) for v in values):
        raise RuntimeError("旋转包含 NaN / Infinity，请检查动画。")
    length = math.sqrt(sum(v * v for v in values))
    if length < 1e-12:
        raise RuntimeError("无法提取有效四元数，请检查物件的变换。")
    return tuple(v / length for v in values)


def _array_text(quaternions):
    def number(value):
        result = "{:.9f}".format(value).rstrip("0").rstrip(".")
        return "0" if result in ("", "-0") else result

    elements = [
        "(X={},Y={},Z={},W={})".format(*(number(v) for v in q))
        for q in quaternions
    ]
    return "(" + ",".join(elements) + ")"


def _qt_clipboard():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("自动复制需要在 Maya 图形界面的 Script Editor 中运行。")
    return app.clipboard()


def _number_objects(paths, rename):
    """编号和重命名均由 Maya Undo 支持，路径对象在重命名后仍指向原节点。"""
    selected_nodes = {path.fullPathName() for path in paths}
    targets = []
    for index, path in enumerate(paths):
        node = path.fullPathName()
        if (cmds.lockNode(node, query=True, lock=True) or [False])[0]:
            raise RuntimeError("物件已锁定，无法编号：" + node)
        plug = node + ".niagaraIndex"
        if cmds.objExists(plug):
            if cmds.getAttr(plug, type=True) not in ("long", "short", "byte"):
                raise RuntimeError("已有 niagaraIndex 属性不是整数：" + node)
            if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
                raise RuntimeError("已有 niagaraIndex 属性锁定或有输入连接：" + node)
        leaf = path.partialPathName().rsplit("|", 1)[-1]
        namespace = leaf.rsplit(":", 1)[0] + ":" if ":" in leaf else ""
        target = namespace + "index" + str(index)
        parent = node.rsplit("|", 1)[0]
        sibling_path = parent + "|" + target
        if rename and cmds.objExists(sibling_path) and sibling_path not in selected_nodes:
            raise RuntimeError("目标名称已被其他同级物件占用：" + sibling_path)
        targets.append(target)

    before_names = [path.fullPathName() for path in paths]
    changed = False
    cmds.undoInfo(openChunk=True, chunkName="NiagaraArrayNumbering")
    try:
        if rename:
            # 先用临时名称，支持重复执行及重新排列已有 index 物件。
            token = uuid.uuid4().hex[:12]
            for index, path in enumerate(paths):
                namespace = targets[index].rsplit(":", 1)[0] + ":" if ":" in targets[index] else ""
                cmds.rename(path.fullPathName(), ":" + namespace + "__niagara_tmp_{}_{}".format(token, index), ignoreShape=True)
                changed = True
            for index, path in enumerate(paths):
                cmds.rename(path.fullPathName(), ":" + targets[index], ignoreShape=True)
        for index, path in enumerate(paths):
            node = path.fullPathName()
            if not cmds.attributeQuery("niagaraIndex", node=node, exists=True):
                cmds.addAttr(node, longName="niagaraIndex", attributeType="long")
                changed = True
            cmds.setAttr(node + ".niagaraIndex", index)
            changed = True
            cmds.setAttr(node + ".niagaraIndex", channelBox=True)
    except Exception:
        cmds.undoInfo(closeChunk=True)
        if changed and cmds.undoInfo(query=True, state=True):
            cmds.undo()
        raise
    else:
        cmds.undoInfo(closeChunk=True)
    return [
        {"index": index, "original_name": before_names[index], "node": path.fullPathName()}
        for index, path in enumerate(paths)
    ]


def export_niagara_rotation_array(start=None, end=None, step=1.0,
                                  rename=True, axis_mode="maya_to_unreal",
                                  copy_to_clipboard=True):
    """返回四元数、Array 文本、编号表及帧信息；默认自动复制。"""
    if axis_mode not in ("maya_to_unreal", "raw"):
        raise ValueError("AXIS_MODE 必须是 maya_to_unreal 或 raw。")
    start = float(cmds.playbackOptions(query=True, minTime=True) if start is None else start)
    end = float(cmds.playbackOptions(query=True, maxTime=True) if end is None else end)
    step = float(step)
    if not all(math.isfinite(v) for v in (start, end, step)) or end < start or step <= 0:
        raise ValueError("帧范围必须有限，结束帧不能小于开始帧，步长必须大于 0。")
    span = (end - start) / step
    if not math.isclose(span, round(span), rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("帧范围必须能被 FRAME_STEP 整除。")

    frames = [start + index * step for index in range(int(round(span)) + 1)]
    paths = _selected_mesh_paths_in_hierarchy_order()
    clipboard = _qt_clipboard() if copy_to_clipboard else None
    up_axis = cmds.upAxis(query=True, axis=True)
    previous_time = cmds.currentTime(query=True)
    previous_quaternions = [None] * len(paths)
    quaternions = []

    try:
        # 外层帧，内层物件：ArrayIndex = frameIndex * objectCount + index。
        for frame in frames:
            cmds.currentTime(frame, update=True)
            for index, path in enumerate(paths):
                q = _convert_quaternion(_world_quaternion(path), up_axis, axis_mode)
                previous = previous_quaternions[index]
                # q 和 -q 表示相同朝向；统一相邻帧符号，便于插值。
                if previous is not None and sum(a * b for a, b in zip(previous, q)) < 0:
                    q = tuple(-v for v in q)
                previous_quaternions[index] = q
                quaternions.append(q)
    finally:
        cmds.currentTime(previous_time, update=True)

    text = _array_text(quaternions)
    mapping = _number_objects(paths, rename)
    if clipboard is not None:
        clipboard.setText(text)
    fps = 1.0 / om.MTime(1.0, om.MTime.uiUnit()).asUnits(om.MTime.kSeconds)
    result = {
        "text": text, "quaternions": quaternions, "mapping": mapping,
        "object_count": len(paths), "frame_count": len(frames),
        "frames": frames, "maya_fps": fps, "niagara_frame_rate": fps / step,
    }
    print("\n=== Niagara Quaternion Array ===")
    for item in mapping:
        print("index{} : {} -> {}".format(item["index"], item["original_name"], item["node"]))
    print("物件数 {} × 帧数 {} = Array 元素 {}".format(len(paths), len(frames), len(quaternions)))
    print("Niagara：Spawn Count = {}，FrameCount = {}，FrameRate = {:g}".format(len(paths), len(frames), fps / step))
    print("采样范围：{:g}～{:g}，步长 {:g}；四元数 X,Y,Z,W；轴模式 {}".format(start, end, step, axis_mode))
    if clipboard is not None:
        print("四元数 Array 已复制。到 User.RotationArray 的整个数组数据属性行上右键 Paste。")
    return result


if __name__ == "__main__":
    NIAGARA_ROTATION_EXPORT_RESULT = export_niagara_rotation_array(
        start=START_FRAME, end=END_FRAME, step=FRAME_STEP,
        rename=RENAME_OBJECTS, axis_mode=AXIS_MODE,
    )
