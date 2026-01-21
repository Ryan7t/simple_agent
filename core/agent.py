"""
BossAgent 核心类
整合所有模块，实现老板 AI 的主要逻辑
"""
from typing import List, Dict

from config import settings
from core.memory import Memory
from core.llm import LLMClient
from prompts import PromptLoader
from context import DocxLoader
from ui import TerminalUI


class BossAgent:
    """赛博司马特 - AI 老板 Agent"""
    
    def __init__(self):
        # 初始化配置
        self.name = settings.agent_name
        
        # 初始化各模块
        self.memory = Memory(settings.memory_file)
        self.llm = LLMClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model
        )
        self.prompt_loader = PromptLoader(
            system_prompt_file=settings.system_prompt_file,
            context_intro_file=settings.context_intro_file
        )
        self.doc_loader = DocxLoader(settings.documents_dir)
        self.ui = TerminalUI(self.name)
        
        # 加载文档上下文
        self.document_context = self.doc_loader.load()
    
    def build_messages(self, user_input: str) -> List[Dict]:
        """
        构建发送给 LLM 的消息列表
        
        Args:
            user_input: 用户输入
            
        Returns:
            消息列表
        """
        # 获取系统提示词内容
        system_content = self.prompt_loader.build_system_content(self.document_context)
        
        messages = [
            {"role": "system", "content": system_content}
        ]
        
        # 添加历史对话
        for record in self.memory.get_all():
            messages.append({"role": "user", "content": record["user_input"]})
            messages.append({"role": "assistant", "content": record["response"]})
        
        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})
        
        return messages
    
    def generate_response(self, user_input: str) -> str:
        """
        生成回复并流式打印
        
        Args:
            user_input: 用户输入
            
        Returns:
            完整的回复内容
        """
        messages = self.build_messages(user_input)
        self.ui.print_agent_prefix()
        
        full_response = ""
        try:
            for chunk in self.llm.chat_stream(messages):
                self.ui.print_stream(chunk)
                full_response += chunk
        except Exception as e:
            self.ui.print_error(f"\n流式接收出错: {e}")
        
        self.ui.print_newline()
        return full_response
    
    def handle_startup(self):
        """处理首次启动的开场白"""
        if self.memory.is_empty():
            init_input = "（系统自动触发：用户已上线。当前没有任何历史对话记录，这是全新的一天。请直接询问用户今天的工作计划：写自然选题还是做商单？不要追问昨天的任务，因为没有昨天的记录。）"
            response = self.generate_response(init_input)
            self.memory.add("（用户上线）", response)
    
    def handle_proactive_followup(self):
        """处理主动追问（空输入触发）"""
        time_info = self.prompt_loader.get_time_info()
        proactive_input = f"（系统自动触发：用户请求你主动追问。当前时间是 {time_info['time_str']} {time_info['weekday']}，现在是{time_info['time_period']}。请根据历史对话上下文和当前时间，主动询问用户的工作进度。比如：如果之前在讨论选题，就问选题想好了没；如果在改稿，就问改得怎么样了；如果时间过了很久还没进展，就催一催。用老板的语气说话。）"
        response = self.generate_response(proactive_input)
        self.memory.add("（主动追问）", response)
    
    def handle_user_input(self, user_input: str):
        """处理正常用户输入"""
        response = self.generate_response(user_input)
        self.memory.add(user_input, response)
    
    def run(self):
        """主循环"""
        # 显示启动 Banner
        self.ui.show_banner()
        
        # 处理首次启动
        self.handle_startup()
        
        # 主循环
        while True:
            user_input = self.ui.get_user_input()
            
            # 退出命令
            if user_input.lower() == "exit":
                self.ui.print_goodbye()
                break
            
            # 空输入触发主动追问
            if not user_input.strip():
                self.handle_proactive_followup()
                continue
            
            # 正常对话
            self.handle_user_input(user_input)
