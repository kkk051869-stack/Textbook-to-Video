# PresentAgent B 本地材料状态

更新时间：2026-08-04 中午

## 结论

B 侧明天上传云端所需的本地材料已经准备齐全。

包括：

- 8 个正式课节数据包。
- PresentAgent 指定 commit 的代码包。
- Linux Python 3.11 运行时。
- PresentAgent 离线 Python wheelhouse。
- CPU 版 PyTorch wheelhouse。
- marker-pdf 相关 wheelhouse。
- MegaTTS3 TTS 权重包。
- LibreOffice Linux deb 包。
- tiktoken `o200k_base` 缓存。
- 云端安装脚本和 PresentAgent baseline runner。

云端现在关闭，所以尚未上传；明天云端打开后统一上传到 `/ai/data/textbook-to-video/uploads/`。

## 已准备文件

```text
TextbookEval-v1-formal-review.zip
cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz
PresentAgent-repo-b9990e9.tar.gz
PresentAgent-wheelhouse-core-py311-linux.tar.gz
PresentAgent-wheelhouse-torch-py311-linux.tar.gz
PresentAgent-wheelhouse-marker-py311-linux.tar.gz
PresentAgent-wheelhouse-remaining-py311-linux.tar.gz
PresentAgent-MegaTTS3-checkpoints.tar.gz
LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz
tiktoken-cache-o200k/fb374d419588a4632f3f557e76b4b70aebbca790
```

## 文件哈希

```text
8D15BD0663C0D1E06B7312A4250CEFC44EDEE7ED825D4460E21FC7D75796D94B  TextbookEval-v1-formal-review.zip
D93A7699505EE0AC7DEC0F09324FFB19A31CCE3066A287BB1FE95285CE3EA0C7  cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz
1DF1E80BD159E3FE939C58AEAF297724471BA8D06C58F000CF599C0DF1210C31  PresentAgent-repo-b9990e9.tar.gz
A85690D5D4CEF4F38EE942C53BDCAD2CD72EB607EED6A53B3311B9212F0692C8  PresentAgent-wheelhouse-core-py311-linux.tar.gz
DFC20F5EE12D2EC6EBA887ECDE93180AD95544DCC0CD19F0FEB7B6CE1C6033D0  PresentAgent-wheelhouse-torch-py311-linux.tar.gz
136138EB17C212BF5A878D713EFDB93231CC691404C3E956A69E3061473173A0  PresentAgent-wheelhouse-marker-py311-linux.tar.gz
DCF4CDCC9D6910AC37FB84001E035068EFC910718B2B634A1550F89465651BB9  PresentAgent-wheelhouse-remaining-py311-linux.tar.gz
E2AA06B4192B5245749AA7CA90D1DE8944D8276AA83D8BAECA56152EB2C70D48  PresentAgent-MegaTTS3-checkpoints.tar.gz
7F4D7B2E36921EEC5122C655249A24CC88935EE357E8261FD3BCCD15AA1F7B9F  LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz
446A9538CB6C348E3516120D7C08B09F57C36495E2ACFFFE59A5BF8B0CFB1A2D  tiktoken-cache-o200k/fb374d419588a4632f3f557e76b4b70aebbca790
```

## MegaTTS3 状态

MegaTTS3 权重已经完整下载并打包：

```text
PresentAgent-MegaTTS3-checkpoints.tar.gz
```

原始 checkpoint 目录共 22 个文件，总大小 4,269,603,672 bytes。压缩包大小约 3.81 GB。

PresentAgent 运行时会把这些文件放到：

```text
/ai/data/repos/PresentAgent/presentagent/MegaTTS3/checkpoints
```

云端安装脚本 `scripts/install_presentagent_cloud.sh` 已经支持自动解压该权重包。

## 云端上传目标

上传到：

```text
/ai/data/textbook-to-video/uploads/
```

建议上传命令在本地 PowerShell 执行：

```powershell
scp TextbookEval-v1-formal-review.zip digital_book:/ai/data/textbook-to-video/uploads/
scp cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-repo-b9990e9.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-wheelhouse-core-py311-linux.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-wheelhouse-torch-py311-linux.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-wheelhouse-marker-py311-linux.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-wheelhouse-remaining-py311-linux.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp PresentAgent-MegaTTS3-checkpoints.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz digital_book:/ai/data/textbook-to-video/uploads/
scp tiktoken-cache-o200k/fb374d419588a4632f3f557e76b4b70aebbca790 digital_book:/ai/data/textbook-to-video/uploads/o200k_base_cache
```

## 云端安装命令

云端打开后执行：

```bash
source /ai/data/use_ai_env.sh
cd /ai/data/repos/Textbook-to-Video
bash scripts/install_presentagent_cloud.sh
```

## B 的正式运行命令

```bash
source /ai/data/repos/Textbook-to-Video/.env
export OPENAI_API_KEY="$ECNU_API_KEY"
export API_BASE="$ECNU_BASE_URL"
export LANGUAGE_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export VISION_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export TEXT_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export TIKTOKEN_CACHE_DIR=/ai/data/tools/tiktoken-cache
export PYTHONPATH=/ai/data/repos/PresentAgent
export PATH=/ai/data/tools/libreoffice/program:/ai/data/tools/bin:$PATH

/ai/data/tools/envs/presentagent/bin/python \
  /ai/data/repos/Textbook-to-Video/scripts/run_presentagent_baseline.py \
  --slides 7
```

## 本次新增/更新的辅助脚本

- `scripts/download_hf_file_parallel.py`：用 Python requests 支持代理和分片下载 HuggingFace 大文件。
- `scripts/download_megatts3_with_proxy.py`：用 `127.0.0.1:7897` 代理下载 MegaTTS3 全量 checkpoint。
- `scripts/download_megatts3_checkpoints.ps1`：普通 curl 版 MegaTTS3 下载脚本，保留作为无代理环境 fallback。
