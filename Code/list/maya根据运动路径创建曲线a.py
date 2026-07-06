# -*- coding: utf-8 -*-
"""
Maya motion path curve generator.

This version uses maya.cmds instead of PyMEL because some Maya 2027/Python
builds can fail during `import pymel.core` with:
AttributeError: module 'logging' has no attribute '_acquireLock'
"""

import traceback
import maya.cmds as cmds


WINDOW_NAME = "motion_path_generator"


def show_dialog(title, message):
    cmds.confirmDialog(title=title, message=message, button=["\u786e\u5b9a"])


def get_frame_range():
    start_time = cmds.intField("start_frame_input", query=True, value=True)
    end_time = cmds.intField("end_frame_input", query=True, value=True)
    if start_time >= end_time:
        raise ValueError("\u8d77\u59cb\u5e27\u5fc5\u987b\u5c0f\u4e8e\u7ed3\u675f\u5e27\u3002")

    return start_time, end_time


def safe_end_progress():
    try:
        cmds.progressWindow(endProgress=True)
    except Exception:
        pass


def get_sample_rate():
    value = cmds.intFieldGrp("sample_rate_input", query=True, value1=True)
    return max(1, int(value))


def generate_motion_path(*_):
    created_curve = None
    anim_locator = None

    try:
        selection = cmds.ls(selection=True, long=True) or []
        if not selection:
            show_dialog("\u9519\u8bef", "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u7269\u4f53\u6216\u9aa8\u9abc\u3002")
            return

        source = selection[0]
        source_short_name = source.split("|")[-1].split(":")[-1]

        start_time, end_time = get_frame_range()

        sample_rate = get_sample_rate()
        smooth_curve = cmds.checkBox("smooth_curve_option", query=True, value=True)
        generate_animation = cmds.checkBox("generate_animation_option", query=True, value=True)

        total_samples = (end_time - start_time + 1) * sample_rate
        positions = []

        cmds.progressWindow(
            title="\u751f\u6210\u8fd0\u52a8\u8def\u5f84",
            progress=0,
            maxValue=100,
            status="\u6b63\u5728\u91c7\u6837\u4f4d\u7f6e...",
            isInterruptable=True,
        )

        sample_index = 0
        cancelled = False

        for frame in range(start_time, end_time + 1):
            for i in range(sample_rate):
                if cmds.progressWindow(query=True, isCancelled=True):
                    cancelled = True
                    break

                subframe = frame + (i / float(sample_rate))
                cmds.currentTime(subframe, edit=True)

                # Querying world-space translation directly works for joints and transforms.
                pos = cmds.xform(source, query=True, worldSpace=True, translation=True)
                positions.append(tuple(pos))

                sample_index += 1
                percent = int(100.0 * sample_index / total_samples)
                cmds.progressWindow(edit=True, progress=max(0, min(100, percent)))

            if cancelled:
                break

        if cancelled:
            safe_end_progress()
            show_dialog("\u53d6\u6d88", "\u64cd\u4f5c\u5df2\u53d6\u6d88\u3002")
            return

        if len(positions) < 2:
            safe_end_progress()
            show_dialog("\u9519\u8bef", "\u81f3\u5c11\u9700\u8981\u4e24\u4e2a\u91c7\u6837\u70b9\u624d\u80fd\u521b\u5efa\u66f2\u7ebf\u3002")
            return

        degree = min(3, len(positions) - 1) if smooth_curve else 1
        curve_name = "{}_motion_path_curve".format(source_short_name)
        created_curve = cmds.curve(point=positions, degree=degree, name=curve_name)

        if generate_animation:
            anim_locator = cmds.spaceLocator(name="{}_anim_locator".format(source_short_name))[0]

            for index, pos in enumerate(positions):
                time_value = start_time + (index / float(sample_rate))
                cmds.currentTime(time_value, edit=True)
                cmds.xform(anim_locator, worldSpace=True, translation=pos)
                cmds.setKeyframe(anim_locator, attribute="translate", time=time_value)

        safe_end_progress()

        if anim_locator:
            cmds.select([created_curve, anim_locator], replace=True)
            message = "\u8fd0\u52a8\u8def\u5f84\u521b\u5efa\u6210\u529f\uff1a\n\u66f2\u7ebf\uff1a{}\n\u5b9a\u4f4d\u5668\uff1a{}".format(
                created_curve, anim_locator
            )
        else:
            cmds.select(created_curve, replace=True)
            message = "\u8fd0\u52a8\u8def\u5f84\u66f2\u7ebf\u521b\u5efa\u6210\u529f\uff1a\n{}".format(created_curve)

        show_dialog("\u6210\u529f", message)

    except Exception as exc:
        safe_end_progress()

        for node in (anim_locator, created_curve):
            try:
                if node and cmds.objExists(node):
                    cmds.delete(node)
            except Exception:
                pass

        show_dialog("\u9519\u8bef", "\u521b\u5efa\u8fd0\u52a8\u8def\u5f84\u65f6\u51fa\u9519\uff1a\n{}".format(exc))
        print("ERROR: {}".format(exc))
        traceback.print_exc()


