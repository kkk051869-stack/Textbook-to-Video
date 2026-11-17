# 稳定教学视频出片手册

本手册用于把 DOCX 教材稳定产出为「dark-blue-academic + MegaTTS3」教学视频。核心原则是：**同一章的音频、timed storyboard、HTML 和 MP4 必须来自同一个任务目录**；任一校验不通过时停止，不录制、不交付。

## 1. 固定目录与命名

本地仓库：

```text
D:\Code\vibe coding\Textbook-to-Video
```

云端代码与数据：

```text
/ai/data/repos/Textbook-to-Video
/ai/data/textbook-to-video
```

每次生成新建一个任务根目录，不能复用旧任务目录。例如：

```text
/ai/data/textbook-to-video/jobs/chapter2-YYYYMMDD-HHMM/
```

该目录内每章必须包含：

```text
<chapter>_storyboard.json
<chapter>_timed_storyboard.json
<chapter>_audio/s1.wav ... sN.wav
<chapter>_timed-pipeline-dark-blue-academic.html
<chapter>_timed-pipeline-dark-blue-academic.manifest.json
run_status.json
```

最终交付目录只放最终文件，一章一个同名 HTML/MP4 对：

```text
cloud_exports/textbook2vedio-qwen32B-YYYYMMDD/
计算机科学讲义-01-计算机原理.html
计算机科学讲义-01-计算机原理.mp4
...
```

## 2. 云端连接与硬规则

本地先启动 SSH agent：

```powershell
Start-Service ssh-agent
ssh-add "D:\Code\vibe coding\materials2textbook\private_key_digital_book.pem"
ssh digital_book
```

云端的安装、缓存、浏览器、模型、任务产物必须在 `/ai/data`。禁止把长期内容放在 `/root`。

启动 vLLM 时必须指定缓存根，避免 torch.compile 写到 `/root/.cache`：

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
```

健康检查：

```bash
curl -fsS http://127.0.0.1:8000/v1/models
```

只有返回模型列表后才开始生成。若曾经异常停止 vLLM，先检查并结束残留的 `VLLM::EngineCore`，否则会占住显存并导致下一次启动失败。

## 3. 正确的生成顺序

严格按以下顺序执行，不能把旧 HTML 与新音频混用：

1. 解析教材、生成 lesson plan、讲稿和 storyboard。
2. 使用 MegaTTS3 生成分段音频。
3. 测量每段真实时长，写入 `audio_duration_sec`，生成 `*_timed_storyboard.json`。
4. **只使用 timed storyboard** 渲染 HTML。
5. 校验 timed storyboard、HTML 与分段音频。
6. 将完整任务包下载到本地。
7. 本地 Edge 录制无声视频。
8. 合成音频、字幕，得到 MP4。
9. 复核最终 MP4 时长并复制到交付目录。

禁止做法：

- 先渲染 HTML、之后才配音，却不重新渲染 HTML。
- 用不同日期或不同任务目录里的 HTML、WAV、storyboard 拼在一起。
- 在云端缺少 Playwright/系统库时强行录制。
- 只看视频文件存在就判定成功。

## 4. MegaTTS3 与术语发音

云端运行需要：

```bash
export T2V_TTS_BACKEND=megatts3
```

旁白在进入 TTS 前会把常见技术缩写规范为可控读法：

```text
CPU -> C P U
GPU -> G P U
NPU -> N P U
AI  -> A I
```

这只影响声音，HTML 仍显示 `CPU`、`GPU` 等原始文字。每次首次更换 TTS 模型或提示音后，应先生成一页含 CPU/GPU 的样本试听。

## 5. 教学页面规则

lesson plan 的教学页采用固定顺序：

```text
正文 -> 想一想 -> 知识点检测 -> 本节小结 -> 结束页
```

若原 storyboard 最后一页包含“感谢聆听”“下节课再见”等结语，活动、测验、小结必须插入在这页之前。这样不会出现先说再见、随后又出现测验的错误教学顺序。

## 6. 录制前的强制校验

`artifact_integrity.verify_render_bundle` 是出片门禁。它检查：

- timed storyboard 的页数和 `audio_duration_sec` 是否完整；
- HTML 中 `slideDurations` 是否与每页音频时长完全相同；
- 分段音频数是否等于页数；
- 分段音频总时长与 storyboard 总时长的误差是否不超过 `0.1s`；
- 生成 manifest，记录 storyboard/HTML 的 SHA-256。

录制前必须运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -c "from textbook2video.pipeline.artifact_integrity import verify_render_bundle; import sys; print(verify_render_bundle(sys.argv[1], sys.argv[2], audio_dir=sys.argv[3]))" `
  <timed_storyboard.json> <html> <audio_dir>
```

校验失败时的处理：重新从第 3 步或第 4 步开始，不能手工修改 `slideDurations` 来凑时长。

## 7. 本地录制与合成

本地应使用系统 Edge。录制时长为：

```text
ceil(manifest.total_duration_sec) + 1 秒
```

额外 1 秒只用于保护最后一页，最终 mux 使用音频长度裁剪成片。Windows 上若 `ffmpeg` 不在 PATH，可以使用已有的 imageio-ffmpeg 二进制；执行录制和合成的子进程必须能找到标准名 `ffmpeg.exe`。

录制后依次检查：

```text
silent.mp4 已生成 -> 合成 WAV -> final.mp4 已生成 -> final.mp4 时长等于 manifest.total_duration_sec
```

## 8. 批量执行建议

先单章验收，再批量：

1. 先选第 2 章做完整样本。
2. 检查 CPU/GPU 发音、活动页顺序、首页布局和音画同步。
3. 样本通过后，云端按章节串行生成完整任务包。
4. 本地也按章节串行录制，避免多个 Playwright/ffmpeg 进程争资源。
5. 每完成一章，立即将最终 HTML/MP4 复制进交付目录。

## 9. 交付前清单

- [ ] 每章都有同名 `.html` 和 `.mp4`。
- [ ] 每章 manifest 校验通过。
- [ ] MP4 时长与音频总时长一致。
- [ ] CPU/GPU 等术语试听正确。
- [ ] 活动、测验、小结在结束页之前。
- [ ] 抽查首页、中间一页、活动页、结语页无乱码、无元素溢出。
- [ ] 交付目录不混入 raw、storyboard、WAV、silent.mp4 等中间产物。

## 10. 常见故障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 声音与翻页差很多 | HTML 来自旧 storyboard，或页面固定为 5 秒 | 用 timed storyboard 重新渲染；通过 manifest 后再录制 |
| CPU 被读成 GPU | TTS 对缩写发音不稳定 | 确认 `normalize_tts_text` 生效；先做试听样本 |
| vLLM 启动很慢或显存被占 | 残留 EngineCore / 初次图编译 | 清理残留进程；保留 `/ai/data` 下编译缓存 |
| `/root/.cache/vllm` 出现缓存 | 未设置 XDG/TorchInductor 缓存变量 | 停止实例、清理精确缓存目录后按第 2 节重启 |
| 云端 HTML 已好但无法录制 | 云端缺 Playwright 或系统动态库 | 下载完整包到本地 Edge 录制 |
| Windows 后台录制参数错乱 | 空格/中文路径被命令行拆分 | 用无参数的 Python 启动器，在脚本内固定路径 |
| `ffmpeg` 找不到 | PATH 未包含二进制 | 将标准名 `ffmpeg.exe` 所在目录加入录制/合成进程 PATH |
