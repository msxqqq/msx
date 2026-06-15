"""
Maya NURBS Curve -> UE Niagara VectorCurve (Y-up to Z-up, 自动剪贴板)
- 选中一条 3D NURBS 曲线后运行。
- 自动按曲线 CV 数量采样，计算切线（RCIM_Cubic）。
- 坐标自动转换：Maya (X, Y, Z) → UE (X, Z, Y)  (Y-up 转 Z-up)
- 结果直接写入系统剪贴板，在 UE 中右键粘贴即可。
"""

import maya.cmds as cmds
import random
from PySide2 import QtWidgets

# ========== 可调参数 ==========
USE_CV_COUNT = True      # True：采样数 = 曲线 CV 数；False：使用 MANUAL_SAMPLES
MANUAL_SAMPLES = 5       # 手动采样点数（仅 USE_CV_COUNT=False 时生效）
LUT_SIZE = 56            # ShaderLUT 采样数

# ========== 工具函数 ==========
def format_ue_float(value, decimals=6):
    return "{:.{}f}".format(value, decimals)

def get_selected_nurbs_curve():
    """返回选中的唯一一条 nurbsCurve 形状节点"""
    sel = cmds.ls(selection=True)
    if not sel:
        cmds.error("请先选择一条 NURBS 曲线。")
    for obj in sel:
        shapes = cmds.listRelatives(obj, shapes=True, type="nurbsCurve")
        if shapes:
            return shapes[0]
        if cmds.nodeType(obj) == "nurbsCurve":
            return obj
    cmds.error("所选对象不是 NURBS 曲线。")

def maya_to_ue(pos):
    """坐标轴转换：Maya Y-up → UE Z-up。
       这里采用常见映射：X 不变，Y/Z 互换。
       Maya (X, Y, Z) → UE (X, Z, Y)。
       切线向量同理。
    """
    return (pos[0], pos[2], pos[1])

def get_cv_count(curve):
    indices = cmds.getAttr(curve + ".controlPoints", multiIndices=True)
    return len(indices) if indices else 0

def get_param_range(curve):
    return cmds.getAttr(curve + ".minValue"), cmds.getAttr(curve + ".maxValue")

def sample_curve(curve, num_samples):
    """均匀采样，返回 (times, positions, tangents)，均已转换到 UE 坐标系"""
    min_u, max_u = get_param_range(curve)
    du = max_u - min_u
    times = []
    ue_positions = []
    ue_tangents = []

    for i in range(num_samples):
        t_norm = i / (num_samples - 1) if num_samples > 1 else 0.0
        u = min_u + t_norm * du
        pos_maya = cmds.pointOnCurve(curve, parameter=u, position=True)
        tan_maya = cmds.pointOnCurve(curve, parameter=u, tangent=True)
        # 切线 = 方向 * du (归一化时间导数)
        tan_maya_scaled = [comp * du for comp in tan_maya]

        ue_positions.append(maya_to_ue(pos_maya))
        ue_tangents.append(maya_to_ue(tan_maya_scaled))
        times.append(t_norm)

    return times, ue_positions, ue_tangents

def build_cubic_keys(times, values, tangents):
    """构建 RCIM_Cubic 关键帧字符串"""
    keys = []
    for i, (t, v, tan) in enumerate(zip(times, values, tangents)):
        if i == 0 and abs(t) < 1e-7:
            keys.append(
                "(InterpMode=RCIM_Cubic,Value={},ArriveTangent={},LeaveTangent={})".format(
                    format_ue_float(v), format_ue_float(tan), format_ue_float(tan))
            )
        else:
            keys.append(
                "(InterpMode=RCIM_Cubic,Time={},Value={},ArriveTangent={},LeaveTangent={})".format(
                    format_ue_float(t), format_ue_float(v), format_ue_float(tan), format_ue_float(tan))
            )
    return "({})".format(",".join(keys))

def build_shader_lut(curve, lut_size):
    """为单条曲线生成 ShaderLUT 文本（坐标已转换）"""
    min_u, max_u = get_param_range(curve)
    du = max_u - min_u
    x_vals, y_vals, z_vals = [], [], []
    for i in range(lut_size):
        t = i / (lut_size - 1) if lut_size > 1 else 0.0
        u = min_u + t * du
        pos = cmds.pointOnCurve(curve, parameter=u, position=True)
        ue_pos = maya_to_ue(pos)
        x_vals.append(ue_pos[0])
        y_vals.append(ue_pos[1])
        z_vals.append(ue_pos[2])

    lines = []
    for i in range(lut_size):
        lines.append("         ShaderLUT({})={}".format(i * 3,     format_ue_float(x_vals[i])))
        lines.append("         ShaderLUT({})={}".format(i * 3 + 1, format_ue_float(y_vals[i])))
        lines.append("         ShaderLUT({})={}".format(i * 3 + 2, format_ue_float(z_vals[i])))
    return "\n".join(lines)

