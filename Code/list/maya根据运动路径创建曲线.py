import pymel.core as pm
import math

def ani_cv():
    try:
        # 检查是否选择了物体
        if not pm.selected():
            pm.confirmDialog(title='错误', message='请先选择一个物体！')
            return
        
        # 获取选中物体
        obj_sel_a = pm.selected()[0]
        obj_name = obj_sel_a.name()
        
        # 创建临时定位器并约束
        temp_loc = pm.spaceLocator(n=f"{obj_name}_temp_locator")
        pm.parentConstraint(obj_sel_a, temp_loc)
        
        # 获取时间范围
        time_range = pm.textFieldButtonGrp('time_range_input', q=1, tx=1)
        if '-' not in time_range:
            pm.confirmDialog(title='错误', message='请输入有效的时间范围（例如：0-120）。')
            pm.delete(temp_loc)
            return
        
        # 解析时间范围
        time_parts = time_range.split('-')
        if len(time_parts) != 2 or not all(p.isdigit() for p in time_parts):
            pm.confirmDialog(title='错误', message='时间范围必须为数字（例如：0-120）。')
            pm.delete(temp_loc)
            return
        
        start_time = int(time_parts[0])
        end_time = int(time_parts[1])
        
        # 验证时间范围
        if start_time >= end_time:
            pm.confirmDialog(title='错误', message='起始时间必须小于结束时间。')
            pm.delete(temp_loc)
            return
        
        # 获取采样频率
        sample_rate = pm.intField('sample_rate_input', q=True, value=True)
        if sample_rate < 1:
            sample_rate = 1
        
        # 获取平滑选项
        smooth_curve = pm.checkBox('smooth_curve_option', q=True, value=True)
        
        # 获取是否生成动画选项
        generate_animation = pm.checkBox('generate_animation_option', q=True, value=True)
        
        # 计算总采样点数
        total_frames = end_time - start_time + 1
        total_samples = total_frames * sample_rate
        
        # 创建进度窗口 - 使用百分比模式避免步长问题
        pm.progressWindow(
            title="生成运动路径", 
            progress=0, 
            max=100, 
            status="正在采样位置...",
            isInterruptable=True
        )
        
        # 采样位置数据
        positions = []
        frame_index = 0
        for frame in range(start_time, end_time + 1):
            # 每帧内多次采样
            for i in range(sample_rate):
                # 检查是否取消
                if pm.progressWindow(q=True, isCancelled=True):
                    break
                
                # 计算子帧时间
                subframe = frame + (i / float(sample_rate))
                pm.currentTime(subframe)
                
                # 获取位置
                pos = temp_loc.translate.get()
                positions.append(pos)
                
                # 更新进度 - 使用百分比避免步长问题
                current_sample = frame_index * sample_rate + i + 1
                percent = int(100.0 * current_sample / total_samples)
                # 确保百分比在0-100之间
                percent = max(0, min(100, percent))
                pm.progressWindow(e=True, progress=percent)
            
            # 更新帧索引
            frame_index += 1
            
            # 检查是否取消
            if pm.progressWindow(q=True, isCancelled=True):
                break
        
        # 如果用户取消
        if pm.progressWindow(q=True, isCancelled=True):
            pm.progressWindow(endProgress=True)
            pm.delete(temp_loc)
            pm.confirmDialog(title='取消', message='操作已取消。')
            return
        
        # 确保至少有两个点
        if len(positions) < 2:
            pm.progressWindow(endProgress=True)
            pm.confirmDialog(title='错误', message='至少需要2个采样点才能创建曲线。')
            pm.delete(temp_loc)
            return
        
        # 创建曲线
        curve_name = f"{obj_name}_motion_path_curve"
        degree = 3 if smooth_curve else 1
        motion_curve = pm.curve(p=positions, d=degree, n=curve_name)
        
        # 清理临时对象
        pm.delete(temp_loc)
        
        # 创建动画定位器（如果用户选择生成动画）
        anim_loc = None
        if generate_animation:
            anim_loc = pm.spaceLocator(n=f"{obj_name}_anim_locator")
            
            # 设置关键帧动画
            for i, pos in enumerate(positions):
                # 计算时间点（每个采样点对应一个帧）
                time_val = start_time + (i / float(sample_rate))
                pm.currentTime(time_val)
                
                # 设置定位器位置
                anim_loc.translate.set(pos)
                
                # 设置关键帧
                pm.setKeyframe(anim_loc, attribute='translate')
        
        pm.progressWindow(endProgress=True)
        
        # 选择生成的曲线和定位器（如果有）
        if anim_loc:
            pm.select([motion_curve, anim_loc])
            message = f"运动路径创建成功:\n曲线: {curve_name}\n定位器: {anim_loc.name()}"
        else:
            pm.select(motion_curve)
            message = f"运动路径曲线创建成功:\n{curve_name}"
        
        pm.confirmDialog(title='成功', message=message, button=['确定'])
    
    except Exception as e:
        # 确保清理进度窗口
        pm.progressWindow(endProgress=True)
        
        # 清理临时对象
        temp_objs = ['temp_loc', 'anim_loc', 'motion_curve']
        for obj in temp_objs:
            if obj in locals():
                try:
                    if pm.objExists(locals()[obj]):
                        pm.delete(locals()[obj])
                except:
                    pass
        
        # 显示错误消息
        error_msg = f"创建运动路径时出错: {str(e)}"
        pm.confirmDialog(title='错误', message=error_msg, button=['确定'])
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

