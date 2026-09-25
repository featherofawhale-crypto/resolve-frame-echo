# 抽帧拖影 Frame Echo

免费、开源的 DaVinci Resolve Fusion 效果模板。它把抽帧保持、时间重影、慢快门、定向／放射运动模糊和中心清晰保护放在一个可直接加到视频片段的 Fusion 效果中。

官网宣传页计划发布到：[qhxmp.cc/plugins/frame-echo](https://qhxmp.cc/plugins/frame-echo)。

## 功能

- 抽帧：目标帧率或每 N 帧更新；参数可打关键帧。
- 拖影：重影叠加或慢快门；历史层归一化，避免静止区域累积增亮。
- 模糊：定向或从指定中心向外的放射状运动模糊。
- 清晰保护：椭圆、钢笔、矩形、圆角矩形、菱形、横向／纵向带状。
- 内置变换：位置、缩放、旋转、锚点在历史取帧之前计算，拖影能跟随动画轨迹。
- 性能旁路：未启用内置变换时，图像直接进入抽帧链，不会为每个历史样本重复经过 Transform。

## 安装

1. 下载 `dist/FrameEcho.drfx` 或发布页中的完整 ZIP。
2. 双击 `.drfx`，在 Resolve 的安装对话框中确认；也可手动放入 Resolve 的 Fusion Templates 目录。
3. 重启 Resolve，在 **效果库 → 工具箱 → 效果 → Frame Echo** 中找到“抽帧拖影 Frame Echo”。

模板只使用 Resolve / Fusion 原生节点。把效果加到有实际图像输入的单个片段、Compound Clip 或 Fusion Clip 上；调整片段无法把下方已合成的时间线图像作为 Fusion 输入。

## 性能建议

`重影叠加`比`慢快门`轻。慢快门会运行 Optical Flow 与 Vector Motion Blur；预览压力较大时，先使用 2 层重影并关闭“附加运动模糊”。不需要在效果内做位置、缩放或旋转动画时，保持“启用内置变换”关闭。

## 源码与验证

- `src/`：可编辑 Fusion `.setting`。
- `scripts/build.py`：重新生成 `.setting` 和 `.drfx`。
- `scripts/test_clear_presets.py`、`scripts/test_transform_echo_oracle.py`：结构与采样算法回归。
- `validation/`：封装、性能结构对比和已知边界记录。

在仓库根目录运行以下命令可重建并验证模板：

```bash
python3 scripts/build.py
(cd scripts && python3 check_package.py)
python3 scripts/test_clear_presets.py
python3 scripts/test_transform_echo_oracle.py
```

前三项只使用 Python 标准库；最后一项需要开发依赖：`python3 -m pip install -r requirements-dev.txt`。

发布 ZIP 包含可安装 `.drfx`、可编辑 `.setting`、MIT 许可证和验证记录；完整构建脚本位于仓库根目录。

当前版本：`v0.1.0`。适配目标为 Resolve 19+；macOS 19.1.4.11 已做部分实机验证，Windows 和 Resolve 免费版尚未完整实测。

## 开源协议

本项目采用 [MIT License](LICENSE) 发布。你可以使用、修改和分发源码与模板；请在副本中保留版权与许可声明。
