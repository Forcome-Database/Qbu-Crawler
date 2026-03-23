#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
便捷启动脚本 — 从源码运行时使用

    uv run python main.py <product-url>
    uv run python main.py serve

等价于 pip install 后运行 qbu-crawler 命令。
"""

from qbu_crawler.cli import main

if __name__ == "__main__":
    main()
