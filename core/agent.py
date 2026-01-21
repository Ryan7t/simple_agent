"""
BossAgent 核心类
整合所有模块，实现老板 AI 的主要逻辑
"""
import sys
import json
import threading
from typing import List, Dict, Any
from colorama import Fore, Style

from config import settings
from core.memory import Memory
from core.llm import LLMClient
from core.scheduler import TaskScheduler
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
        
        # 初始化任务调度器
        self.scheduler = TaskScheduler(settings.task_state_file)

        # 工具定义与处理器
        self.tools = self._build_tools()
        self.tool_handlers = {
            "set_deadline": self._tool_set_deadline,
            "clear_deadline": self._tool_clear_deadline
        }
        
        # 加载文档上下文
        self.document_context = self.doc_loader.load()
        
        # 用于非阻塞输入的同步机制
        self._input_ready = threading.Event()
        self._pending_input = None
        self._auto_followup_triggered = threading.Event()
    
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

        if not self.llm.is_ready:
            self.ui.print_error("\n错误：未配置有效的 OpenAI API Key，无法进行对话。")
            self.ui.print_newline()
            return ""

        tool_response = self.llm.chat(messages, tools=self.tools, tool_choice="auto")
        if tool_response is None:
            fallback_messages = messages + [
                {
                    "role": "system",
                    "content": "（系统提示：工具不可用时，请在回复末尾使用【截止时间：N分钟】或【任务完成】标记。）"
                }
            ]
            full_response = self._stream_response(fallback_messages)
            self._process_deadline(full_response, tool_used=False)
            return full_response

        assistant_message = tool_response.choices[0].message
        tool_calls = assistant_message.tool_calls or []
        tool_used = False

        if tool_calls:
            tool_used = True
            assistant_tool_calls = []
            for call in tool_calls:
                assistant_tool_calls.append({
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments
                    }
                })
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": assistant_tool_calls
            })
            messages.extend(self._execute_tool_calls(tool_calls))
            full_response = self._stream_response(messages)
        else:
            full_response = assistant_message.content or ""
            if full_response:
                self.ui.print_stream(full_response)
            self.ui.print_newline()

        self._process_deadline(full_response, tool_used=tool_used)
        return full_response

    def _process_deadline(self, response: str, tool_used: bool):
        """从回复中解析截止时间并设置调度器（工具调用失败时的兜底）"""
        if tool_used:
            return
        minutes = self.scheduler.parse_deadline(response)
        if minutes is not None:
            if minutes > 0:
                self.scheduler.set_deadline(minutes)
            else:
                # minutes == 0 表示任务完成
                self.scheduler.clear_deadline()

    def _build_tools(self) -> List[Dict[str, Any]]:
        """构建工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "set_deadline",
                    "description": "设置任务截止时间（分钟），用于循环催促。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "minutes": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "从现在起的分钟数"
                            }
                        },
                        "required": ["minutes"],
                        "additionalProperties": False
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "clear_deadline",
                    "description": "清除当前截止时间，停止循环催促。",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                }
            }
        ]

    def _tool_set_deadline(self, minutes: Any, **_unused: Any) -> str:
        """工具：设置截止时间"""
        try:
            minutes_int = int(minutes)
        except (TypeError, ValueError):
            return "设置失败：minutes 参数无效"
        self.scheduler.set_deadline(minutes_int)
        return f"已设置截止时间：{minutes_int}分钟"

    def _tool_clear_deadline(self, **_unused: Any) -> str:
        """工具：清除截止时间"""
        self.scheduler.clear_deadline()
        return "截止时间已清除"

    def _execute_tool_calls(self, tool_calls: List[Any]) -> List[Dict[str, str]]:
        """执行工具调用并返回工具消息"""
        tool_messages: List[Dict[str, str]] = []
        for call in tool_calls:
            tool_name = call.function.name
            args_text = call.function.arguments or "{}"
            try:
                args = json.loads(args_text)
            except json.JSONDecodeError:
                args = {}

            handler = self.tool_handlers.get(tool_name)
            if handler is None:
                result = f"未知工具：{tool_name}"
            else:
                try:
                    if isinstance(args, dict):
                        result = handler(**args)
                    else:
                        result = handler(args)
                except Exception as e:
                    result = f"工具执行失败：{e}"

            tool_messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result)
            })
        return tool_messages

    def _stream_response(self, messages: List[Dict]) -> str:
        """流式输出 LLM 回复并返回完整内容"""
        full_response = ""
        try:
            for chunk in self.llm.chat_stream(messages):
                self.ui.print_stream(chunk)
                full_response += chunk
        except Exception as e:
            self.ui.print_error(f"\n流式接收出错: {e}")
        self.ui.print_newline()
        return full_response
    
    def _on_deadline_reached(self):
        """截止时间到达时的回调"""
        self._auto_followup_triggered.set()
    
    def handle_startup(self):
        """处理首次启动的开场白"""
        if self.memory.is_empty():
            init_input = "（系统自动触发：用户已上线。当前没有任何历史对话记录，这是全新的一天。请直接询问用户今天的工作计划：写自然选题还是做商单？不要追问昨天的任务，因为没有昨天的记录。）"
            response = self.generate_response(init_input)
            self.memory.add("（用户上线）", response)
    
    def handle_proactive_followup(self):
        """处理主动追问（空输入或定时触发）"""
        time_info = self.prompt_loader.get_time_info()
        proactive_input = f"（系统自动触发：用户请求你主动追问。当前时间是 {time_info['time_str']} {time_info['weekday']}，现在是{time_info['time_period']}。请根据历史对话上下文和当前时间，主动询问用户的工作进度。比如：如果之前在讨论选题，就问选题想好了没；如果在改稿，就问改得怎么样了；如果时间过了很久还没进展，就催一催。用老板的语气说话。）"
        response = self.generate_response(proactive_input)
        self.memory.add("（主动追问）", response)
    
    def handle_auto_followup(self):
        """处理定时自动触发的追问"""
        time_info = self.prompt_loader.get_time_info()
        auto_input = f"（系统自动触发：任务截止时间已到。当前时间是 {time_info['time_str']} {time_info['weekday']}，现在是{time_info['time_period']}。之前你给用户布置了任务并设定了截止时间，现在时间到了。请根据历史对话上下文，催促用户汇报任务进度。如果用户还没完成，问他卡在哪里了需要什么帮助。用老板的语气说话，直接但不粗暴。）"
        response = self.generate_response(auto_input)
        self.memory.add("（定时催促）", response)
    
    def handle_user_input(self, user_input: str):
        """处理正常用户输入"""
        response = self.generate_response(user_input)
        self.memory.add(user_input, response)
    
    def run(self):
        """主循环"""
        # 显示启动 Banner
        self.ui.show_banner()
        
        # 启动调度器
        self.scheduler.start(self._on_deadline_reached)
        
        try:
            # 处理首次启动
            self.handle_startup()
            
            # 主循环
            while True:
                # 清除自动触发标志
                self._auto_followup_triggered.clear()
                
                # 使用非阻塞方式等待输入或定时触发
                user_input = self._get_input_with_timeout()
                
                # 检查是否是定时触发的自动追问
                if user_input is None:
                    self.handle_auto_followup()
                    continue
                
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
        finally:
            # 确保调度器正确停止
            self.scheduler.stop()
    
    def _get_input_with_timeout(self) -> str:
        """
        获取用户输入，同时监听定时触发事件
        支持多行粘贴，自动合并为一条消息
        
        Returns:
            用户输入字符串，如果是定时触发则返回 None
        """
        import sys
        
        # 先打印输入提示
        print(f"\n{Fore.BLUE}我的回复 > {Style.RESET_ALL}", end="", flush=True)
        
        input_result = [None]
        input_done = threading.Event()
        
        def read_input():
            try:
                if sys.platform == 'win32':
                    from ui.terminal import read_all_available_lines_windows
                    first_line = input()
                    input_result[0] = read_all_available_lines_windows(first_line)
                else:
                    from ui.terminal import read_all_available_lines_unix
                    input_result[0] = read_all_available_lines_unix()
            except EOFError:
                input_result[0] = "exit"
            finally:
                input_done.set()
        
        # 启动输入线程
        input_thread = threading.Thread(target=read_input, daemon=True)
        input_thread.start()
        
        # 等待用户输入或定时触发
        while True:
            # 每 0.5 秒检查一次
            if input_done.wait(timeout=0.5):
                # 用户已输入
                return input_result[0]
            
            if self._auto_followup_triggered.is_set():
                # 定时触发 - 打印换行，旧的输入线程会继续在后台等待
                # 但由于是 daemon 线程，用户按回车后不会有副作用
                print()  # 换行，让催促消息在新行显示
                return None
