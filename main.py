#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CyberBoss - 赛博司马特 AI 老板
程序入口
"""

from core import BossAgent


def main():
    """主函数"""
    agent = BossAgent()
    agent.run()


if __name__ == "__main__":
    main()
