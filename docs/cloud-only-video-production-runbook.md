# 云端全流程教学视频出片手册

本手册定义“教材输入到最终 MP4 均在云端完成”的标准流程。最终 MP4、HTML、音频、字幕和 manifest 全部保存在 `/ai/data/textbook-to-video`；本地只用于 SSH 连接、查看或下载交付物，不参与生成与录制。

## 1. 运行约束

云端代码目录：

```text
/ai/data/repos/Textbook-to-Video
```

云端输入、缓存、浏览器、模型、任务与交付目录：

```text
/ai/data/textbook-to-video
/ai/data/models
/ai/data/tools
```

硬规则：所有安装包、Python 包、浏览器、浏览器依赖、模型、缓存和运行产物只能位于 `/ai/data`。禁止向 `/root`、`/root/.cache` 或 `/tmp` 写入长期内容。

建议的单次任务目录：

```text
/ai/data/textbook-to-video/jobs/chapter2-YYYYMMDD-HHMM/
```

最终交付目录：

```text
/ai/data/textbook-to-video/deliveries/textbook2video-qwen32b-YYYYMMDD/
```

## 2. SSH 与环境

本地连接：

```powershell
Start-Service ssh-agent
ssh-add "D:\Code\vibe coding\materials2textbook\private_key_digital_book.pem"
ssh digital_book
```

进入云端后：

```bash
source /ai/data/use_ai_env.sh
cd /ai/data/repos/Textbook-to-Video
```

## 3. 一次性准备云端录制运行时

云端要完成录制，需要同时具备：

1. Python Playwright 包；
2. `/ai/data` 下的 Chromium；
3. Chromium 所需的共享库，例如 `pango`、`glib`、`nss`、`gtk`、`libxkbcommon`；
4. `ffmpeg`/`ffprobe`。

当前环境若报 `libpango-1.0.so.0` 缺失，**不能直接开始教材任务**。先在 `/ai/data` 下创建专用浏览器运行时，例如通过 Conda/Mamba 安装到：

```text
/ai/data/tools/envs/t2v-cloud-browser/
```

运行时变量示例：

```bash
export PYTHONPATH=/ai/data/textbook-to-video/python-packages:/ai/data/repos/Textbook-to-Video/src
export PLAYWRIGHT_BROWSERS_PATH=/ai/data/textbook-to-video/ms-playwright
export T2V_BROWSER_EXECUTABLE=/ai/data/textbook-to-video/ms-playwright/chromium-1234/chrome-linux64/chrome
export PATH=/ai/data/tools/bin:$PATH
export LD_LIBRARY_PATH=/ai/data/tools/envs/t2v-cloud-browser/lib:${LD_LIBRARY_PATH:-}
```

浏览器、Python 包和共享库的版本必须作为一套固定运行时维护；不要让 Playwright 自动下载到默认 cache。

## 4. 云端录制冒烟测试

每次更换 Chromium、Playwright、系统库或镜像后，先用一页短 HTML 做录制测试：

```bash
cd /ai/data/repos/Textbook-to-Video
python -m textbook2video.cli doctor --browser ''
python -m textbook2video.cli record /ai/data/textbook-to-video/smoke/smoke.html \
  /ai/data/textbook-to-video/smoke/smoke.mp4 --duration 5
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 \
  /ai/data/textbook-to-video/smoke/smoke.mp4
```

只有 smoke MP4 可播放、时长正确且浏览器没有缺库错误，才能开始正式任务。

## 5. 启动 Qwen3-32B vLLM

启动前检查 GPU 没有遗留进程：

```bash
nvidia-smi
ps -eo pid,ppid,cmd | grep -E '[v]llm|[E]ngineCore'
```

若异常退出后遗留 `VLLM::EngineCore`，只结束确认过的精确 PID。不要在不确认进程归属时使用宽泛 kill。

启动命令：

```bash
mkdir -p /ai/data/textbook-to-video/cache/vllm \
  /ai/data/textbook-to-video/cache/torchinductor \
  /ai/data/textbook-to-video/logs

nohup env \
  CUDA_VISIBLE_DEVICES=0 \
  VLLM_WORKER_MULTIPROC_METHOD=spawn \
  XDG_CACHE_HOME=/ai/data/textbook-to-video/cache \
  TORCHINDUCTOR_CACHE_DIR=/ai/data/textbook-to-video/cache/torchinductor \
  /ai/data/tools/envs/cosyvoice3/bin/python -m vllm.entrypoints.openai.api_server \
  --model /ai/data/models/qwen/Qwen3-32B-AWQ \
  --served-model-name qwen3-32b-awq \
  --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.85 \
  --max-model-len 16384 \
  --quantization awq_marlin \
  > /ai/data/textbook-to-video/logs/vllm-$(date +%Y%m%d-%H%M%S).log 2>&1 &

curl -fsS http://127.0.0.1:8000/v1/models
```

`/v1/models` 必须返回 `qwen3-32b-awq` 后才允许调用生成器。

## 6. 生成与配音

为每一章创建新的任务目录，禁止复用旧 HTML：

```bash
export LLM_API_KEY=EMPTY
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export T2V_MODEL=qwen3-32b-awq
export T2V_TTS_BACKEND=megatts3
export PATH=/ai/data/tools/bin:$PATH
```

标准阶段顺序：

```text
DOCX -> lesson plan -> script -> storyboard
     -> MegaTTS3 WAV -> timed storyboard -> HTML -> manifest
     -> cloud Chromium record (silent MP4) -> subtitle -> mux -> final MP4
```

