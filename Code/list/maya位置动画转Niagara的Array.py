# -*- coding: utf-8 -*-
"""
Maya -> Niagara Position Array

功能：
1. 获取选中的独立 Mesh 物件。
2. 按场景 DAG 层级顺序编号，从 index0 开始。
3. 按播放范围逐帧采样世界空间位置。
4. 转换为 Niagara Array 的属性粘贴格式。
5. 自动复制到剪贴板。

Array 排列：
第0帧物件0、第0帧物件1……
第1帧物件0、第1帧物件1……

索引 = 采样帧编号 × 物件数量 + 物件编号
"""

import math
import uuid

import maya.cmds as cmds
import maya.api.OpenMaya as om


# ============================================================
# 可调整设置
# ============================================================

# None：使用 Maya 时间滑条的播放范围。
# 例如设为 1 和 60，会采样 60 帧，包含开始帧与结束帧。
START_FRAME = None
END_FRAME = None

# 1：每帧采样。
# 2：每隔两帧采样一次。
FRAME_STEP = 1.0

# True：重命名为 index0、index1……
# False：保留原名称，只写入 niagaraIndex 编号属性。
RENAME_OBJECTS = True

# "maya_to_unreal"：自动转换坐标轴。
# "raw"：保留 Maya XYZ 坐标。
AXIS_MODE = "maya_to_unreal"

# "transform"：采样物件变换原点。
# "rotate_pivot"：采样世界空间旋转枢轴。
POSITION_SOURCE = "transform"

# Maya 世界空间参考原点，单位厘米。
# 输出位置会先减去这个原点。
ORIGIN_CM = (0.0, 0.0, 0.0)


# ============================================================
# 获取物件并按场景层级顺序排列
# ============================================================

def selected_mesh_paths_in_hierarchy_order():
    selected_paths = set()

    selected_nodes = cmds.ls(
        selection=True,
        long=True,
        objectsOnly=True
    ) or []

    for node in selected_nodes:
        # 选择的是 Mesh Shape 时，转换为它的 Transform。
        if cmds.nodeType(node) == "mesh":
            parents = cmds.listRelatives(
                node,
                parent=True,
                fullPath=True
            ) or []

            node = parents[0] if parents else None

        if not node:
            continue

        if not cmds.objectType(node, isAType="transform"):
            continue

        meshes = cmds.listRelatives(
            node,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
            type="mesh"
        ) or []

        if meshes:
            selected_paths.add(node)

    if not selected_paths:
        raise RuntimeError(
            "请先选择一个或多个独立 Mesh 物件，不要只选择分组。"
        )

    ordered_paths = []

    # 深度优先遍历场景 DAG。
    # 保留同级节点的层级顺序，不使用点击选择顺序或名称排序。
    iterator = om.MItDag(
        om.MItDag.kDepthFirst,
        om.MFn.kTransform
    )

    while not iterator.isDone():
        path = iterator.getPath()
        full_name = path.fullPathName()

        if full_name in selected_paths:
            if path.isInstanced():
                raise RuntimeError(
                    "请选择独立物件，当前选择包含实例：{}".format(
                        full_name
                    )
                )

            ordered_paths.append(path)

        iterator.next()

    if len(ordered_paths) != len(selected_paths):
        raise RuntimeError(
            "有选择项无法在场景 DAG 中唯一定位，请选择物件的 Transform。"
        )

    return ordered_paths


# ============================================================
# 位置采样与坐标转换
# ============================================================

def get_world_position_cm(path, position_source):
    # Maya API 世界矩阵中的平移使用内部厘米单位，
    # 不受场景显示单位为米、厘米或毫米的影响。

    if position_source == "rotate_pivot":
        transform = om.MFnTransform(path)
        position = transform.rotatePivot(om.MSpace.kWorld)

        return (
            position.x,
            position.y,
            position.z
        )

    matrix = path.inclusiveMatrix()

    return (
        matrix[12],
        matrix[13],
        matrix[14]
    )


def convert_position(position, up_axis, axis_mode, origin_cm):
    x = position[0] - origin_cm[0]
    y = position[1] - origin_cm[1]
    z = position[2] - origin_cm[2]

    if axis_mode == "raw":
        return (x, y, z)

    # 常规 Maya FBX -> UE 的轴转换，
    # 对应未启用 Force Front XAxis 的导入设置。
    if up_axis == "y":
        return (x, z, y)

    return (x, -y, z)


# ============================================================
# 生成 Unreal Array 属性文本
# ============================================================

