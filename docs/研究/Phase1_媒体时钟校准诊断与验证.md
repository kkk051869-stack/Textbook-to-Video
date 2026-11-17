# Phase 1 媒体时钟校准诊断与验证

本轮取得了通过现有严格媒体校准的 `lesson_002` 完整无声 MP4，但**没有证明旧两次失败的底层原因已经修复**。没有定位到可确定修改的生产代码缺陷，因此生产代码和 0.12 秒阈值均未修改。旧失败定位到浏览器 Runtime 与采集媒体中色板边界之间的时间差，具体来自合成器呈现、采集时间戳还是采集缓冲，原记录不足以进一步区分。本轮短片与唯一一次完整复核均通过，说明问题不能稳定复现。

分支 `codex/visual-acquisition-handoff-20261030`，HEAD `1a667a607ffee0a8d94c915b059b8b45757a9fbf`。本轮新增证据目录为 `datasets/research_generation_v2/dry_run/20261103-media-clock-r1/`；此前改动和运行均保留。原 HTML SHA-256 为 `99107a5a0468655f2b2a6fc0a8a7f75a591c333aa902b9d5c10e9409dd26e7b0`，本次完整复核直接读取该文件，没有重建 HTML。

## 旧失败的只读诊断

浏览器计划、翻页与结束使用 `performance.now()` 单调时钟；`schedule.done` 表示 JS 已执行终止色板插入，并不保证该色板已被合成器呈现或被录制帧采集。录制采用 Playwright `record_video`，不是网页中的 MediaRecorder API。检查本地 Playwright `coreBundle.js` 可见其使用 Chromium screencast metadata timestamp，经 `frameSwapWallTime` 传入录制器，按 25fps 计算重复帧，最终通过 Playwright 自带 ffmpeg 编码 VP8。公开 record 参数 fps 影响后续 H.264 输出，不改变该原始采集帧率。

Playwright 停止时会补至少 1 秒最后一帧；这会延长末尾色板和 WebM 容器。现有 `media_interval()` 通过四象限色板的解码像素定位内容起止，排除了初始加载、首色板和末色板，所以该尾部补帧并不是旧内容区间误差的直接解释。原校准对 raw WebM 解码重采样至至少 30fps 后计数；本次额外按原生 PTS 解码，并用 ffprobe 独立核对。

| 原始失败 | 容器时长 | 首/末帧 PTS | 原生内容起止 PTS | 原生内容长度 | 原校准长度 | Runtime 结束 |
|---|---:|---|---|---:|---:|---:|
| 180s，1600×900 | 182.880s | 0 / 182.840s | 1.040 / 181.240s | 180.200s | 180.200s | 180004.9ms |
| 180.1s，1920×1080 | 183.480s | 0 / 183.440s | 0.800 / 181.840s | 181.040s | 181.0333s | 180102.1ms |

两份容器均为连续 25fps 帧，分别 4572、4587 帧；容器结束与末帧 PTS 只差一帧。原生边界与重采样计算只差至多约 7ms，说明原校准并未凭空计算出 0.2s / 0.933s 误差。0.12s 阈值约为 25fps 三帧，验收的是**实际媒体中色板间内容跨度与请求时长的接近程度**；它不是 Runtime 执行率、总容器长度或音画同步指标。两次旧偏差超过该量化范围，没有证据支持放宽阈值。

确定的部分：旧失败发生在 Runtime 计时与实际采集色板区间之间；停止补帧、容器尾部、输出 fps 以及 fps 重采样计算都不能单独解释旧偏差。尚不能确定的部分：旧记录没有墙钟采样、逐帧 CDP timestamp 或合成器呈现时间，因此不能断言是墙钟调整、合成器延迟或 screencast/编码缓冲。两次视口不同，也不能把其误差变化归因于单独延长末页 0.1 秒。

证据见新目录中的 `original_analysis.json`、两个 `*.ffmpeg.log`、`*.ffprobe.json`。原始 WebM、clock 和 Trace 仍在上一轮 r2 目录，没有覆盖。

## 最小样本与完整复核

最小样本使用已有 `tests/test_recording_clock.py::lesson_html()`：三页各 2 秒，使用正式控制器和录制链。诊断包装只在页面采样 `Date.now()/performance.now()`，并在关闭录制前后记录停止时刻；不修改页面事件、翻页计划或校准逻辑。短片未复现旧失败。

| 项目 | 6 秒样本 | 唯一一次 lesson_002 完整复核 |
|---|---:|---:|
| 请求时长 | 6.000s | 180.000s |
| 浏览器实际结束 | 6005.4ms | 180005.3ms |
| 原始容器长度 | 8.040s | 182.560s |
| 原始首/末帧 PTS | 0 / 8.000s | 0 / 182.520s |
| 校准色板间跨度 | 6.000s | 180.100s |
| 校准偏差 | 0 | +0.100s |
| 墙钟减单调时钟累计变化 | −1.0ms | −0.5ms |
| 关闭前页面 mono 时间 | 7800ms | 181917.5ms |
| Python 启动至关闭请求 | 9.971s | 183.027s |
| Python 启动至关闭完成 | 未补记 | 183.734s |
| MP4 容器时长 | 6.000s | 180.066667s |
| MP4 首/末解码帧 PTS | 0 / 5.966667s | 0.066016 / 180.066016s |
| MP4 帧数/帧率 | 180 / 30fps | 2701 / 15fps |
| 校准状态 | CALIBRATED | CALIBRATED |