MegaTTS3 旁白必须经过术语规范化；`CPU/GPU/NPU/AI` 分别读为字母拼读，页面文字仍保留原缩写。

教学页顺序固定为：

```text
正文 -> 想一想 -> 知识点检测 -> 本节小结 -> 结束页
```

## 7. 录制前门禁

在录制前必须运行 `verify_render_bundle`，并要求全部通过：

```bash
python - <<'PY'
from textbook2video.pipeline.artifact_integrity import verify_render_bundle

print(verify_render_bundle(
    '/ai/data/textbook-to-video/jobs/chapter2-YYYYMMDD-HHMM/chapter2_timed_storyboard.json',
    '/ai/data/textbook-to-video/jobs/chapter2-YYYYMMDD-HHMM/chapter2_timed-pipeline-dark-blue-academic.html',
    audio_dir='/ai/data/textbook-to-video/jobs/chapter2-YYYYMMDD-HHMM/chapter2_audio',
))
PY
```

该校验确保：

- HTML `slideDurations` 与 timed storyboard 的逐页时长完全一致；
- 音频段数等于页面数；
- 音频总时长与 timed storyboard 误差不超过 `0.1s`；
- manifest 记录 HTML 与 storyboard 的 SHA-256。

任何失败都必须回到“配音后重新渲染 HTML”阶段，不能手工修改时长数组。

## 8. 云端录制、合成与终检

录制时长使用：

```text
ceil(manifest.total_duration_sec) + 1 秒
```

录制结束后在云端完成音频合成：

```text
silent.mp4 + s1.wav ... sN.wav + SRT -> final.mp4
```

最终复核：

```bash
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 final.mp4
```

最终 MP4 时长应与 manifest 的 `total_duration_sec` 保持在 `0.1s` 内。成功后只复制以下文件到 delivery 目录：

```text
计算机科学讲义-01-计算机原理.html
计算机科学讲义-01-计算机原理.mp4
```

不要把 raw、storyboard、WAV、silent.mp4、浏览器录制 WebM 或日志复制到交付目录。

## 9. 批量策略

1. 先完整生成一个章节，并人工观看首页、正文页、活动页、结束页。
2. 确认缩写发音、教学顺序、无乱码和音画同步均正常。
3. 云端串行处理后续章节；避免 vLLM、MegaTTS3 和多个 Chromium 录制进程同时抢占 GPU/CPU。
4. 每章完成后立即执行 manifest 和最终 MP4 时长检查。
5. 全部通过后再整理到 delivery 目录。

## 10. vLLM 与 MegaTTS3 资源互斥（硬性门禁）

本机型中，vLLM 和 MegaTTS3 **不得同时运行**。两者都会占用 GPU；并发启动会导致显存不足、TTS 失败，或生成任务不稳定。录制虽然主要使用 Chromium/CPU，也必须排在 TTS 完成之后，避免多章任务互相争抢内存、磁盘和 ffmpeg。

每次在两个阶段之间切换，必须执行以下检查：

```bash
# 先确认目前是谁占用 GPU
nvidia-smi
ps -eo pid,ppid,cmd | grep -E '[v]llm|[E]ngineCore|[m]egatts|[c]osyvoice'

# vLLM -> MegaTTS3：仅结束已经确认属于本次 vLLM 服务的精确 PID，
# 再次确认 nvidia-smi 中该进程已消失后，才能启动 MegaTTS3。

# MegaTTS3 -> 下一批 LLM：确认 MegaTTS3 进程已经自然退出或被正常停止，
# 再启动 vLLM；不可让两个服务重叠。
```

推荐的批量队列如下，按阶段串行，而不是按章节端到端并行：

```text
阶段 A（仅 vLLM）
  第 1 章至第 5 章：DOCX -> lesson plan -> script -> storyboard
  停止 vLLM，并确认显存释放

阶段 B（仅 MegaTTS3）
  第 1 章至第 5 章：WAV -> timed storyboard -> HTML -> manifest
  每章完成后立即 verify_render_bundle；失败的章在这里修复，不进入录制队列
  停止 MegaTTS3，并确认显存释放

阶段 C（不启动 vLLM 或 MegaTTS3）
  按章节串行：Chromium record (silent MP4) -> subtitle -> mux -> ffprobe
  每章通过时长和可播放检查后，再处理下一章
```

不要同时录制多章，也不要在 Chromium 录制期间启动下一章的 MegaTTS3 或 vLLM。每章只允许使用本章任务目录中的 timed storyboard、音频目录和 manifest，禁止跨章节复用。

## 11. 故障处理

| 现象 | 处理 |
| --- | --- |
| `libpango`/浏览器动态库错误 | 停止正式任务；先补齐 `/ai/data` 浏览器运行时并通过 smoke MP4 |
| HTML 固定每页 5 秒 | HTML 来自未配音 storyboard；必须使用 timed storyboard 重渲染 |
| CPU 读成 GPU | 确认 MegaTTS3 输入已通过缩写规范化 |
| vLLM 无法启动且显存被占 | 检查并清理确认过的残留 EngineCore；检查缓存变量是否在 `/ai/data` |
| manifest 校验失败 | 不录制；重新从对应 timed storyboard 与音频阶段生成 |
| final MP4 时长不对 | 检查 mux 的音频目录是否来自同一任务目录，重新合成 |
