"""
对话记忆管理模块
负责加载和保存对话历史
"""
import json
import time
import os
from typing import List, Dict


class Memory:
    """对话记忆管理类"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.history: List[Dict] = []
        self._ensure_dir()
        self.load()
    
    def _ensure_dir(self):
        """确保数据目录存在"""
        dir_path = os.path.dirname(self.file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
    
    def load(self) -> List[Dict]:
        """加载历史对话记录"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []
        return self.history
    
    def save(self):
        """保存对话记录到文件"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存记忆文件失败: {e}")
    
    def add(self, messages: List[Dict]):
        """添加一条对话记录（完整消息列表）"""
        self.history.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": messages  # 保存完整消息列表（包括 user、assistant、tool_calls、tool）
        })
        self.save()
    
    def is_empty(self) -> bool:
        """检查是否有历史记录"""
        return len(self.history) == 0
    
    def get_all(self) -> List[Dict]:
        """获取所有历史记录"""
        return self.history
    
    def clear(self):
        """清空历史记录"""
        self.history = []
        self.save()