完整复核沿用旧首次运行的 1600×900、15fps 输出、180 秒计划，55 个事件均 executed。原生采集仍为 25fps。停止时刻以 `diagnostic_stop_requested` 的 wall/mono 以及 Python 关闭前后时间共同记录，详见两个新 clock 文件。完整复核没有检测到墙钟与单调时钟明显漂移，无法据此回推旧运行也无漂移。

实际 MP4 为 [lesson002.mp4](../../datasets/research_generation_v2/dry_run/20261103-media-clock-r1/lesson002.mp4)。完整解码/PTS 遍历由 ffprobe 完成，只有 H.264 视频流，没有音轨或字幕流。MP4 起始 PTS 非零，帧关联记录同时保留归一化帧序号及实际 PTS，避免将它误作零起点。

这是一组“旧失败→本次成功”的运行对比，不是“代码修复前→修复后”的对比。未修改生产 recorder/calibration，也未伪造或重新标定 PTS。转换只使用正式录制链已有的色板裁除，不裁掉教学内容，没有 time stretching。单次成功不证明长期稳定性已恢复。

## MP4 事件证据等级

`mp4_event_evidence.json` 将 55 个实际执行事件关联至原 G0 event ID、Runtime ID、页号、目标、触发时间、前/后帧序号及联系表行号。按该映射从 MP4 实际解码提取了 87 张不同帧，形成 10 张联系表；联系表每行左为前帧、右为后帧。

本轮实际查看了全部 10 张联系表。10 个页标题在对应后帧可辨认，记录为 `title_visible_in_sample_frame`；另外 45 项记录为 `paired_frames_viewed_object_timing_not_adjudicated`。这 45 项虽然有视频帧关联并已查看联系表，但没有逐个对象连续检查其精确出现和结束窗口，不能写成已审核可见窗口。第 1 页装饰性目标等前后差异不明显，需要对象级复核；若干相邻事件的帧内已有其他组件，尚未裁定提前显示还是正常动画重叠。未将其写成时序通过，也未断言所有 55 项无缺失、过早或过晚。

| 证据等级 | 数量 |
|---|---:|
| G0→Runtime→实际 MP4 帧的确定关联 | 55 |
| 标题对象在抽样后帧确认可见 | 10 |
| 帧对已查看、对象精确时序未裁定 | 45 |
| 连续可见窗口已审核 | 0 |
| 原来源门禁过滤，未进入 Runtime | 10 |

过滤结果由原 HTML 字节/哈希及新 Trace 共同核对：Runtime 仅包含原来的 55 个内部事件 ID，被过滤的图片和标注 10 项仍未进入执行集合。没有补来源审核或改变门禁。没有真实音频、动态字幕验证或人工连续完整视频审核，本次不能声称音画同步通过或 Phase 1 全项通过。

## 文件修改、检查与后续边界

本轮只新增本报告和新的诊断/媒体证据，生产代码、G0/Renderer/Runtime 事件逻辑、冻结 Storyboard、Gold、Baseline 均未改动；既有未提交改动保留。没有为未确定的根因加入推测性修补。

工具使用 `pipeline.recorder._ffmpeg_executable()` 解析到已安装 imageio-ffmpeg 二进制；另发现本机 `C:/Users/H2O-zero/AppData/Roaming/AiWorkCN/program/bin/ffprobe.exe` 可用，版本记录于 `ffprobe-version.txt`。上一轮“ffprobe 缺失”只能说明 PATH 预检没有找到，并不代表磁盘没有可用工具。本轮未更改全局 PATH。

必要定向测试：`pytest tests/test_recording_clock.py -q -k 'not actual_mp4_page_and_element_times and not runtime_stall_is_rejected'`：11 passed、4 deselected。排除的 4 项涉及额外真实录制，使用本轮 6 秒样本和唯一一次完整复核作实际媒体验证。development 预检：33 passed、通过；仍提示 PATH 没有 ffmpeg/ffprobe，但本轮已用明确工具路径完成媒体分析。未运行全量测试、付费模型/VLM、TTS、图片生成或课程规划，未提交或推送。

当前交付解决了“没有可校准 MP4”的产物阻塞；旧采集偏差的底层原因仍未确定，不能宣布录制器已根治。若后续继续诊断间歇性失败，应在短样本采集链记录同一帧的 CDP timestamp、Python 单调接收时刻和可见标记，区分合成器延迟与时间戳问题。本轮按要求停止，不继续长片重试、不补图片审核、不进入 Pilot。
