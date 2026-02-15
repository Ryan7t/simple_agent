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
    
    def add(self, messages: List[Dict], request_input: str = ""):
        """添加一条对话记录（完整消息列表）"""
        self.history.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "request_input": request_input or "",
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

    def update_message(
        self,
        record_index: int,
        message_index: int = None,
        role: str = None,
        content: str = ""
    ) -> bool:
        """更新指定记录中的消息内容"""
        if record_index is None:
            return False
        if record_index < 0 or record_index >= len(self.history):
            return False
        record = self.history[record_index]
        messages = record.get("messages")
        if not isinstance(messages, list):
            return False
        target_index = message_index
        if target_index is None or target_index < 0 or target_index >= len(messages):
            if role:
                for idx in range(len(messages) - 1, -1, -1):
                    msg = messages[idx]
                    if msg.get("role") == role:
                        target_index = idx
                        break
        if target_index is None or target_index < 0 or target_index >= len(messages):
            return False
        messages[target_index]["content"] = content
        # 查找第一条 user 消息，更新 request_input
        for idx, msg in enumerate(messages):
            if msg.get("role") == "user":
                record["request_input"] = msg.get("content", "")
                break
        self.save()
        return True

    def replace_record(self, record_index: int, messages: List[Dict], request_input: str = "") -> bool:
        """用新的消息列表替换指定记录"""
        if record_index < 0 or record_index >= len(self.history):
            return False
        self.history[record_index] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "request_input": request_input or "",
            "messages": messages
        }
        self.save()
        return True
