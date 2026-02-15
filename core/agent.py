"""
BossAgent 核心类
整合所有模块，实现老板 AI 的主要逻辑
"""
import sys
import json
import re
import threading
import traceback
import httpx
import openai
from typing import List, Dict, Any, Tuple, Optional, Callable, TYPE_CHECKING
from colorama import Fore, Style

from config import settings
from core.memory import Memory
from core.llm import LLMClient
from core.scheduler import TaskScheduler
from prompts import PromptLoader
from context import DocxLoader
if TYPE_CHECKING:
    from ui.terminal import TerminalUI


def _is_timeout_error(err: BaseException) -> bool:
    """判断是否为请求超时错误"""
    if isinstance(err, httpx.TimeoutException):
        return True
    if isinstance(err, (openai.APITimeoutError, openai.Timeout)):
        return True
    seen = set()
    current = err
    while current and current not in seen:
        seen.add(current)
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if isinstance(current, httpx.TimeoutException):
            return True
        if isinstance(current, (openai.APITimeoutError, openai.Timeout)):
            return True
    message = str(err).lower()
    return "timeout" in message or "timed out" in message or "readtimeout" in message or "etimedout" in message


class BossAgent:
    """赛博司马特 - AI 老板 Agent"""
    
    def __init__(self, ui: Optional["TerminalUI"] = None):
        # 初始化配置
        self.name = settings.agent_name
        
        # 初始化各模块
        self.memory = Memory(settings.memory_file)
        self.llm = LLMClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s
        )
        self.prompt_loader = PromptLoader(
            system_prompt_file=settings.system_prompt_file,
            context_intro_file=settings.context_intro_file
        )
        self.doc_loader = DocxLoader(settings.documents_dir)
        if ui is None:
            from ui.terminal import TerminalUI
            self.ui = TerminalUI(self.name)
        else:
            self.ui = ui
        
        # 初始化任务调度器
        self.scheduler = TaskScheduler(settings.task_state_file)

        # 工具定义与处理器
        self.tools = self._build_tools()
        self.tool_handlers = {
            "set_deadline": self._tool_set_deadline,
            "clear_deadline": self._tool_clear_deadline
        }
        
        # 文档上下文延迟加载，避免启动阻塞
        self.document_context = None
        self.document_context_hash = None
        
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
        # 获取系统提示词内容（按需加载文档上下文）
        # 每次调用 load() 检查文件修改时间，自动刷新缓存
        self.document_context = self.doc_loader.load()
        system_content = self.prompt_loader.build_system_content(self.document_context)
        scheduler_status = self.scheduler.get_status()
        if scheduler_status.get("active"):
            remaining = max(0, int(scheduler_status.get("remaining_seconds", 0) // 60))
            deadline = scheduler_status.get("deadline") or ""
            system_content += "\n\n当前系统状态：定时器已设置。"
            system_content += f" 剩余约 {remaining} 分钟。"
            if deadline:
                system_content += f" 截止时间 {deadline}。"
            system_content += " 重要：再次调用 set_deadline 会覆盖已有定时器，除非用户明确要求修改，否则不要重复调用。"
        else:
            system_content += "\n\n当前系统状态：定时器未设置。"
        
        messages = [
            {"role": "system", "content": system_content}
        ]
        
        # 添加历史对话（阶段二：使用完整消息格式）
        for record in self.memory.get_all():
            # 新格式：直接展开完整消息列表
            if "messages" in record:
                messages.extend(record["messages"])
            # 向后兼容旧格式（如果存在）
            elif "user_input" in record and "response" in record:
                messages.append({"role": "user", "content": record["user_input"]})
                messages.append({"role": "assistant", "content": record["response"]})
        
        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})
        
        return messages
    
    def generate_response(
        self,
        user_input: str,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ) -> Tuple[str, List[Dict], bool]:
        """
        生成回复并流式打印
        
        Args:
            user_input: 用户输入
            
        Returns:
            完整的回复内容、本轮对话消息列表、是否写入历史记录
        """
        messages = self.build_messages(user_input)
        self.ui.print_agent_prefix()

        if not self.llm.is_ready:
            error_text = "错误：未配置有效的 OpenAI API Key，无法进行对话。"
            if event_callback:
                event_callback({"type": "error", "content": error_text, "message_id": message_id})
            self.ui.print_error(f"\n{error_text}")
            self.ui.print_newline()
            # 返回错误信息和简单的对话消息
            conversation_messages = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": error_text}
            ]
            return error_text, conversation_messages, False

        try:
            full_response, tool_calls = self._stream_with_tools(
                messages,
                event_callback=event_callback,
                message_id=message_id
            )
        except Exception as err:
            error_trace = traceback.format_exc()
            is_timeout = _is_timeout_error(err)
            error_text = "请求超时，点击“重试”可再次生成。" if is_timeout else error_trace
            if event_callback:
                payload = {"type": "error", "content": error_text, "message_id": message_id}
                if is_timeout:
                    payload["kind"] = "timeout"
                event_callback(payload)
            self.ui.print_error(f"\n{error_trace}")
            self.ui.print_newline()
            # 返回错误跟踪和简单的对话消息
            conversation_messages = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": error_text}
            ]
            return error_text, conversation_messages, False

        tool_used = False
        error_occurred = False
        # 收集本轮对话的完整消息（阶段二：保存完整消息格式）
        conversation_messages = [
            {"role": "user", "content": user_input}
        ]

        if tool_calls:
            tool_used = True
            # 添加 assistant 消息（包含 tool_calls）
            assistant_message = {
                "role": "assistant",
                "content": full_response,
                "tool_calls": tool_calls
            }
            conversation_messages.append(assistant_message)
            messages.append(assistant_message)

            # 执行工具并添加 tool 消息
            tool_messages = self._execute_tool_calls(tool_calls, event_callback=event_callback, message_id=message_id)
            conversation_messages.extend(tool_messages)
            messages.extend(tool_messages)

            # 获取第二轮回复
            second_response, second_error = self._stream_response(
                messages,
                event_callback=event_callback,
                message_id=message_id
            )
            if second_error:
                error_occurred = True
            cleaned_second, dsml_used, dsml_calls, dsml_tool_messages = self._handle_dsml_tool_calls(
                second_response,
                event_callback=event_callback,
                message_id=message_id
            )
            if dsml_used:
                tool_used = True
                if event_callback:
                    event_callback({
                        "type": "replace",
                        "content": full_response + cleaned_second,
                        "message_id": message_id
                    })
                assistant_entry = {"role": "assistant", "content": cleaned_second}
                if dsml_calls:
                    assistant_entry["tool_calls"] = dsml_calls
                conversation_messages.append(assistant_entry)
                conversation_messages.extend(dsml_tool_messages)
                full_response += cleaned_second
            else:
                # 添加第二轮 assistant 消息
                conversation_messages.append({
                    "role": "assistant",
                    "content": second_response
                })
                full_response += second_response
        else:
            full_response, dsml_used, dsml_calls, dsml_tool_messages = self._handle_dsml_tool_calls(
                full_response,
                event_callback=event_callback,
                message_id=message_id
            )
            if dsml_used:
                tool_used = True
                if event_callback:
                    event_callback({"type": "replace", "content": full_response, "message_id": message_id})

            # 添加 assistant 消息
            assistant_entry = {"role": "assistant", "content": full_response}
            if dsml_calls:
                assistant_entry["tool_calls"] = dsml_calls
            conversation_messages.append(assistant_entry)
            if dsml_tool_messages:
                conversation_messages.extend(dsml_tool_messages)

        should_save = not error_occurred
        if should_save:
            self._process_deadline(full_response, tool_used=tool_used)
        return full_response, conversation_messages, should_save

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
                    "description": "设置任务截止时间（分钟），用于循环催促。重复调用会覆盖已有定时器。",
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
        
        # 检查是否已有定时器（阶段一：明确告知覆盖行为）
        status = self.scheduler.get_status()
        if status.get("active"):
            old_remaining = status.get("remaining_seconds", 0) // 60
            self.scheduler.set_deadline(minutes_int)
            return f"已覆盖之前的定时器（原剩余 {old_remaining} 分钟），新的截止时间：{minutes_int}分钟"
        else:
            self.scheduler.set_deadline(minutes_int)
            return f"已设置截止时间：{minutes_int}分钟"

    def _tool_clear_deadline(self, **_unused: Any) -> str:
        """工具：清除截止时间"""
        self.scheduler.clear_deadline()
        return "截止时间已清除"

    def _execute_tool_calls(
        self,
        tool_calls: List[Any],
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """执行工具调用并返回工具消息"""
        tool_messages: List[Dict[str, str]] = []
        for call in tool_calls:
            if isinstance(call, dict):
                function = call.get("function", {}) or {}
                tool_name = function.get("name") or ""
                args_text = function.get("arguments") or "{}"
                call_id = call.get("id")
            else:
                tool_name = call.function.name
                args_text = call.function.arguments or "{}"
                call_id = call.id
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

            if event_callback:
                event_callback({
                    "type": "tool",
                    "message_id": message_id,
                    "name": tool_name,
                    "args": args,
                    "result": str(result)
                })
                
                # 如果是调度器相关工具，主动推送状态变更事件
                if tool_name in ["set_deadline", "clear_deadline"]:
                    event_callback({
                        "type": "scheduler_update",
                        "message_id": message_id,
                        "data": self.scheduler.get_status()
                    })

            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id or tool_name or "unknown_tool",
                "content": str(result)
            })
        return tool_messages

    def _parse_dsml_args(self, body: str) -> Dict[str, Any]:
        """解析 DSML 参数"""
        body = (body or "").strip()
        if not body:
            return {}
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        params: Dict[str, Any] = {}
        param_pattern = re.compile(
            r"<[\|｜]DSML[\|｜]parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</[\|｜]DSML[\|｜]parameter>",
            re.S
        )
        for name, value in param_pattern.findall(body):
            value_text = value.strip()
            if not value_text:
                params[name] = ""
                continue
            try:
                params[name] = json.loads(value_text)
            except json.JSONDecodeError:
                params[name] = value_text
        return params

    def _extract_dsml_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """从 DSML 内容中提取工具调用"""
        if not content:
            return []
        pattern = re.compile(
            r"<[\|｜]DSML[\|｜]invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</[\|｜]DSML[\|｜]invoke>",
            re.S
        )
        matches = pattern.findall(content)
        if not matches:
            return []
        tool_calls: List[Dict[str, Any]] = []
        for index, (name, body) in enumerate(matches):
            args = self._parse_dsml_args(body)
            tool_calls.append({
                "id": f"dsml_{index}_{name}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False)
                }
            })
        return tool_calls

    def _strip_dsml_content(self, content: str) -> str:
        cleaned = re.sub(
            r"<[\|｜]DSML[\|｜]function_calls>.*?</[\|｜]DSML[\|｜]function_calls>",
            "",
            content,
            flags=re.S
        )
        cleaned = re.sub(
            r"<[\|｜]DSML[\|｜]invoke\b.*?</[\|｜]DSML[\|｜]invoke>",
            "",
            cleaned,
            flags=re.S
        )
        cleaned = re.sub(r"</?[\|｜]DSML[\|｜][^>]*>", "", cleaned)
        return cleaned.strip()

    def _handle_dsml_tool_calls(
        self,
        content: str,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ) -> Tuple[str, bool, List[Dict[str, Any]], List[Dict[str, str]]]:
        """解析 DSML 工具调用并执行，同时清理可见输出"""
        if not content:
            return content, False, [], []
        tool_calls = self._extract_dsml_tool_calls(content)
        if not tool_calls:
            return content, False, [], []
        cleaned = self._strip_dsml_content(content)
        tool_messages = self._execute_tool_calls(
            tool_calls,
            event_callback=event_callback,
            message_id=message_id
        )
        return cleaned, True, tool_calls, tool_messages

    def _stream_with_tools(
        self,
        messages: List[Dict],
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """流式请求首轮回复并解析工具调用"""
        full_response = ""
        tool_call_map: Dict[int, Dict[str, Any]] = {}

        for chunk in self.llm.chat_stream_chunks(messages, tools=self.tools, tool_choice="auto"):
            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                if event_callback:
                    event_callback({"type": "chunk", "content": delta.content, "message_id": message_id})
                self.ui.print_stream(delta.content)
                full_response += delta.content

            tool_calls_delta = getattr(delta, "tool_calls", None)
            if tool_calls_delta:
                for tool_call in tool_calls_delta:
                    index = tool_call.index
                    entry = tool_call_map.get(index)
                    if entry is None:
                        entry = {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": "",
                                "arguments": ""
                            }
                        }
                        tool_call_map[index] = entry
                    if tool_call.id:
                        entry["id"] = tool_call.id
                    if tool_call.function:
                        if tool_call.function.name:
                            entry["function"]["name"] = tool_call.function.name
                        if tool_call.function.arguments:
                            entry["function"]["arguments"] += tool_call.function.arguments

        tool_calls = [tool_call_map[index] for index in sorted(tool_call_map.keys())]
        if not tool_calls:
            self.ui.print_newline()
        return full_response, tool_calls

    def _stream_response(
        self,
        messages: List[Dict],
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ) -> Tuple[str, bool]:
        """流式输出 LLM 回复并返回完整内容"""
        full_response = ""
        try:
            for chunk in self.llm.chat_stream(messages):
                if event_callback:
                    event_callback({"type": "chunk", "content": chunk, "message_id": message_id})
                self.ui.print_stream(chunk)
                full_response += chunk
        except Exception as err:
            error_trace = traceback.format_exc()
            is_timeout = _is_timeout_error(err)
            error_text = "请求超时，点击“重试”可再次生成。" if is_timeout else error_trace
            if event_callback:
                payload = {"type": "error", "content": error_text, "message_id": message_id}
                if is_timeout:
                    payload["kind"] = "timeout"
                event_callback(payload)
            self.ui.print_error(f"\n{error_trace}")
            full_response = error_text
            self.ui.print_newline()
            return full_response, True
        self.ui.print_newline()
        return full_response, False
    
    def _on_deadline_reached(self):
        """截止时间到达时的回调"""
        self._auto_followup_triggered.set()
    
    def handle_startup(
        self,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ):
        """处理首次启动的开场白"""
        if self.memory.is_empty():
            init_input = "（系统自动触发：用户已上线。当前没有任何历史对话记录，这是全新的一天。直接开门见山问今天的工作计划：写自然选题还是做商单？语气要直接有力，不给犹豫空间，像老板布置任务一样，不要客气。）"
            response, conversation_messages, should_save = self.generate_response(
                init_input,
                event_callback=event_callback,
                message_id=message_id
            )
            if should_save:
                self.memory.add(conversation_messages, request_input=init_input)
            return response
        return ""
    
    def handle_proactive_followup(
        self,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ):
        """处理主动追问（空输入或定时触发）"""
        time_info = self.prompt_loader.get_time_info()
        proactive_input = f"（系统自动触发：用户请求你主动追问。当前时间是 {time_info['time_str']} {time_info['weekday']}，现在是{time_info['time_period']}。请根据历史对话上下文和当前时间，用严厉的语气催促用户汇报工作进度。如果之前在讨论选题，就直接质问选题想好了没有；如果在改稿，就追问改得怎么样了；如果时间过了很久还没进展，就骂他拖延、摸鱼。用老板训斥员工的语气说话，要凶狠一点，别客气，让他感受到压力。）"
        response, conversation_messages, should_save = self.generate_response(
            proactive_input,
            event_callback=event_callback,
            message_id=message_id
        )
        if should_save:
            self.memory.add(conversation_messages, request_input=proactive_input)
        return response
    
    def handle_auto_followup(
        self,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ):
        """处理定时自动触发的追问"""
        time_info = self.prompt_loader.get_time_info()
        auto_input = f"（系统自动触发：任务截止时间已到，用户还没有任何回复。当前时间是 {time_info['time_str']} {time_info['weekday']}，现在是{time_info['time_period']}。之前你给用户布置了任务并设定了截止时间，现在时间到了他还没交付成果。请用非常严厉凶狠的语气骂他、训斥他。像老板发现员工拖延任务时那样愤怒地质问：时间到了东西呢？在干什么？是不是又在摸鱼？要直接骂出来，让他感受到你的怒火和不满。如果他还没完成，除了骂他，还要追问到底卡在哪里了，是能力不行还是态度有问题。语气要凶，要狠，要让他意识到拖延的严重性。）"
        response, conversation_messages, should_save = self.generate_response(
            auto_input,
            event_callback=event_callback,
            message_id=message_id
        )
        if should_save:
            self.memory.add(conversation_messages, request_input=auto_input)
        return response
    
    def handle_user_input(
        self,
        user_input: str,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        message_id: Optional[str] = None
    ):
        """处理正常用户输入"""
        response, conversation_messages, should_save = self.generate_response(
            user_input,
            event_callback=event_callback,
            message_id=message_id
        )
        if should_save:
            self.memory.add(conversation_messages, request_input=user_input)
        return response
    
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

    def shutdown(self):
        """停止后台资源（用于非交互模式）"""
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
