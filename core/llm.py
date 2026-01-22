"""
LLM 客户端封装模块
负责与 OpenAI 兼容 API 交互
"""
from typing import List, Dict, Generator, Optional, Any
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
    
    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None, tool_choice: Optional[str] = None) -> Any:
        """
        非流式调用 LLM（支持工具调用）
        
        Args:
            messages: 消息列表
            tools: 工具定义列表
            tool_choice: 工具选择策略
            
        Returns:
            LLM 响应对象
        """
        if not self.is_ready:
            raise RuntimeError("错误：未配置有效的 OpenAI API Key，无法进行对话。")

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self.client.chat.completions.create(**kwargs)

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None, tool_choice: Optional[str] = None) -> Generator[str, None, None]:
        """
        流式调用 LLM 生成回复
        
        Args:
            messages: 消息列表
            
        Yields:
            生成的文本片段
        """
        for chunk in self.chat_stream_chunks(messages, tools=tools, tool_choice=tool_choice):
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content

    def chat_stream_chunks(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None
    ) -> Generator[Any, None, None]:
        """
        流式调用 LLM，返回原始 chunk 对象（用于处理工具调用）
        """
        if not self.is_ready:
            raise RuntimeError("错误：未配置有效的 OpenAI API Key，无法进行对话。")

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "stream": True
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            yield chunk
