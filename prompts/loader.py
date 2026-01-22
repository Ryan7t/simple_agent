"""
提示词加载器模块
负责加载系统提示词和上下文引导
"""
import os
from datetime import datetime
from colorama import Fore, Style


class PromptLoader:
    """提示词加载器"""

    DEFAULT_SYSTEM_PROMPT = "你是一个智能助手，请根据提供的上下文回答用户的问题。"

    def __init__(self, system_prompt_file: str, context_intro_file: str):
        self.system_prompt_file = system_prompt_file
        self.context_intro_file = context_intro_file
        self._system_prompt = None
        self._context_intro = None
    
    def load_system_prompt(self) -> str:
        """加载系统提示词"""
        if self._system_prompt is not None:
            return self._system_prompt
            
        if os.path.exists(self.system_prompt_file):
            try:
                with open(self.system_prompt_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        self._system_prompt = content
                        return content
            except Exception as e:
                print(f"{Fore.RED}读取系统提示词文件失败: {e}{Style.RESET_ALL}")
        
        self._system_prompt = self.DEFAULT_SYSTEM_PROMPT
        return self._system_prompt
    
    def load_context_intro(self) -> str:
        """加载上下文引导语"""
        if self._context_intro is not None:
            return self._context_intro
            
        if os.path.exists(self.context_intro_file):
            try:
                with open(self.context_intro_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        self._context_intro = content
                        return content
            except Exception as e:
                print(f"{Fore.RED}读取上下文引导文件失败: {e}{Style.RESET_ALL}")
        
        self._context_intro = ""
        return self._context_intro

    
    @staticmethod
    def get_time_info() -> dict:
        """获取当前时间信息"""
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        hour = now.hour
        
        if hour < 12:
            time_period = "上午"
        elif hour < 18:
            time_period = "下午"
        else:
            time_period = "晚上"
        
        return {
            "datetime": now,
            "date_str": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time_str": now.strftime("%Y-%m-%d %H:%M"),
            "weekday": weekdays[now.weekday()],
            "hour": hour,
            "time_period": time_period
        }
    
    def build_system_content(self, document_context: str = "") -> str:
        """
        构建完整的系统提示词内容
        
        Args:
            document_context: 文档上下文内容
            
        Returns:
            完整的系统提示词
        """
        time_info = self.get_time_info()
        
        # 构建内容
        content = f"{self.load_system_prompt()}\n\n"
        content += f"【当前时间信息】\n今天是：{time_info['date_str']} {time_info['weekday']}\n\n"
        
        context_intro = self.load_context_intro()
        if context_intro:
            content += f"【背景设定/引导】\n{context_intro}\n\n"

        if document_context:
            content += f"【参考文档内容】\n{document_context}"
        
        return content
