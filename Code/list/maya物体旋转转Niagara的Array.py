# -*- coding: utf-8 -*-
"""在 Maya Script Editor 的 Python 标签中执行整个文件。

所选物件按默认 Outliner 的 DAG 层级顺序编号，实际重命名为
index0、index1……，导出世界空间旋转四元数到 Niagara Quaternion Array。

世界旋转由完整世界矩阵提取，包含父级旋转、rotateAxis 和 jointOrient。
自动查询 Maya 当前上轴，沿用位置脚本保持 X 轴的坐标转换约定：
Y-up：位置 (x,z,y)，四元数 (-qx,-qz,-qy,qw)；
Z-up：位置 (x,-y,z)，四元数 (-qx,qy,-qz,qw)。
输出顺序为 X/Y/Z/W，单位四元数无长度或角度单位；不修改场景上轴。
平移和缩放不写入数组。镜像或退化世界矩阵在改名前报错。
若与位置数组配对，请两次都选择同一批物件，保持 DAG 排列一致。
Outliner 的字母排序、搜索及过滤属于显示设置，不参与 DAG 排序。
仅重命名 transform，不重命名 shape；一次 Undo 可撤销全部改名。
"""

import math
import uuid

import maya.cmds as cmds
import maya.api.OpenMaya as om


def _get_clipboard():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        from PySide2.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("请在 Maya 图形界面中运行，当前没有 Qt 应用。")
    clipboard = app.clipboard()
    if clipboard is None:
        raise RuntimeError("无法获取系统剪贴板。")
    return clipboard


def _node_path(node):
    # 每次重新取路径，避免父物件改名后子物件的旧路径失效。
    return om.MDagPath.getAPathTo(node).fullPathName()


def _selected_in_dag_order():
    selection = om.MGlobal.getActiveSelectionList()
    if selection.length() == 0:
        raise RuntimeError("请先选择要导出的物件。")

    selected = {}
    for i in range(selection.length()):
        try:
            path = selection.getDagPath(i)
        except (RuntimeError, TypeError):
            raise RuntimeError("选择中包含非场景物件，请只选择模型或 transform。")

        # 选择 shape 或组件时，使用其所属 transform；重复选择只导出一次。
        while path.length() and not path.node().hasFn(om.MFn.kTransform):
            path.pop()
        if not path.length():
            raise RuntimeError("无法找到所选物件的 transform。")

        node = path.node()
        if len(om.MDagPath.getAllPathsTo(node)) > 1:
            raise RuntimeError(
                "不支持拥有多个 DAG 路径的实例 transform：{}".format(
                    path.fullPathName()
                )
            )
        node_id = om.MFnDependencyNode(node).uuid().asString()
        selected[node_id] = node

    ordered = []
    seen = set()
    iterator = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kTransform)
    while not iterator.isDone():
        node = iterator.currentItem()
        node_id = om.MFnDependencyNode(node).uuid().asString()
        if node_id in selected and node_id not in seen:
            ordered.append(selected[node_id])
            seen.add(node_id)
        iterator.next()

    if len(ordered) != len(selected):
        raise RuntimeError("部分所选物件未能在 DAG 层级中找到，已停止。")
    return ordered


def _to_unreal_quaternion(quaternion, up_axis):
    # 四元数的向量部分按 det(C) * C 转换，不能只交换 Y/Z。
    x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
    if up_axis == "y":
        values = (-x, -z, -y, w)
    elif up_axis == "z":
        values = (-x, y, -z, w)
    else:
        raise RuntimeError("不支持当前 Maya 上轴设置：{}".format(up_axis))
    if not all(math.isfinite(v) for v in values):
        raise RuntimeError("旋转四元数包含无效数值。")
    length = math.sqrt(sum(v * v for v in values))
    if length <= 1e-12 or not math.isfinite(length):
        raise RuntimeError("无法归一化旋转四元数。")
    values = tuple(v / length for v in values)
    # q 与 -q 表示相同旋转，统一符号便于比较两次导出的结果。
    for component in (values[3], values[0], values[1], values[2]):
        if abs(component) > 1e-12:
            if component < 0.0:
                values = tuple(-v for v in values)
            break
    return values