def format_number(value):
    if not math.isfinite(value):
        raise RuntimeError(
            "采样位置包含 NaN 或 Infinity，请检查动画。"
        )

    text = "{:.6f}".format(value)
    text = text.rstrip("0").rstrip(".")

    if text in ("", "-0"):
        return "0"

    return text


def build_array_text(positions):
    elements = []

    for position in positions:
        element = "(X={},Y={},Z={})".format(
            format_number(position[0]),
            format_number(position[1]),
            format_number(position[2])
        )

        elements.append(element)

    return "(" + ",".join(elements) + ")"


# ============================================================
# 剪贴板
# ============================================================

def get_clipboard():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets

    application = QtWidgets.QApplication.instance()

    if application is None:
        raise RuntimeError(
            "自动复制需要在 Maya 图形界面的 Script Editor 中运行。"
        )

    return application.clipboard()


# ============================================================
# 编号与重命名
# ============================================================

def number_objects(paths, rename_objects):
    selected_names = {
        path.fullPathName()
        for path in paths
    }

    target_names = []

    # 先检查锁定状态、已有属性和名称冲突。
    for index, path in enumerate(paths):
        node = path.fullPathName()

        locked = cmds.lockNode(
            node,
            query=True,
            lock=True
        ) or [False]

        if locked[0]:
            raise RuntimeError(
                "物件已锁定，无法编号：{}".format(node)
            )

        attribute = node + ".niagaraIndex"

        if cmds.objExists(attribute):
            attribute_type = cmds.getAttr(
                attribute,
                type=True
            )

            if attribute_type not in ("long", "short", "byte"):
                raise RuntimeError(
                    "已有 niagaraIndex 属性不是整数：{}".format(node)
                )

            attribute_locked = cmds.getAttr(
                attribute,
                lock=True
            )

            connections = cmds.listConnections(
                attribute,
                source=True,
                destination=False
            )

            if attribute_locked or connections:
                raise RuntimeError(
                    "已有 niagaraIndex 属性锁定或有输入连接：{}".format(
                        node
                    )
                )

        leaf_name = node.rsplit("|", 1)[-1]

        if ":" in leaf_name:
            namespace = leaf_name.rsplit(":", 1)[0] + ":"
        else:
            namespace = ""

        target_name = namespace + "index" + str(index)
        parent_path = node.rsplit("|", 1)[0]
        target_path = parent_path + "|" + target_name

        if rename_objects:
            if cmds.objExists(target_path):
                if target_path not in selected_names:
                    raise RuntimeError(
                        "目标名称已被其他同级物件占用：{}".format(
                            target_path
                        )
                    )

        target_names.append(target_name)

    original_names = [
        path.fullPathName()
        for path in paths
    ]

    changed = False

    cmds.undoInfo(
        openChunk=True,
        chunkName="NiagaraArrayNumbering"
    )

    try:
        if rename_objects:
            # 先使用临时名称，避免所选物件之间发生名称冲突。
            token = uuid.uuid4().hex[:12]

            for index, path in enumerate(paths):
                target_name = target_names[index]

                if ":" in target_name:
                    namespace = target_name.rsplit(":", 1)[0] + ":"
                else:
                    namespace = ""

                temporary_name = (
                    ":"
                    + namespace
                    + "__niagara_tmp_{}_{}".format(token, index)
                )

                cmds.rename(
                    path.fullPathName(),
                    temporary_name,
                    ignoreShape=True
                )

                changed = True

            for index, path in enumerate(paths):
                cmds.rename(
                    path.fullPathName(),
                    ":" + target_names[index],
                    ignoreShape=True
                )

        for index, path in enumerate(paths):
            node = path.fullPathName()

            attribute_exists = cmds.attributeQuery(
                "niagaraIndex",
                node=node,
                exists=True
            )

            if not attribute_exists:
                cmds.addAttr(
                    node,
                    longName="niagaraIndex",
                    attributeType="long"
                )

                changed = True

            cmds.setAttr(
                node + ".niagaraIndex",
                index
            )

            changed = True

            cmds.setAttr(
                node + ".niagaraIndex",
                channelBox=True
            )

    except Exception:
        cmds.undoInfo(closeChunk=True)

        if changed and cmds.undoInfo(query=True, state=True):
            cmds.undo()

        raise

    else:
        cmds.undoInfo(closeChunk=True)

    mapping = []

    for index, path in enumerate(paths):
        mapping.append({
            "index": index,
            "original_name": original_names[index],
            "node": path.fullPathName()
        })

    return mapping


# ============================================================
# 主导出函数
# ============================================================

