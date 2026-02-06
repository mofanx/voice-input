#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨设备语音输入传输系统 - 兼容入口
推荐使用新方式运行：voice-input 或 python -m voice_input
此文件保留以兼容旧的 python voice_server.py 用法
"""

import sys

from voice_input.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
