"""Build a self-contained Fusion GroupOperator and deterministic DRFX archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "抽帧拖影 Frame Echo"
ARCHIVE_PATH = f"Edit/Effects/Frame Echo/{NAME}.setting"

# Sample the preceding output interval. Recompute from the composition's origin,
# never from render-order-dependent state. GetValue reads the actual spline.
# Resolve exposes the visible clip in/out through RenderStart/End. GlobalStart/
# End include source handles and must not be used as the visible clip boundary.
CADENCE = " ".join("""
:local a=math.ceil(comp.RenderStart);
local t=math.max(a,math.floor(time+0.000001));
if self.HoldEnabled<0.5 then return math.min(comp.RenderEnd,t) end;
local r=math.max(0.001,comp:GetPrefs("Comp.FrameFormat.Rate"));
local mode=self.RateMode;
local dep=self.TargetFPS+self.FrameStep;
local phase=0; local held=a;
for f=a,t-1 do
    local rate;
    if mode<0.5 then
        rate=math.min(1,math.max(0.1,self:GetValue("TargetFPS",f))/r);
    else
        rate=1/math.max(1,math.floor(self:GetValue("FrameStep",f)+0.5));
    end;
    local before=math.floor(phase+0.0000001);
    phase=phase+rate;
    if math.floor(phase+0.0000001)>before then held=f+1 end;
end;
return math.min(comp.RenderEnd,held)
""".split())


def time_speed_delay(age):
    """Return a seek-safe TimeSpeed delay expression for a requested age.

    This deliberately does not read a TimeStretcher image output.  Resolve's
    Edit-page renderer can otherwise mix a clip's prior sizing state into a
    historical request when the native position/zoom is animated.
    """
    return " ".join(f"""
:local a=math.ceil(comp.RenderStart);
local t=math.max(a,math.floor(time+0.000001));
local held=t;
if FE_Hold.HoldEnabled>=0.5 then
    local r=math.max(0.001,comp:GetPrefs("Comp.FrameFormat.Rate"));
    local mode=FE_Hold.RateMode;
    local dep=FE_Hold.TargetFPS+FE_Hold.FrameStep;
    local phase=0;
    for f=a,t-1 do
        local rate;
        if mode<0.5 then
            rate=math.min(1,math.max(0.1,FE_Hold:GetValue("TargetFPS",f))/r);
        else
            rate=1/math.max(1,math.floor(FE_Hold:GetValue("FrameStep",f)+0.5));
        end;
        local before=math.floor(phase+0.0000001);
        phase=phase+rate;
        if math.floor(phase+0.0000001)>before then held=f+1 end;
    end;