def _world_unreal_quaternion(node, up_axis):
    matrix = om.MDagPath.getAPathTo(node).inclusiveMatrix()
    determinant = matrix.det4x4()
    if not math.isfinite(determinant) or determinant == 0.0:
        raise RuntimeError("世界矩阵退化或无效，无法提取旋转：{}".format(_node_path(node)))
    if determinant < 0.0:
        raise RuntimeError(
            "物件或父级存在镜像变换，Quaternion Array 无法单独表示反射：{}".format(
                _node_path(node)
            )
        )
    quaternion = om.MTransformationMatrix(matrix).rotation(asQuaternion=True)
    return _to_unreal_quaternion(quaternion, up_axis)


def _number(value):
    # 避免格式化得到 -0.000000。
    return "{:.6f}".format(0.0 if abs(value) < 0.0000005 else value)


def _niagara_text(quaternions):
    values = ",".join(
        "(X={},Y={},Z={},W={})".format(*[_number(v) for v in point])
        for point in quaternions
    )
    header = """Begin Object Class=/Script/NiagaraEditor.NiagaraClipboardContent Name="NiagaraClipboardContent_126" ExportPath="/Script/NiagaraEditor.NiagaraClipboardContent'/Engine/Transient.NiagaraClipboardContent_126'"
"""
    return header + '   PortableValues(0)=(ValueString="(' + values + ')")\nEnd Object\n'


def export_selected_rotations_to_niagara():
    up_axis = cmds.upAxis(query=True, axis=True).lower()
    if up_axis not in ("y", "z"):
        raise RuntimeError("不支持当前 Maya 上轴设置：{}".format(up_axis))
    if not cmds.undoInfo(query=True, state=True):
        raise RuntimeError("请先启用 Maya Undo，以保证重命名操作可以撤销。")

    nodes = _selected_in_dag_order()
    selected_ids = {
        om.MFnDependencyNode(node).uuid().asString() for node in nodes
    }
    clipboard = _get_clipboard()
    old_clipboard_text = clipboard.text()
    records = []

    # 在任何重命名之前检查所有物件、目标名称并取得世界旋转。
    for index, node in enumerate(nodes):
        path = _node_path(node)
        target = "index{}".format(index)
        if cmds.referenceQuery(path, isNodeReferenced=True):
            raise RuntimeError("无法重命名引用物件：{}".format(path))
        if cmds.lockNode(path, query=True, lock=True)[0]:
            raise RuntimeError("物件被锁定，无法重命名：{}".format(path))

        # 保证根命名空间中的 index 名称唯一，不让 Maya 自动添加后缀。
        for existing in cmds.ls(":" + target, long=True) or []:
            existing_id = cmds.ls(existing, uuid=True)[0]
            if existing_id not in selected_ids:
                raise RuntimeError(
                    "目标名称 {} 已被未选中的节点 {} 占用，请先处理该名称。".format(
                        target, existing
                    )
                )

        quaternion = _world_unreal_quaternion(node, up_axis)
        records.append((node, path, target, quaternion))

    text = _niagara_text([record[3] for record in records])
    temporary_prefix = "__niagara_array_" + uuid.uuid4().hex + "_"
    changed = False
    clipboard_attempted = False
    cmds.undoInfo(openChunk=True, chunkName="Niagara Quaternion Array Rename")
    try:
        try:
            # 先使用临时名称，支持选中的物件原本已叫 index0、index1 等。
            for index, record in enumerate(records):
                cmds.rename(
                    _node_path(record[0]),
                    ":" + temporary_prefix + str(index),
                    ignoreShape=True,
                )
                changed = True

            for node, old_path, target, quaternion in records:
                cmds.rename(_node_path(node), ":" + target, ignoreShape=True)
                if om.MFnDependencyNode(node).name() != target:
                    raise RuntimeError("Maya 未能使用准确的目标名称：{}".format(target))

            clipboard_attempted = True
            clipboard.setText(text)
            if clipboard.text() != text:
                raise RuntimeError("剪贴板写入校验失败。")
        finally:
            cmds.undoInfo(closeChunk=True)
    except Exception:
        if changed:
            cmds.undo()
        if clipboard_attempted:
            clipboard.setText(old_clipboard_text)
        raise

    print("\n=== Maya {}-up → Unreal Z-up（世界旋转四元数，X/Y/Z/W） ===".format(up_axis.upper()))
    for node, old_path, target, quaternion in records:
        print("{} <- {} : {}".format(target, old_path, quaternion))
    print("\n=== Niagara 剪贴板文本 ===\n" + text)
    om.MGlobal.displayInfo(
        "已按 DAG 层级顺序导出 {} 个世界旋转四元数并复制到剪贴板。".format(len(records))
    )
    return text


if __name__ == "__main__":
    export_selected_rotations_to_niagara()
