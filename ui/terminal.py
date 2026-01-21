"""
终端用户界面模块
负责艺术字显示、彩色输出、用户输入处理
"""
from colorama import Fore, Style, init
from pyfiglet import Figlet


# 初始化 colorama
init()


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
        """获取用户输入"""
        return input(f"\n{Fore.BLUE}我的回复 > {Style.RESET_ALL}")
    
    def print_goodbye(self):
        """打印告别消息"""
        print(Fore.RED + "再见！期待下次相遇～" + Style.RESET_ALL)