end;
local sample=math.max(comp.RenderStart,math.min(comp.RenderEnd,held)-({age}));
if t==a+1 and held==a then return 1 end;
return time-sample
""".split())


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def value(v):
    if isinstance(v, str):
        return f"Input {{ Value = {quote(v)}, }}"
    return f"Input {{ Value = {v}, }}"


def expression(v):
    return f"Input {{ Expression = {quote(v)}, }}"


def wire(op, port="Output"):
    return f"Input {{ SourceOp = {quote(op)}, Source = {quote(port)}, }}"


CONTROLS = [
    ("RateMode", "抽帧模式", 0, 0, 1, ["目标帧率", "每 N 帧更新"]),
    ("TargetFPS", "目标帧率 (fps)", 12, 0.1, 120, None),
    ("FrameStep", "帧间隔 N", 2, 1, 120, None),
    ("TrailMode", "拖影模式", 0, 0, 1, ["重影叠加", "慢快门"]),
    ("Strength", "效果总强度 (%)", 50, 0, 100, None),
    ("TrailLength", "重影长度 (帧)", 6, 0, 48, None),
    ("LayerChoice", "重影层数 (含当前帧)", 1, 0, 2, ["2 层", "4 层", "8 层"]),
    ("ShutterLength", "慢快门长度", 2, 0, 10, None),
    ("MotionMode", "附加运动模糊", 1, 0, 2, ["关闭", "定向", "放射（中心向外）"]),
    ("MotionLength", "运动模糊长度 (%)", 1.5, 0, 20, None),
    ("MotionAngle", "定向模糊角度", 0, -180, 180, None),
    ("ClearRadius", "中心清晰区半径 (%)", 16, 0, 100, None),
    ("ClearFeather", "清晰区柔边 (%)", 6, 0, 50, None),
    ("HoldEnabled", "启用抽帧", 1, 0, 1, None),
    ("TrailEnabled", "启用拖影", 1, 0, 1, None),
    ("ClearEnabled", "启用中心保护", 1, 0, 1, None),
    ("MotionEnabled", "启用运动模糊", 1, 0, 1, None),
    # Keep ellipse=0 and pen=1 stable for previously saved instances.
    ("ClearShape", "清晰区形状", 0, 0, 6,
     ["椭圆", "自定义钢笔", "矩形", "圆角矩形", "菱形", "横向带状", "纵向带状"]),
    # Append new controls only: saved Input1…20 mappings must remain stable.
    ("TransformEnabled", "启用内置变换", 0, 0, 1, None),
]

# Public group input IDs are part of the saved effect contract.  The original
# 14 values were followed by the promoted center (14), four later switches and
# the pen path (20); keep that numbering even though the Inspector now uses
# native GroupOperator UserControls for deterministic nesting.
CONTROL_IDS = {
    key: (index if index < 14 else index + 1)
    for index, (key, *_rest) in enumerate(CONTROLS, 1)
}
# Input20 was reserved for the native Polyline path before the transform was
# added, so the appended transform switch is Input21 rather than Input20.
CONTROL_IDS["TransformEnabled"] = 21


def group_user_controls():
    """Return the outer Inspector layout, including one real transform nest.

    Resolve renders GroupOperator UserControls before InstanceInputs.  An
    InstanceInput therefore cannot be placed inside a LabelControl nest.  The
    numeric controls are bridged through group inputs, leaving the native
    Polyline InstanceInput outside this layout.
    """
    by_id = {CONTROL_IDS[key]: (key, label, default, low, high, choices)
             for key, label, default, low, high, choices in CONTROLS}
    ordered_ids = [5, 15, 1, 2, 3, 16, 4, 6, 7, 8, 18, 9, 10, 11,
                   17, 19, 12, 13, 14, 22, 21, 23, 24, 25, 26]
    controls = []
    for input_id in ordered_ids:
        if input_id == 22:
            controls.append(
                'Input22 = { INP_External = false, LINKID_DataType = "Number", '
                'LBLC_DropDownButton = true, INPID_InputControl = "LabelControl", '
                'LBLC_NumInputs = 5, INP_Passive = true, '
                'ICS_ControlPage = "Controls", LINKS_Name = "内置变换", }')
            continue
        if input_id == 14:
            controls.append(
                'Input14 = { LINKID_DataType = "Point", '
                'INPID_InputControl = "OffsetControl", INP_DefaultX = 0.5, INP_DefaultY = 0.5, '
                'ICS_ControlPage = "Controls", LINKS_Name = "清晰区 / 放射中心", }')
            continue
        if input_id in (23, 26):
            label = "位置" if input_id == 23 else "锚点"
            controls.append(
                f'Input{input_id} = {{ LINKID_DataType = "Point", '
                f'INPID_InputControl = "OffsetControl", INP_DefaultX = 0.5, INP_DefaultY = 0.5, '
                f'ICS_ControlPage = "Controls", LINKS_Name = {quote(label)}, }}')
            continue
        if input_id == 24:
            controls.append(
                'Input24 = { LINKID_DataType = "Number", '
                'INPID_InputControl = "SliderControl", INP_Default = 1, INP_MinAllowed = 0, '
                'INP_MaxAllowed = 5, INP_MinScale = 0, INP_MaxScale = 5, '
                'ICS_ControlPage = "Controls", LINKS_Name = "缩放", }')
            continue
        if input_id == 25:
            controls.append(
                'Input25 = { LINKID_DataType = "Number", '
                'INPID_InputControl = "ScrewControl", INP_Default = 0, INP_MinAllowed = -360, '
                'INP_MaxAllowed = 360, INP_MinScale = -360, INP_MaxScale = 360, '
                'ICS_ControlPage = "Controls", LINKS_Name = "旋转", }')
            continue
        key, label, default, low, high, choices = by_id[input_id]
        widget = "CheckboxControl" if key.endswith("Enabled") else "ComboControl" if choices else "SliderControl"
        attrs = [
            'LINKID_DataType = "Number"',
            f'INPID_InputControl = "{widget}"', f"INP_Default = {default}",
            f"INP_MinAllowed = {low}", f"INP_MaxAllowed = {high}",
            f"INP_MinScale = {low}", f"INP_MaxScale = {high}",
            'ICS_ControlPage = "Controls"', f"LINKS_Name = {quote(label)}",
        ]
        if choices or key == "FrameStep":
            attrs.append("INP_Integer = true")
        if key.endswith("Enabled"):
            attrs.extend(["INP_Integer = true", "INP_Passive = true", "CBC_TriState = false"])
        if choices:
            attrs.append("INP_Passive = true")
            attrs.extend(f"{{ CCS_AddString = {quote(choice)} }}" for choice in choices)
        controls.append(f"Input{input_id} = {{ {', '.join(attrs)}, }}")
    return "UserControls = ordered() {\n" + ",\n".join(controls) + ",\n}"


def controls():
    entries = []
    for key, label, default, low, high, choices in CONTROLS:
        toggle = key.endswith("Enabled")
        widget = "CheckboxControl" if toggle else "ComboControl" if choices else "SliderControl"
        attrs = [
            f"LINKS_Name = {quote(label)}",
            'LINKID_DataType = "Number"',
            'ICS_ControlPage = "Controls"',
            f'INPID_InputControl = "{widget}"',
            f"INP_Default = {default}",
            f"INP_MinAllowed = {low}", f"INP_MaxAllowed = {high}",
            f"INP_MinScale = {low}", f"INP_MaxScale = {high}",
        ]
        if choices or key == "FrameStep":
            attrs.append("INP_Integer = true")
        if toggle:
            attrs.extend(["INP_Integer = true", "INP_Passive = true", "CBC_TriState = false"])
        if choices:
            attrs.append("INP_Passive = true")
            attrs.extend(f"{{ CCS_AddString = {quote(s)} }}" for s in choices)
        entries.append(f"{key} = {{ {', '.join(attrs)}, }}")
    return "UserControls = ordered() {\n" + ",\n".join(entries) + ",\n}"


def node(name, kind, inputs, x=0, y=0, extra=""):
    fields = ",\n".join(f"{key} = {val}" for key, val in inputs.items())
    body = f"{fields},\n" if fields else ""
    return (f"{name} = {kind} {{\nInputs = {{\n{body}}},\n"
            f"ViewInfo = OperatorInfo {{ Pos = {{ {x}, {y} }} }},\n{extra}\n}}")


def setting(time_engine="timestretcher"):
    """Build the template graph.

    ``timespeed`` keeps TimeStretcher only as the numeric cadence controller.
    Its image output is never evaluated; the actual historical image requests
    use native TimeSpeed.  This is kept as an opt-in builder mode until it has
    passed the real Edit-page delivery regression.
    """
    if time_engine not in {"timestretcher", "timespeed", "timespeed-direct"}:
        raise ValueError(time_engine)
    nodes = [node("FE_Input", "PipeRouter", {}, 0, 0)]
    # The Edit page's native Transform is composited after a Fusion Effect, so
    # historical image requests cannot see its previous keyframes. This native
    # Transform is deliberately upstream of every TimeStretcher instead.
    nodes.append(node("FE_Transform", "Transform", {
        "Input": wire("FE_Input"),
        # These are Fusion Transform's native normalized coordinates.  A
        # center/pivot of (0.5, 0.5) is an identity transform at Size=1.
        "Center": expression("FrameEcho.Input23"),
        "Pivot": expression("FrameEcho.Input26"),
        "Size": expression("FrameEcho.Input24"),
        "Angle": expression("FrameEcho.Input25"),
        "Edges": value(0),
        "Blend": value(1),
    }, 100, -80))
    # Do not merely set Transform.Blend to zero when the internal transform is
    # disabled: the node can still resample every temporal request.  Selecting
    # the original image here keeps the default path equal to the first release
    # and leaves Transform out of the requested branch until it is enabled.
    nodes.append(node("FE_TransformBypass", "Dissolve", {
        "Background": wire("FE_Input"),
        "Foreground": wire("FE_Transform"),
        "Mix": expression("iif(FE_Hold.TransformEnabled>0.5,1,0)"),
    }, 160, -80))
    inputs = ({
        "Input": wire("FE_Input"),
        "SourceTime": expression(CADENCE),
        "InterpolateBetweenFrames": value(0),
    } if time_engine != "timespeed-direct" else {})
    inputs.update({key: expression(f"FrameEcho.Input{CONTROL_IDS[key]}")
                   for key, *_ in CONTROLS})
    nodes.append(node("FE_Hold", "TimeStretcher" if time_engine != "timespeed-direct" else "PipeRouter",
                      inputs, 220, 0, controls() + ","))
    layers = "(2^(math.floor(FE_Hold.LayerChoice+0.5)+1))"
    if time_engine == "timestretcher":
        nodes.insert(2, node("FE_Bounds", "TimeStretcher", {
            "Input": wire("FE_TransformBypass"),
            "SourceTime": expression("math.min(comp.RenderEnd,math.max(comp.RenderStart,time))"),
            "InterpolateBetweenFrames": value(0),
        }, 110, 0))
        # Preserve the shipped graph byte-for-byte aside from this function
        # wrapper while the alternate engine remains under QA.
        hold = nodes[-1]
        nodes[-1] = hold.replace('SourceOp = "FE_Input"', 'SourceOp = "FE_Bounds"', 1)
        hold_image = "FE_Hold"
        previous = hold_image
        history_input = "FE_Bounds"
    elif time_engine == "timespeed":
        nodes.append(node("FE_HoldImage", "TimeSpeed", {
            "Input": wire("FE_Input"), "Speed": value(1),
            "Delay": expression("time-FE_Hold.SourceTime"),
            "InterpolateBetweenFrames": value(0),
        }, 220, 0))
        hold_image = "FE_HoldImage"
        previous = hold_image
        history_input = "FE_Input"
    else:
        nodes.append(node("FE_HoldImage", "TimeSpeed", {
            "Input": wire("FE_Input"), "Speed": value(1),
            "Delay": expression(time_speed_delay("0")),
            "InterpolateBetweenFrames": value(0),
        }, 220, 0))
        hold_image = "FE_HoldImage"
        previous = hold_image
        history_input = "FE_Input"
    for i in range(1, 8):
        tap = f"FE_Echo{i}"
        age = f"math.floor(math.max(0,FE_Hold.TrailLength)*{i}/({layers}-1)+0.5)"
        if time_engine == "timestretcher":
            nodes.append(node(tap, "TimeStretcher", {
                "Input": wire(history_input),
                "SourceTime": expression(f"math.max(comp.RenderStart,FE_Hold.SourceTime-{age})"),
                "InterpolateBetweenFrames": value(0),
            }, 220, i*40))
        elif time_engine == "timespeed":
            nodes.append(node(tap, "TimeSpeed", {
                "Input": wire(history_input), "Speed": value(1),
                "Delay": expression(f"time-math.max(comp.RenderStart,FE_Hold.SourceTime-{age})"),
                "InterpolateBetweenFrames": value(0),
            }, 220, i*40))
        else:
            nodes.append(node(tap, "TimeSpeed", {
                "Input": wire(history_input), "Speed": value(1),
                "Delay": expression(time_speed_delay(age)),
                "InterpolateBetweenFrames": value(0),
            }, 220, i*40))
        weight = 0.65**i / sum(0.65**j for j in range(i+1))
        mix = f"iif({layers}>{i},{weight:.17g},0)"
        blend = f"FE_Accumulate{i}"
        nodes.append(node(blend, "Dissolve", {
            "Background": wire(previous), "Foreground": wire(tap),
            "Mix": expression(mix),
        }, 440, i*40))
        previous = blend
    nodes.append(node("FE_Flow", "Dimension.OpticalFlow", {
        "Input": wire(history_input), "Method": 'Input { Value = FuID { "Method2" }, }',
    }, 220, -100))
    nodes.append(node("FE_Blur", "VectorMotionBlur", {
        "Input": wire("FE_Flow"), "Vectors": wire("FE_Flow"),
        "XVectorChannel": value(3), "YChannel": value(4),
        "LockScaleXY": value(1),
        "XScale": expression("math.max(0,FE_Hold.ShutterLength)"),
    }, 330, -100))
    if time_engine == "timestretcher":
        nodes.append(node("FE_BlurHold", "TimeStretcher", {
            "Input": wire("FE_Blur"), "SourceTime": expression("FE_Hold.SourceTime"),
            "InterpolateBetweenFrames": value(0),
        }, 440, -100))
    elif time_engine == "timespeed":
        nodes.append(node("FE_BlurHold", "TimeSpeed", {
            "Input": wire("FE_Blur"), "Speed": value(1),
            "Delay": expression("time-FE_Hold.SourceTime"),
            "InterpolateBetweenFrames": value(0),
        }, 440, -100))
    else:
        nodes.append(node("FE_BlurHold", "TimeSpeed", {
            "Input": wire("FE_Blur"), "Speed": value(1),
            "Delay": expression(time_speed_delay("0")),
            "InterpolateBetweenFrames": value(0),
        }, 440, -100))
    nodes.append(node("FE_Select", "Dissolve", {
        "Background": wire(previous), "Foreground": wire("FE_BlurHold"),
        "Mix": expression("iif(FE_Hold.TrailMode<0.5,0,1)"),
    }, 550, 0))
    nodes.append(node("FE_Trail", "Dissolve", {
        "Background": wire(hold_image), "Foreground": wire("FE_Select"),
        "Mix": expression("iif(FE_Hold.TrailEnabled>0.5,1,0)"),
    }, 605, 0))
    # The mask protects the held clean image, including against temporal ghosts.
    # Center is promoted from a native Point control, so it remains draggable.
    shorter = 'math.min(comp:GetPrefs("Comp.FrameFormat.Width"),comp:GetPrefs("Comp.FrameFormat.Height"))'
    nodes.append(node("FE_Clear", "EllipseMask", {
        "UseFrameFormatSettings": value(1),
        "Center": expression("FrameEcho.Input14"),
        "Width": expression(f'2*FE_Hold.ClearRadius/100*{shorter}/comp:GetPrefs("Comp.FrameFormat.Width")'),
        "Height": expression(f'2*FE_Hold.ClearRadius/100*{shorter}/comp:GetPrefs("Comp.FrameFormat.Height")'),
        "SoftEdge": expression(f'FE_Hold.ClearFeather/100*{shorter}/comp:GetPrefs("Comp.FrameFormat.Width")'),
        "Level": expression("iif(FE_Hold.ClearEnabled>0.5 and FE_Hold.ClearShape<0.5 and FE_Hold.ClearRadius>0,1,0)"),
        "Filter": 'Input { Value = FuID { "Bartlett" }, }',
        "Invert": value(0),
    }, 660, 100))
    nodes.append(node("FE_Motion", "DirectionalBlur", {
        "Input": wire("FE_Trail"),
        # Native Type: 0=Linear, 1=Radial, 2=Centered, 3=Zoom.
        # Zoom is the outward streak requested here, with no angular spin.
        "Type": expression("iif(FE_Hold.MotionMode>1.5,3,0)"),
        "Center": expression("FE_Clear.Center"),
        "Length": expression("iif(FE_Hold.MotionEnabled<0.5 or FE_Hold.MotionMode<0.5,0,FE_Hold.MotionLength/100)"),
        "Angle": expression("iif(FE_Hold.MotionMode>1.5,0,FE_Hold.MotionAngle)"),
        "Glow": value(0),
        "CorrectEdges": value(1),
        "ClippingMode": 'Input { Value = FuID { "Frame" }, }',
    }, 660, 0))
    nodes.append(node("FE_Output", "Dissolve", {
        "Background": wire(hold_image), "Foreground": wire("FE_Motion"),
        "Mix": expression("math.max(0,math.min(1,FE_Hold.Strength/100))"),
        "EffectMask": wire("FE_Clear","Mask"),
        "ApplyMaskInverted": value(1),
    }, 770, 0))
    # Publish the native Polyline preview control; the shape and its animation
    # are embedded in the composition. An empty path protects nothing until
    # the user closes a shape. Ellipse radius/center do not move a drawn path.
    nodes.append(node("FE_Pen", "PolylineMask", {
        "UseFrameFormatSettings": value(1),
        "Filter": 'Input { Value = FuID { "Bartlett" }, }',
        "SoftEdge": expression(f'FE_Hold.ClearFeather/100*{shorter}/comp:GetPrefs("Comp.FrameFormat.Width")'),
        "Level": expression("iif(FE_Hold.ClearEnabled>0.5 and FE_Hold.ClearShape>0.5 and FE_Hold.ClearShape<1.5,1,0)"),
        "Solid": value(1),
        "Polyline": wire("FE_PenPath", "Value"),
        "Polyline2": 'Input { Value = Polyline { }, Disabled = true, }',
    }, 770, 100, 'DrawMode = "ClickAppend", DrawMode2 = "InsertAndModify",'))
    nodes.append('FE_PenPath = BezierSpline {\n'
                 'SplineColor = { Red = 237, Green = 68, Blue = 68 },\n'
                 'CtrlWZoom = false,\n'
                 'KeyFrames = { [0] = { 0, Flags = { Linear = true, LockedY = true }, Value = Polyline { } } },\n}')
    nodes.append(node("FE_PenOutput", "Dissolve", {
        "Background": wire("FE_Output"), "Foreground": wire(hold_image),
        "Mix": value(1), "EffectMask": wire("FE_Pen", "Mask"),
    }, 880, 0))
    # RectangleMask provides native corners and aspect-correct rotation. All
    # presets share one mask; no external images or generated path scripts.
    # Width/Height describe physical size relative to the frame's shorter side.
    # A square rotated 45 degrees has a diagonal sqrt(2) times its side.
    diameter = f'2*math.max(0,FE_Hold.ClearRadius)/100*{shorter}'
    nodes.append(node("FE_Preset", "RectangleMask", {
        "UseFrameFormatSettings": value(1),
        "Center": expression("FE_Clear.Center"),
        "Width": expression(f'iif(FE_Hold.ClearShape==5,3,{diameter}/comp:GetPrefs("Comp.FrameFormat.Width")*iif(FE_Hold.ClearShape==4,1/math.sqrt(2),iif(FE_Hold.ClearShape==6,1,1.5)))'),
        "Height": expression(f'iif(FE_Hold.ClearShape==6,3,{diameter}/comp:GetPrefs("Comp.FrameFormat.Height")*iif(FE_Hold.ClearShape==4,1/math.sqrt(2),1))'),
        "CornerRadius": expression("iif(FE_Hold.ClearShape==3,0.35,0)"),
        "Angle": expression("iif(FE_Hold.ClearShape==4,45,0)"),
        "SoftEdge": expression(f'FE_Hold.ClearFeather/100*{shorter}/comp:GetPrefs("Comp.FrameFormat.Width")'),
        "Level": expression("iif(FE_Hold.ClearEnabled>0.5 and FE_Hold.ClearShape>1.5 and FE_Hold.ClearShape<6.5 and FE_Hold.ClearRadius>0,1,0)"),
        "Filter": 'Input { Value = FuID { "Bartlett" }, }',
        "Solid": value(1),
        "Invert": value(0),
        "ClippingMode": 'Input { Value = FuID { "None" }, }',
    }, 990, 100))
    nodes.append(node("FE_PresetOutput", "Dissolve", {
        "Background": wire("FE_PenOutput"), "Foreground": wire(hold_image),
        "Mix": value(1), "EffectMask": wire("FE_Preset", "Mask"),
    }, 990, 0))
    published = ['MainInput1 = InstanceInput { SourceOp = "FE_Input", Source = "Input", }']
    # These native group inputs are styled and ordered by group_user_controls.
    # Each numeric value is bridged into the internal graph by an expression,
    # allowing the Inspector's LabelControl to nest the enable switch and four
    # transform values.
    for key, _label, default, _low, _high, _choices in CONTROLS:
        published.append(f'Input{CONTROL_IDS[key]} = Input {{ Value = {default}, }}')
    published.extend([
        'Input14 = Input { Value = { 0.5, 0.5 }, }',
        'Input22 = Input { Value = 0, }',
        'Input23 = Input { Value = { 0.5, 0.5 }, }',
        'Input24 = Input { Value = 1, }',
        'Input25 = Input { Value = 0, }',
        'Input26 = Input { Value = { 0.5, 0.5 }, }',
        'Input20 = InstanceInput { SourceOp = "FE_Pen", Source = "Polyline", Name = "钢笔路径", Page = "Controls", }',
    ])
    result = ("{\nTools = ordered() {\nFrameEcho = GroupOperator {\n"
            "CtrlWZoom = false,\nInputs = ordered() {\n" + ",\n".join(published) + ",\n},\n"
            'Outputs = { MainOutput1 = InstanceOutput { SourceOp = "FE_PresetOutput", Source = "Output", }, },\n'
            + group_user_controls() + ',\n'
            'ViewInfo = GroupInfo { Pos = { 0, 0 } },\nTools = ordered() {\n'
            + ",\n".join(nodes) + '\n},\n},\n},\nActiveTool = "FrameEcho",\n}\n')
    if time_engine == "timespeed-direct":
        # FE_Hold becomes a numeric controller only; the replacement avoids
        # accidental evaluation of a TimeStretcher image output anywhere in
        # the group, including published controls and expressions.
        result = result.replace("FE_Hold", "FE_Control")
    return result


def main():
    text = setting()
    src = ROOT / "src" / f"{NAME}.setting"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(text, encoding="utf-8")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / "FrameEcho.drfx"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        entry = zipfile.ZipInfo(ARCHIVE_PATH, date_time=(2026, 9, 23, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        z.writestr(entry, text.encode("utf-8"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built {src.name}: {len(text.encode('utf-8'))} bytes; {archive.name}: {archive.stat().st_size} bytes")


if __name__ == "__main__":
    main()
