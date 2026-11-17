# Textbook-to-Video 运行 README

本文记录在 Windows 电脑 `echo` 上配置、启动和访问本项目 Web 演示界面的步骤。

项目目录：

```text
D:\text python\Textbook-to-Video-master\Textbook-to-Video-master
```

推荐访问地址：

```text
http://192.168.1.100:5000
```

## 1. 基础环境

### 1.1 Python 环境

当前使用的 Python 环境是：

```text
D:\anaconda3\envs\textbook2video\python.exe
```

确认环境可用：

```powershell
D:\anaconda3\envs\textbook2video\python.exe --version
```

### 1.2 安装项目依赖

进入项目目录：

```powershell
cd "D:\text python\Textbook-to-Video-master\Textbook-to-Video-master"
```

安装项目本体依赖：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m pip install -e .
```

安装 Web 界面依赖：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m pip install -r requirements-web.txt
```

安装 Playwright 浏览器：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m playwright install chromium
```

如果看到 LiteLLM 关于 `botocore` 的 warning，通常可以忽略；如果想消除 warning：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m pip install botocore
```

## 2. 环境变量

项目通过 `.env` 读取模型/API 配置。确认项目根目录存在：

```text
.env
```

如果需要新建，可参考：

```text
.env.example
```

常见模型选择：

```text
ecnu-plus
```

## 3. 启动 Web 服务

### 3.1 本机访问模式

只在 echo 电脑本机访问时，可以直接运行：

```powershell
cd "D:\text python\Textbook-to-Video-master\Textbook-to-Video-master"
D:\anaconda3\envs\textbook2video\python.exe web_app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

### 3.2 局域网访问模式

如果要从另一台电脑访问 echo 电脑上的 Web 页面，推荐使用局域网启动脚本：

```powershell
cd "D:\text python\Textbook-to-Video-master\Textbook-to-Video-master"
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
D:\anaconda3\envs\textbook2video\python.exe run_web_lan.py
```

浏览器打开：

```text
http://192.168.1.100:5000
```

如果 `run_web_lan.py` 不存在，创建内容如下：

```python
from web_app import app

print("Textbook-to-Video Web on 0.0.0.0:5000")
app.run(host="0.0.0.0", port=5000, debug=False)
```

## 4. 防火墙放行

如果局域网访问 `http://192.168.1.100:5000` 超时，需要在 echo 电脑管理员 PowerShell 中放行 5000 端口：

```powershell
New-NetFirewallRule `
  -Name "TextbookToVideoWeb5000" `
  -DisplayName "Textbook-to-Video Web 5000" `
  -Enabled True `
  -Direction Inbound `
  -Protocol TCP `
  -Action Allow `
  -LocalPort 5000
```

检查端口是否监听：

```powershell
Get-NetTCPConnection -LocalPort 5000
```

正常应看到：

```text
0.0.0.0:5000 Listen
```

## 5. 使用流程

1. 打开 Web 页面：

```text
http://192.168.1.100:5000
```

2. 上传教材文件：

```text
DOCX 或 PDF
```

3. 等待系统读取章节列表。

4. 选择章节、视觉主题、模型。

推荐：

```text
视觉主题：深蓝学术
模型：ecnu-plus
```

5. 点击“开始生成”。

6. 等待日志跑完，生成成功后下载 MP4。

输出目录：

```text
output\web_demo\
```

上传目录：

```text
uploads\
```

## 6. 命令行运行

### 6.1 DOCX 生成

DOCX 使用 `--chapter` 和 `--section`，都是 0-based 编号：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m textbook2video.cli produce `
  "uploads\textbook.docx" `
  --chapter 2 `
  --section 6 `
  --theme dark-blue-academic `
  --model ecnu-plus `
  -o "output\web_demo\manual_docx"
```

### 6.2 PDF 生成

PDF 使用 `--lesson`：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m textbook2video.cli produce `
  "uploads\textbook.pdf" `
  --lesson 14 `
  --theme dark-blue-academic `
  --model ecnu-plus `
  -o "output\web_demo\manual_pdf"
```

注意：

```text
PDF 不要传 --chapter / --section
DOCX 不要传 --lesson
```

## 7. 常见问题

### 7.1 LiteLLM botocore warning

现象：

```text
No module named 'botocore'
```

说明：

```text
这是 LiteLLM 对 AWS Bedrock/SageMaker 流式响应能力的 warning。
如果不用 AWS Bedrock 或 SageMaker，通常可以忽略。
```

可选修复：

```powershell
D:\anaconda3\envs\textbook2video\python.exe -m pip install botocore
```

### 7.2 UnicodeEncodeError: gbk

现象：

```text
UnicodeEncodeError: 'gbk' codec can't encode character
```

原因：

```text
Windows 子进程 stdout 使用 GBK，遇到 emoji 或部分 Unicode 字符会失败。
```

修复：

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
```

Web 启动脚本也应保留这两个环境变量。

### 7.3 页面无法访问

先在 echo 电脑上检查：

```powershell
Get-NetTCPConnection -LocalPort 5000
```

如果只看到：

```text
127.0.0.1:5000 Listen
```

说明只能 echo 本机访问。局域网访问需要启动在：

```text
0.0.0.0:5000
```

如果看到 `0.0.0.0:5000 Listen` 但外部仍访问不了，检查防火墙 5000 端口。

### 7.4 PDF 被当成 DOCX

正确规则：

```text
PDF 只走 --lesson
DOCX 只走 --chapter + --section
```

如果 PDF 误传 `--chapter/--section`，程序会直接报清晰错误，不再进入 DOCX 解析器。

### 7.5 DOCX 章节越界

Web 页面现在使用 `parser.list_sections_from_docx()` 返回真实可提取小节。

如果命令行手动运行，确保 `--chapter` 和 `--section` 是生成器识别到的 0-based 坐标。

## 8. 监控运行状态

查看 Web 服务：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match "python" -and $_.CommandLine -match "run_web_lan|web_app" } |
  Select-Object ProcessId,CommandLine
```

查看任务进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match "python" -and $_.CommandLine -match "textbook2video.cli produce" } |
  Select-Object ProcessId,CommandLine
```

查看最近输出：

```powershell
Get-ChildItem "D:\text python\Textbook-to-Video-master\Textbook-to-Video-master\output\web_demo" -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 Name,LastWriteTime
```

## 9. 视频加速工具

如果需要把录屏加速 15 倍，可用 ffmpeg：

```powershell
ffmpeg -i "input.mp4" `
  -filter_complex "[0:v]setpts=PTS/15[v];[0:a]atempo=2,atempo=2,atempo=2,atempo=1.875[a]" `
  -map "[v]" -map "[a]" `
  -c:v libx264 -preset veryfast -crf 23 `
  -c:a aac -b:a 128k `
  -movflags +faststart `
  "input_15x.mp4"
```

