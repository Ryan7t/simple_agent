"""
任务调度器模块
负责管理任务截止时间和自动触发催促
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from colorama import Fore, Style


class TaskScheduler:
    """任务调度器 - 管理任务截止时间并在到期时触发回调"""
    
    # 匹配截止时间的正则表达式
    DEADLINE_PATTERNS = [
        r"【截止时间[：:]\s*(\d+)\s*分钟】",
        r"【任务截止[：:]\s*(\d+)\s*分钟后?】",
        r"【(\d+)\s*分钟后催促】",
    ]
    
    # 任务完成标记
    COMPLETE_PATTERNS = [
        r"【任务完成】",
        r"【完成】",
    ]
    
    def __init__(self, state_file: str = "data/task_state.json"):
        self.state_file = state_file
        self.deadline: Optional[datetime] = None
        self.interval_minutes: Optional[int] = None  # 存储间隔时间，用于循环触发
        self.callback: Optional[Callable] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        self._ensure_dir()
        self._load_state()
    
    def _ensure_dir(self):
        """确保数据目录存在"""
        dir_path = os.path.dirname(self.state_file)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
    
    def _load_state(self):
        """从文件加载截止时间状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.interval_minutes = data.get("interval_minutes")
                    if data.get("deadline"):
                        self.deadline = datetime.fromisoformat(data["deadline"])
                        # 如果加载的截止时间已经过期，基于间隔重新计算下一个截止时间
                        if self.deadline <= datetime.now() and self.interval_minutes:
                            self._reset_deadline()
            except Exception:
                self.deadline = None
                self.interval_minutes = None
    
    def _save_state(self):
        """保存截止时间状态到文件"""
        try:
            data = {
                "deadline": self.deadline.isoformat() if self.deadline else None,
                "interval_minutes": self.interval_minutes,
                "updated_at": datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{Fore.RED}保存任务状态失败: {e}{Style.RESET_ALL}")
    
    def parse_deadline(self, text: str) -> Optional[int]:
        """
        从文本中解析截止时间（分钟数）
        
        Args:
            text: LLM 返回的文本
            
        Returns:
            分钟数，如果没有找到则返回 None
        """
        # 先检查是否有任务完成标记
        for pattern in self.COMPLETE_PATTERNS:
            if re.search(pattern, text):
                return 0  # 返回 0 表示清除截止时间
        
        # 解析截止时间
        for pattern in self.DEADLINE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        
        return None
    
    def set_deadline(self, minutes: int):
        """
        设置截止时间（从现在起 N 分钟后），并启用循环催促
        
        Args:
            minutes: 分钟数
        """
        with self._lock:
            if minutes <= 0:
                self.clear_deadline()
                return
            
            self.interval_minutes = minutes
            self.deadline = datetime.now() + timedelta(minutes=minutes)
            self._save_state()
            print(f"{Fore.CYAN}[调度器] 已设置截止时间: {self.deadline.strftime('%H:%M:%S')} ({minutes}分钟后，循环催促){Style.RESET_ALL}")
    
    def _reset_deadline(self):
        """重置截止时间到下一个周期（用于循环催促）"""
        if self.interval_minutes:
            # 基于上一个截止时间累加，避免漂移
            self.deadline = self.deadline + timedelta(minutes=self.interval_minutes)
            self._save_state()
    
    def clear_deadline(self):
        """清除当前截止时间（停止循环催促）"""
        with self._lock:
            if self.deadline:
                print(f"{Fore.CYAN}[调度器] 截止时间已清除，循环催促停止{Style.RESET_ALL}")
            self.deadline = None
            self.interval_minutes = None
            self._save_state()
    
    def is_overdue(self) -> bool:
        """检查是否已超时"""
        with self._lock:
            if self.deadline is None:
                return False
            return datetime.now() >= self.deadline
    
    def get_remaining_seconds(self) -> Optional[float]:
        """获取剩余秒数，如果没有截止时间返回 None"""
        with self._lock:
            if self.deadline is None:
                return None
            remaining = (self.deadline - datetime.now()).total_seconds()
            return max(0, remaining)

    def get_status(self) -> dict:
        """获取调度器状态信息"""
        with self._lock:
            if self.deadline is None:
                return {
                    "active": False,
                    "deadline": None,
                    "interval_minutes": None,
                    "remaining_seconds": None
                }
            remaining = (self.deadline - datetime.now()).total_seconds()
            return {
                "active": True,
                "deadline": self.deadline.isoformat(),
                "interval_minutes": self.interval_minutes,
                "remaining_seconds": max(0, remaining)
            }
    
    def start(self, callback: Callable):
        """
        启动后台调度线程
        
        Args:
            callback: 截止时间到达时调用的回调函数
        """
        self.callback = callback
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
    
    def _monitor_loop(self):
        """后台监控循环"""
        while not self._stop_event.is_set():
            should_trigger = False
            callback = None
            
            with self._lock:
                if (self.deadline is not None and 
                    datetime.now() >= self.deadline and 
                    self.callback is not None):
                    should_trigger = True
                    callback = self.callback
                    # 重置到下一个周期（循环催促）
                    self._reset_deadline()
            
            if should_trigger:
                # 在锁外部调用回调
                try:
                    callback()
                except Exception as e:
                    print(f"{Fore.RED}[调度器] 回调执行出错: {e}{Style.RESET_ALL}")
            
            # 每秒检查一次
            self._stop_event.wait(1.0)
    
    def trigger_now(self):
        """立即触发回调（用于手动测试）"""
        with self._lock:
            if self.callback:
                self.callback()
