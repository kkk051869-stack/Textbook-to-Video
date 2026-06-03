"""
全局配置
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env（项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if os.environ.get("TEXTBOOK2VIDEO_SKIP_DOTENV") != "1":
    _ = load_dotenv(_PROJECT_ROOT / ".env")

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
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_RATE = "+5%"

# ── ffmpeg ──
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")

# ── LLM 配置（华东师范大学大模型服务） ──
ECNU_API_KEY = os.environ.get("ECNU_API_KEY", "")
ECNU_BASE_URL = os.environ.get("ECNU_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1")
ECNU_DEFAULT_MODEL = os.environ.get("ECNU_DEFAULT_MODEL", "ecnu-max")

# ── 通用 OpenAI-compatible LLM 配置（优先级高于 ECNU） ──
def select_llm_config() -> tuple[str, str, str]:
    """Select LLM credentials as a matched key/base-url/model tuple."""
    ecnu_api_key = os.environ.get("ECNU_API_KEY", "")
    ecnu_base_url = os.environ.get("ECNU_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1")
    ecnu_default_model = os.environ.get("ECNU_DEFAULT_MODEL", "ecnu-max")

    llm_api_key = os.environ.get("LLM_API_KEY")
    llm_base_url = os.environ.get("LLM_BASE_URL")
    if llm_api_key and llm_base_url:
        return llm_api_key, llm_base_url, os.environ.get("LLM_DEFAULT_MODEL", ecnu_default_model)

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai_base_url = os.environ.get("OPENAI_BASE_URL")
    if openai_api_key and openai_base_url:
        return openai_api_key, openai_base_url, os.environ.get("OPENAI_MODEL", ecnu_default_model)

    return ecnu_api_key, ecnu_base_url, ecnu_default_model


LLM_API_KEY, LLM_BASE_URL, LLM_DEFAULT_MODEL = select_llm_config()

# ── AI 图片生成配置 ──
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "ecnu-image")
IMAGE_SIZE = os.environ.get("IMAGE_SIZE", "1024x1024")

# 可用模型
ECNU_MODELS = {
    "ecnu-max": {
        "description": "旗舰模型（DeepSeek-V4-Flash），1M 上下文，适合复杂任务；"
        "注意：实测生成长 HTML 较慢（约 350s/批）且偶发超时，追求速度建议用 ecnu-plus",
        "context_window": 1_000_000,
        "quota_multiplier": 3,
    },
    "ecnu-plus": {
        "description": "通用模型（Qwen3.6-27B），256K 上下文，性价比高；"
        "实测生成快（数秒至数十秒），推荐用于动画 HTML 生成",
        "context_window": 256_000,
        "quota_multiplier": 1,
    },
}
