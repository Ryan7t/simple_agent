"""
终端用户界面模块
负责艺术字显示、彩色输出、用户输入处理
"""
import sys
import time
import os
from colorama import Fore, Style, init
from pyfiglet import Figlet


# 初始化 colorama
init()


def read_all_available_lines_windows(first_line: str) -> str:
    """Windows: 使用 msvcrt 检测键盘缓冲区"""
    import msvcrt
    lines = [first_line]
    
    time.sleep(0.1)
    while msvcrt.kbhit():
        try:
            line = input()
            lines.append(line)
            time.sleep(0.02)
        except EOFError:
            break
    
    return "\n".join(lines)


def read_all_available_lines_unix() -> str:
    """
    Unix/Linux: read pasted lines without relying on TextIOWrapper buffering.

    Approach:
    - Read the first line in binary mode (blocking).
    - Prefer bracketed paste markers when supported; otherwise drain a short burst.
    """
    import fcntl
    
    buffer = sys.stdin.buffer
    fd = sys.stdin.fileno()
    paste_start = b"\x1b[200~"
    paste_end = b"\x1b[201~"

    def enable_bracketed_paste() -> bool:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        try:
            sys.stdout.write("\x1b[?2004h")
            sys.stdout.flush()
            return True
        except Exception:
            return False

    def disable_bracketed_paste():
        try:
            sys.stdout.write("\x1b[?2004l")
            sys.stdout.flush()
        except Exception:
            pass

    bracketed_enabled = False
    try:
        bracketed_enabled = enable_bracketed_paste()
        # Read first line (blocking) using the binary buffer to avoid text buffering.
        first_line = buffer.readline()
        if not first_line:
            return ""

        chunks = [first_line]

        # If bracketed paste markers appear, keep reading until the end marker arrives.
        if paste_start in first_line:
            while paste_end not in chunks[-1]:
                line = buffer.readline()
                if not line:
                    break
                chunks.append(line)
            data = b"".join(chunks)
            encoding = sys.stdin.encoding or "utf-8"
            errors = sys.stdin.errors or "replace"
            text = data.decode(encoding, errors=errors)
            text = text.replace("\x1b[200~", "").replace("\x1b[201~", "")
            return "\n".join(text.splitlines())

        original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        try:
            fcntl.fcntl(fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)

            initial_timeout = 0.3
            idle_timeout = 0.2
            max_duration = 2.0
            start_time = time.monotonic()
            last_data_time = start_time
            saw_extra = False

            # Short initial wait to detect paste; if extra data arrives, drain until idle.
            while True:
                try:
                    chunk = buffer.read1(4096)
                except (BlockingIOError, InterruptedError):
                    now = time.monotonic()
                    if not saw_extra and now - start_time >= initial_timeout:
                        break
                    if saw_extra and (now - last_data_time >= idle_timeout or now - start_time >= max_duration):
                        break
                    time.sleep(0.01)
                    continue

                if not chunk:
                    break

                chunks.append(chunk)
                saw_extra = True
                last_data_time = time.monotonic()
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, original_flags)
    finally:
        if bracketed_enabled:
            disable_bracketed_paste()

    data = b"".join(chunks)
    encoding = sys.stdin.encoding or "utf-8"
    errors = sys.stdin.errors or "replace"
    text = data.decode(encoding, errors=errors)
    text = text.replace("\x1b[200~", "").replace("\x1b[201~", "")
    return "\n".join(text.splitlines())


class TerminalUI:
    """终端用户界面类"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
    
    def show_banner(self):
        """显示启动艺术字"""
        f = Figlet(font='slant')
        print(Fore.CYAN + f.renderText(self.agent_name) + Style.RESET_ALL)
    
    def print_agent(self, message: str, end: str = "\n"):
        """打印 Agent 消息"""
        print(f"{Fore.GREEN}[{self.agent_name}]{Style.RESET_ALL} {message}", end=end)
    
    def print_agent_prefix(self):
        """打印 Agent 消息前缀（用于流式输出）"""
        print(f"\n{Fore.GREEN}[{self.agent_name}]{Style.RESET_ALL}", end=" ")
    
    def print_stream(self, chunk: str):
        """打印流式输出片段"""
        print(chunk, end="", flush=True)
    
    def print_newline(self):
        """打印换行"""
        print()
    
    def print_error(self, message: str):
        """打印错误消息"""
        print(f"{Fore.RED}{message}{Style.RESET_ALL}")
    
    def print_warning(self, message: str):
        """打印警告消息"""
        print(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")
    
    def print_info(self, message: str):
        """打印信息消息"""
        print(f"{Fore.CYAN}{message}{Style.RESET_ALL}")
    
    def get_user_input(self) -> str:
        """
        获取用户输入，支持多行粘贴
        当用户粘贴多行内容时，会自动合并为一条消息
        """
        print(f"\n{Fore.BLUE}我的回复 > {Style.RESET_ALL}", end="", flush=True)
        
        if sys.platform == 'win32':
            first_line = input()
            return read_all_available_lines_windows(first_line)
        else:
            return read_all_available_lines_unix()
    
    def print_goodbye(self):
        """打印告别消息"""
        print(Fore.RED + "再见！期待下次相遇～" + Style.RESET_ALL)
