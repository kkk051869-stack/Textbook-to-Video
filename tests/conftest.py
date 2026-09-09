"""Pytest 配置"""
import sys
from pathlib import Path

# 确保 src 在 Python path 中
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))