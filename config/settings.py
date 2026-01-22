"""
配置管理模块
负责加载环境变量和提供配置访问接口
"""
import os
import json
import sys
from dotenv import load_dotenv


class Settings:
    """应用配置类"""
    
    def __init__(self):
        # 加载 .env 文件
        self._load_env()

        # 文件路径配置
        base_dir_override = os.getenv("BOSS_BASE_DIR")
        inferred_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = base_dir_override or getattr(sys, "_MEIPASS", inferred_base_dir)
        data_dir_override = os.getenv("BOSS_DATA_DIR")
        self.data_dir = data_dir_override or os.path.join(self.base_dir, "data")
        self.prompts_dir = os.path.join(self.base_dir, "prompts", "templates")
        self.prompt_overrides_dir = os.path.join(self.data_dir, "prompts")
        self.runtime_config_file = os.path.join(self.data_dir, "runtime_config.json")

        # LLM 配置
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V3.2")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")

        # Agent 配置
        self.agent_name = "CyberBoss"

        # 数据文件
        self.memory_file = os.path.join(self.data_dir, "conversation_history.json")
        self.task_state_file = os.path.join(self.data_dir, "task_state.json")
        self.documents_dir = os.path.join(self.data_dir, "文案")

        # 提示词文件
        self.system_prompt_file = self._resolve_prompt_file("system_prompt.txt")
        self.context_intro_file = self._resolve_prompt_file("context_intro.txt")

        # 运行时配置覆盖
        self._apply_runtime_overrides()

    def _resolve_prompt_file(self, filename: str) -> str:
        """优先使用用户数据目录中的提示词文件"""
        override_path = os.path.join(self.prompt_overrides_dir, filename)
        if os.path.exists(override_path):
            return override_path
        return os.path.join(self.prompts_dir, filename)
    
    def _load_env(self):
        """加载环境变量"""
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.env'
        )
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path, override=True)

    def _load_runtime_config(self) -> dict:
        """加载运行时配置"""
        if os.path.exists(self.runtime_config_file):
            try:
                with open(self.runtime_config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _save_runtime_config(self, config: dict):
        """保存运行时配置"""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.runtime_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _apply_runtime_overrides(self, overrides: dict = None):
        """应用运行时配置覆盖"""
        overrides = overrides if overrides is not None else self._load_runtime_config()
        if not overrides:
            return

        if "llm_model" in overrides and overrides["llm_model"] is not None:
            self.llm_model = str(overrides["llm_model"])
        if "openai_api_key" in overrides and overrides["openai_api_key"] is not None:
            self.openai_api_key = str(overrides["openai_api_key"])
        if "openai_base_url" in overrides and overrides["openai_base_url"] is not None:
            self.openai_base_url = str(overrides["openai_base_url"])
        if "documents_dir" in overrides and overrides["documents_dir"] is not None:
            value = str(overrides["documents_dir"])
            if value:
                self.documents_dir = value
            else:
                self.documents_dir = os.path.join(self.data_dir, "文案")

    def get_runtime_config(self) -> dict:
        """获取当前运行时配置"""
        return {
            "llm_model": self.llm_model,
            "openai_api_key": self.openai_api_key,
            "openai_base_url": self.openai_base_url,
            "documents_dir": self.documents_dir
        }

    def update_runtime_config(self, updates: dict) -> dict:
        """更新运行时配置并持久化"""
        config = self._load_runtime_config()
        for key in ["llm_model", "openai_api_key", "openai_base_url", "documents_dir"]:
            if key in updates:
                config[key] = updates[key]
        self._save_runtime_config(config)
        self._apply_runtime_overrides(config)
        return self.get_runtime_config()
    
    @property
    def is_api_configured(self) -> bool:
        """检查 API 是否已配置"""
        return bool(self.openai_api_key)


# 全局配置实例
settings = Settings()