def create_ui():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME, window=True)

    window = cmds.window(
        WINDOW_NAME,
        title="\u8fd0\u52a8\u8def\u5f84\u751f\u6210\u5668",
        widthHeight=(360, 300),
        sizeable=False,
        menuBar=False,
    )

    cmds.columnLayout(
        adjustableColumn=True,
        rowSpacing=8,
        columnAttach=("both", 10),
        parent=window,
    )

    cmds.text(label="\u8fd0\u52a8\u8def\u5f84\u751f\u6210\u5de5\u5177", align="center", height=28, font="boldLabelFont")
    cmds.text(label="\u9009\u62e9\u6709\u52a8\u753b\u7684\u7269\u4f53\u6216\u9aa8\u9abc\uff0c\u7136\u540e\u751f\u6210\u8fd0\u52a8\u8f68\u8ff9\u3002", align="center")
    cmds.separator(height=8, style="in")

    frame_row = cmds.rowLayout(
        numberOfColumns=5,
        columnWidth5=(58, 70, 58, 70, 84),
        adjustableColumn=5,
    )
    cmds.text(label="\u5f00\u59cb\u5e27\uff1a", align="right", parent=frame_row)
    cmds.intField("start_frame_input", value=1, parent=frame_row)
    cmds.text(label="\u7ed3\u675f\u5e27\uff1a", align="right", parent=frame_row)
    cmds.intField("end_frame_input", value=100, parent=frame_row)
    cmds.button(label="\u751f\u6210", command=generate_motion_path, parent=frame_row)
    cmds.setParent("..")

    cmds.intFieldGrp(
        "sample_rate_input",
        label="\u6bcf\u5e27\u91c7\u6837\uff1a",
        numberOfFields=1,
        value1=3,
        columnWidth2=(100, 80),
    )

    cmds.checkBox("smooth_curve_option", label="\u521b\u5efa\u5e73\u6ed1\u66f2\u7ebf", value=True)
    cmds.checkBox("generate_animation_option", label="\u751f\u6210\u5b9a\u4f4d\u5668\u52a8\u753b", value=True)

    cmds.separator(height=8, style="in")
    cmds.text(label="\u4f7f\u7528\u6b65\u9aa4\uff1a", align="left", font="boldLabelFont")
    cmds.text(label="1. \u9009\u62e9\u8981\u8bfb\u53d6\u8fd0\u52a8\u8f68\u8ff9\u7684\u7269\u4f53\u6216\u9aa8\u9abc\u3002", align="left")
    cmds.text(label="2. \u8bbe\u7f6e\u65f6\u95f4\u8303\u56f4\u548c\u6bcf\u5e27\u91c7\u6837\u6570\u3002", align="left")
    cmds.text(label="3. \u70b9\u51fb\u201c\u751f\u6210\u201d\u3002", align="left")

    cmds.separator(height=8, style="none")
    cmds.button(
        label="\u5173\u95ed",
        height=34,
        command=lambda *_: cmds.deleteUI(WINDOW_NAME, window=True)
        if cmds.window(WINDOW_NAME, exists=True)
        else None,
    )

    cmds.showWindow(window)


if __name__ == "__main__":
    create_ui()
