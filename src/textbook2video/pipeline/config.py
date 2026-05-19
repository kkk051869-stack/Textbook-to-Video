"""
全局配置
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env（项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# 项目根目录
PROJECT_ROOT = _PROJECT_ROOT

# 默认路径
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# ── 录制参数 ──
RECORD_VIEWPORT_WIDTH = 1920
RECORD_VIEWPORT_HEIGHT = 1080
RECORD_FPS = 30
RECORD_BROWSER_CHANNEL = "msedge"  # 使用系统 Edge

# ── TTS 参数 ──
TTS_VOICE = "zh-CN-XiaoyiNeural"
TTS_RATE = "+5%"

# ── ffmpeg ──
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")

# ── LLM 配置（华东师范大学大模型服务） ──
ECNU_API_KEY = os.environ.get("ECNU_API_KEY", "")
ECNU_BASE_URL = os.environ.get("ECNU_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1")
ECNU_DEFAULT_MODEL = os.environ.get("ECNU_DEFAULT_MODEL", "ecnu-max")

# 可用模型
ECNU_MODELS = {
    "ecnu-max": {
        "description": "旗舰模型（DeepSeek-V4-Flash），1M 上下文，适合复杂任务",
        "context_window": 1_000_000,
        "quota_multiplier": 3,
    },
    "ecnu-plus": {
        "description": "通用模型（Qwen3.6-27B），256K 上下文，性价比高",
        "context_window": 256_000,
        "quota_multiplier": 1,
    },
}