def export_niagara_position_array(
    start=None,
    end=None,
    step=1.0,
    rename_objects=True,
    axis_mode="maya_to_unreal",
    position_source="transform",
    origin_cm=(0.0, 0.0, 0.0)
):
    if axis_mode not in ("maya_to_unreal", "raw"):
        raise ValueError(
            "AXIS_MODE 必须是 maya_to_unreal 或 raw。"
        )

    if position_source not in ("transform", "rotate_pivot"):
        raise ValueError(
            "POSITION_SOURCE 必须是 transform 或 rotate_pivot。"
        )

    if len(origin_cm) != 3:
        raise ValueError(
            "ORIGIN_CM 必须包含三个数值。"
        )

    if not all(math.isfinite(float(value)) for value in origin_cm):
        raise ValueError(
            "ORIGIN_CM 必须包含三个有限数值。"
        )

    if start is None:
        start = cmds.playbackOptions(
            query=True,
            minTime=True
        )

    if end is None:
        end = cmds.playbackOptions(
            query=True,
            maxTime=True
        )

    start = float(start)
    end = float(end)
    step = float(step)

    if not all(math.isfinite(value) for value in (start, end, step)):
        raise ValueError(
            "开始帧、结束帧和采样步长必须是有限数值。"
        )

    if end < start:
        raise ValueError(
            "结束帧不能小于开始帧。"
        )

    if step <= 0:
        raise ValueError(
            "FRAME_STEP 必须大于 0。"
        )

    interval_count = (end - start) / step

    if not math.isclose(
        interval_count,
        round(interval_count),
        rel_tol=1e-9,
        abs_tol=1e-7
    ):
        raise ValueError(
            "帧范围必须能被 FRAME_STEP 整除，"
            "避免最后一段采样间隔不一致。"
        )

    frames = [
        start + index * step
        for index in range(int(round(interval_count)) + 1)
    ]

    paths = selected_mesh_paths_in_hierarchy_order()
    clipboard = get_clipboard()

    up_axis = cmds.upAxis(
        query=True,
        axis=True
    )

    original_time = cmds.currentTime(query=True)
    positions = []

    try:
        # 外层遍历帧，内层遍历按层级编号的物件。
        for frame in frames:
            cmds.currentTime(
                frame,
                update=True
            )

            for path in paths:
                world_position = get_world_position_cm(
                    path,
                    position_source
                )

                converted_position = convert_position(
                    world_position,
                    up_axis,
                    axis_mode,
                    origin_cm
                )

                positions.append(converted_position)

    finally:
        cmds.currentTime(
            original_time,
            update=True
        )

    array_text = build_array_text(positions)

    mapping = number_objects(
        paths,
        rename_objects
    )

    clipboard.setText(array_text)

    seconds_per_frame = om.MTime(
        1.0,
        om.MTime.uiUnit()
    ).asUnits(om.MTime.kSeconds)

    maya_fps = 1.0 / seconds_per_frame
    niagara_frame_rate = maya_fps / step

    print("\n=== Niagara Position Array ===")

    for item in mapping:
        print(
            "index{} : {} -> {}".format(
                item["index"],
                item["original_name"],
                item["node"]
            )
        )

    print(
        "物件数 {} × 帧数 {} = Array 元素 {}".format(
            len(paths),
            len(frames),
            len(positions)
        )
    )

    print(
        "Niagara：Spawn Count = {}，"
        "FrameCount = {}，FrameRate = {:g}".format(
            len(paths),
            len(frames),
            niagara_frame_rate
        )
    )

    print(
        "采样范围：{:g}～{:g}，步长 {:g}；"
        "单位厘米；轴模式 {}".format(
            start,
            end,
            step,
            axis_mode
        )
    )

    print(
        "位置 Array 已复制到剪贴板。"
        "请在 Niagara 的 Position Data 整个数组行上右键 Paste。"
    )

    return {
        "text": array_text,
        "positions": positions,
        "mapping": mapping,
        "object_count": len(paths),
        "frame_count": len(frames),
        "frames": frames,
        "maya_fps": maya_fps,
        "niagara_frame_rate": niagara_frame_rate
    }


# ============================================================
# 运行
# ============================================================

NIAGARA_EXPORT_RESULT = export_niagara_position_array(
    start=START_FRAME,
    end=END_FRAME,
    step=FRAME_STEP,
    rename_objects=RENAME_OBJECTS,
    axis_mode=AXIS_MODE,
    position_source=POSITION_SOURCE,
    origin_cm=ORIGIN_CM
)
