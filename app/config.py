"""配置管理模块 - 单例模式"""
import os
import threading
from pathlib import Path
from typing import Optional

import tomllib
from pydantic import BaseModel, Field


class ServerSettings(BaseModel):
    """服务器配置"""
    name: str = Field(default="mcp-server", description="服务器名称")
    host: str = Field(default="localhost", description="主机地址")
    port: int = Field(default=8080, description="端口")
    transport: str = Field(default="sse", description="传输协议（sse/websocket）")


class LLMSettings(BaseModel):
    """LLM 配置"""
    model: str = Field(default="qwen3.7-plus", description="模型名称")
    base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", description="API 地址")
    api_key: str = Field(default="", description="API Key")
    max_tokens: int = Field(default=4096, description="最大 Token 数")
    temperature: float = Field(default=0.2, description="温度")
    timeout: int = Field(default=60, description="超时时间（秒）")


class ToolSettings(BaseModel):
    """工具配置"""
    timeout: int = Field(default=30, description="工具执行超时（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")
    enable_cache: bool = Field(default=True, description="是否启用结果缓存")
    cache_ttl: int = Field(default=300, description="缓存TTL（秒）")


class AppConfig(BaseModel):
    """应用配置"""
    server: ServerSettings = Field(default_factory=ServerSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    tool: ToolSettings = Field(default_factory=ToolSettings)


class Config:
    """全局配置 - 单例模式"""
    _instance: Optional["Config"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config: Optional[AppConfig] = None

    def load(self, config_path: Optional[str] = None) -> AppConfig:
        """加载配置"""
        if self._config is not None:
            return self._config

        if config_path is None:
            config_path = os.getenv(
                "CONFIG_PATH",
                str(Path(__file__).parent.parent / "config" / "config.toml"),
            )

        config_data = {}
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                config_data = tomllib.load(f)

        # 合并环境变量
        llm_data = config_data.get("llm", {})
        env_api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if env_api_key:
            llm_data["api_key"] = env_api_key

        self._config = AppConfig(
            server=ServerSettings(**config_data.get("server", {})),
            llm=LLMSettings(**llm_data),
            tool=ToolSettings(**config_data.get("tool", {})),
        )
        return self._config

    @property
    def server(self) -> ServerSettings:
        if self._config is None:
            self.load()
        return self._config.server

    @property
    def llm(self) -> LLMSettings:
        if self._config is None:
            self.load()
        return self._config.llm

    @property
    def tool(self) -> ToolSettings:
        if self._config is None:
            self.load()
        return self._config.tool


def get_config(config_path: Optional[str] = None) -> AppConfig:
    """获取配置"""
    config = Config()
    return config.load(config_path)
