"""
LLM 客户端封装模块
负责与 OpenAI 兼容 API 交互
"""
import traceback
from typing import List, Dict, Generator
import httpx
from openai import OpenAI
from colorama import Fore, Style


class LLMClient:
    """LLM 客户端类"""
    
    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self.client = None
        
        if api_key:
            # 显式禁用代理，忽略系统环境变量中的代理配置 (HTTP_PROXY, HTTPS_PROXY 等)
            # 这可以解决因系统配置了不兼容的代理协议 (如 socks://) 而导致的启动失败问题
            http_client = httpx.Client(proxy=None)
            self.client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        else:
            print(f"{Fore.RED}警告：未配置有效的 OPENAI_API_KEY。请检查 .env。{Style.RESET_ALL}")
    
    @property
    def is_ready(self) -> bool:
        """检查客户端是否就绪"""
        return self.client is not None
    
    def chat_stream(self, messages: List[Dict]) -> Generator[str, None, None]:
        """
        流式调用 LLM 生成回复
        
        Args:
            messages: 消息列表
            
        Yields:
            生成的文本片段
        """
        if not self.is_ready:
            yield "错误：未配置有效的 OpenAI API Key，无法进行对话。"
            return
        
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception:
            error_trace = traceback.format_exc()
            print(f"\n{Fore.RED}======== LLM 调用错误详情 ========{Style.RESET_ALL}")
            print(f"{Fore.RED}{error_trace}{Style.RESET_ALL}")
            print(f"{Fore.RED}=================================={Style.RESET_ALL}")
            yield "调用 LLM 失败，请查看上方红色错误日志。"