def create_ui():
    window_name = "motion_path_generator"
    
    # 删除现有窗口
    if pm.window(window_name, exists=True):
        pm.deleteUI(window_name, window=True)
    
    # 设置窗口背景色
    window_bg = [0.22, 0.22, 0.22]
    section_bg = [0.28, 0.28, 0.28]
    text_color = [0.9, 0.9, 0.9]
    
    # 创建窗口
    window = pm.window(
        window_name, 
        title="运动路径生成器", 
        width=350,
        sizeable=False,
        menuBar=False
    )
    
    # 主布局
    main_layout = pm.columnLayout(
        adjustableColumn=True, 
        rowSpacing=8, 
        bgc=window_bg,
        parent=window
    )
    
    # 标题区域
    title_frame = pm.frameLayout(
        label="", 
        marginWidth=5, 
        marginHeight=5, 
        bgc=section_bg, 
        borderVisible=False, 
        collapsable=False,
        parent=main_layout
    )
    pm.text(label="运动路径生成工具", align="center", height=30, bgc=[0.2, 0.4, 0.6], parent=title_frame)
    pm.separator(height=5, style="none", parent=title_frame)
    pm.text(label="根据物体动画轨迹生成运动路径曲线", align="center", parent=title_frame)
    
    # 主设置区域
    settings_frame = pm.frameLayout(
        label="参数设置", 
        marginWidth=10, 
        marginHeight=5, 
        bgc=section_bg, 
        borderVisible=True,
        parent=main_layout
    )
    pm.text(label="选择物体后设置以下参数：", align="left", parent=settings_frame)
    pm.separator(height=5, style="single", parent=settings_frame)
    
    # 时间范围输入
    pm.textFieldButtonGrp(
        'time_range_input', 
        label='时间范围：', 
        text='1-100', 
        buttonLabel='生成路径',
        buttonCommand=ani_cv,
        columnWidth3=[70, 150, 80],
        bgc=[0.25, 0.25, 0.25],
        annotation="输入动画时间范围，例如: 1-100",
        parent=settings_frame
    )
    
    pm.separator(height=8, style="none", parent=settings_frame)
    
    # 采样率设置
    rate_layout = pm.rowLayout(
        numberOfColumns=3, 
        columnWidth3=[100, 150, 1], 
        adjustableColumn=2,
        parent=settings_frame
    )
    pm.text(label="每帧采样数：", align="right", parent=rate_layout)
    pm.intField(
        'sample_rate_input', 
        minValue=1, 
        maxValue=10, 
        value=3, 
        bgc=[0.25, 0.25, 0.25],
        annotation="数值越高，快速移动物体的路径越平滑",
        parent=rate_layout
    )
    
    pm.separator(height=5, style="none", parent=settings_frame)
    
    # 平滑曲线选项
    pm.checkBox(
        'smooth_curve_option',
        label='创建平滑曲线',
        value=True,
        bgc=[0.25, 0.25, 0.25],
        annotation="创建平滑曲线（3阶）而不是线性路径（1阶）",
        parent=settings_frame
    )
    
    # 生成动画选项 - 新增
    pm.checkBox(
        'generate_animation_option',
        label='生成定位器动画',
        value=True,
        bgc=[0.25, 0.25, 0.25],
        annotation="是否创建带动画的定位器",
        parent=settings_frame
    )
    
    # 信息区域
    info_frame = pm.frameLayout(
        label="使用说明", 
        marginWidth=10, 
        marginHeight=5, 
        bgc=section_bg, 
        borderVisible=True,
        parent=main_layout
    )
    pm.text(label="使用步骤：", align="left", font="boldLabelFont", parent=info_frame)
    pm.text(label="1. 选择要生成运动路径的动画物体", align="left", parent=info_frame)
    pm.text(label="2. 设置动画时间范围（如 1-100）", align="left", parent=info_frame)
    pm.text(label="3. 设置每帧采样数（默认3）", align="left", parent=info_frame)
    pm.text(label="4. 选择是否生成定位器动画", align="left", parent=info_frame)  # 更新步骤
    pm.text(label="5. 点击'生成路径'按钮创建曲线", align="left", parent=info_frame)  # 更新步骤
    pm.separator(height=5, parent=info_frame)
    pm.text(
        label="提示：快速移动的物体需要更高的采样率", 
        align="left", 
        bgc=[0.3, 0.2, 0.2],
        parent=info_frame
    )
    
    # 底部按钮 - 只保留关闭按钮
    button_layout = pm.rowLayout(
        numberOfColumns=1, 
        columnWidth1=350,
        adjustableColumn=1,
        parent=main_layout
    )
    
    # 关闭窗口按钮
    pm.button(
        label="关闭窗口", 
        command=lambda *_: pm.deleteUI(window_name, window=True) if pm.window(window_name, exists=True) else None, 
        bgc=[0.3, 0.3, 0.3], 
        height=40,
        parent=button_layout
    )
    
    # 设置全局文本颜色
    def set_text_color():
        for child in pm.layout(main_layout, q=True, childArray=True) or []:
            if pm.objectTypeUI(child) == "text":
                try:
                    pm.text(child, e=True, fgc=text_color)
                except:
                    pass
    
    # 延迟执行颜色设置，确保所有控件已创建
    pm.evalDeferred(set_text_color)
    
    # 显示窗口
    pm.showWindow(window)

# 启动UI
if __name__ == "__main__":
    try:
        create_ui()
    except Exception as e:
        error_msg = f"初始化UI时出错: {str(e)}"
        pm.confirmDialog(title='错误', message=error_msg, button=['确定'])
        print(error_msg)
