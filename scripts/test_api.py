"""
验证 ECNU API 连通性

用法：填好 .env 后运行
    python scripts/test_api.py
"""

import sys
from pathlib import Path

# 确保能导入项目包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from textbook2video.llm.client import chat_with_system


def main():
    print("正在测试 ECNU API 连通性...\n")

    # 测试 1: ecnu-max
    print("=== 测试 ecnu-max ===")
    try:
        result = chat_with_system(
            "用一句话介绍什么是人工智能。",
            model="ecnu-max",
            max_tokens=100,
        )
        print(f"回复: {result}\n")
        print("ecnu-max 连通成功\n")
    except Exception as e:
        print(f"ecnu-max 连通失败: {e}\n")

    # 测试 2: ecnu-plus
    print("=== 测试 ecnu-plus ===")
    try:
        result = chat_with_system(
            "用一句话介绍什么是机器学习。",
            model="ecnu-plus",
            max_tokens=100,
        )
        print(f"回复: {result}\n")
        print("ecnu-plus 连通成功\n")
    except Exception as e:
        print(f"ecnu-plus 连通失败: {e}\n")


if __name__ == "__main__":
    main()
