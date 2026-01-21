"""
配置管理模块
负责加载环境变量和提供配置访问接口
"""
import os
from dotenv import load_dotenv


class Settings:
    """应用配置类"""
    
    def __init__(self):
        # 加载 .env 文件
        self._load_env()
        
        # LLM 配置
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V3.2")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
        
        # Agent 配置
        self.agent_name = "CyberBoss"
        
        # 文件路径配置
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, "data")
        self.prompts_dir = os.path.join(self.base_dir, "prompts", "templates")
        
        # 数据文件
        self.memory_file = os.path.join(self.data_dir, "conversation_history.json")
        self.documents_dir = os.path.join(self.data_dir, "文案")
        
        # 提示词文件
        self.system_prompt_file = os.path.join(self.prompts_dir, "system_prompt.txt")
        self.context_intro_file = os.path.join(self.prompts_dir, "context_intro.txt")
    
    def _load_env(self):
        """加载环境变量"""
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.env'
        )
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path, override=True)
    
    @property
    def is_api_configured(self) -> bool:
        """检查 API 是否已配置"""
        return bool(self.openai_api_key)


# 全局配置实例
settings = Settings()