def assemble_clipboard_text(x_keys, y_keys, z_keys, shader_lut_str, portable_str):
    merge_id = ''.join(random.choice('0123456789ABCDEF') for _ in range(32))
    template = '''Begin Object Class=/Script/NiagaraEditor.NiagaraClipboardContent Name="NiagaraClipboardContent_365" ExportPath="/Script/NiagaraEditor.NiagaraClipboardContent'/Engine/Transient.NiagaraClipboardContent_365'"
   Begin Object Class=/Script/NiagaraEditor.NiagaraClipboardFunctionInput Name="NiagaraClipboardFunctionInput_0" ExportPath="/Script/NiagaraEditor.NiagaraClipboardFunctionInput'/Engine/Transient.NiagaraClipboardContent_365:NiagaraClipboardFunctionInput_0'"
      Begin Object Class=/Script/Niagara.NiagaraDataInterfaceVectorCurve Name="NiagaraDataInterfaceVectorCurve_0" ExportPath="/Script/Niagara.NiagaraDataInterfaceVectorCurve'/Engine/Transient.NiagaraClipboardContent_365:NiagaraClipboardFunctionInput_0.NiagaraDataInterfaceVectorCurve_0'"
      End Object
   End Object
   Begin Object Name="NiagaraClipboardFunctionInput_0" ExportPath="/Script/NiagaraEditor.NiagaraClipboardFunctionInput'/Engine/Transient.NiagaraClipboardContent_365:NiagaraClipboardFunctionInput_0'"
      Begin Object Name="NiagaraDataInterfaceVectorCurve_0" ExportPath="/Script/Niagara.NiagaraDataInterfaceVectorCurve'/Engine/Transient.NiagaraClipboardContent_365:NiagaraClipboardFunctionInput_0.NiagaraDataInterfaceVectorCurve_0'"
         XCurve=(Keys={x})
         YCurve=(Keys={y})
         ZCurve=(Keys={z})
{lut}
         LUTNumSamplesMinusOne=55.000000
         MergeId={merge}
      End Object
      InputName="VectorCurve"
      InputType=(ClassStructOrEnum="/Script/CoreUObject.Class'/Script/Niagara.NiagaraDataInterfaceVectorCurve'",UnderlyingType=1)
      ValueMode=Data
      Data="/Script/Niagara.NiagaraDataInterfaceVectorCurve'NiagaraDataInterfaceVectorCurve_0'"
   End Object
   FunctionInputs(0)="/Script/NiagaraEditor.NiagaraClipboardFunctionInput'NiagaraClipboardFunctionInput_0'"
   PortableValues(0)=(ValueString="{portable}")
End Object'''
    return template.format(x=x_keys, y=y_keys, z=z_keys,
                           lut=shader_lut_str, merge=merge_id,
                           portable=portable_str)

def copy_to_clipboard(text):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    clipboard = app.clipboard()
    clipboard.setText(text)
    print("// 已自动复制到剪贴板，可直接在 UE 中粘贴。")

# ========== 主程序 ==========
def main():
    curve = get_selected_nurbs_curve()

    # 采样点数：默认等于 CV 数量
    num_samples = get_cv_count(curve) if USE_CV_COUNT else MANUAL_SAMPLES
    print("// 采样点数: {}".format(num_samples))

    # 采样并转换坐标系
    times, ue_positions, ue_tangents = sample_curve(curve, num_samples)

    # 分离 X/Y/Z 分量（均为 UE 坐标）
    x_vals = [p[0] for p in ue_positions]
    y_vals = [p[1] for p in ue_positions]
    z_vals = [p[2] for p in ue_positions]
    x_tan  = [t[0] for t in ue_tangents]
    y_tan  = [t[1] for t in ue_tangents]
    z_tan  = [t[2] for t in ue_tangents]

    # 构建关键帧字符串
    x_keys = build_cubic_keys(times, x_vals, x_tan)
    y_keys = build_cubic_keys(times, y_vals, y_tan)
    z_keys = build_cubic_keys(times, z_vals, z_tan)

    # ShaderLUT（自动转换坐标系）
    shader_lut_str = build_shader_lut(curve, LUT_SIZE)

    # PortableValues
    portable_val = "(Curves=((Keys={}),(Keys={}),(Keys={})))".format(x_keys, y_keys, z_keys)

    # 合成最终文本
    final_text = assemble_clipboard_text(x_keys, y_keys, z_keys, shader_lut_str, portable_val)

    print("\n" + "=" * 80)
    print(final_text)
    print("=" * 80)
    copy_to_clipboard(final_text)

if __name__ == "__main__":
    main()
