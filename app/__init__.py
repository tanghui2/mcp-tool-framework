"""MCP工具集成框架

模块组织：
- app.protocol: MCP 协议层（消息/传输/服务器）
- app.tools: 工具层（基类/注册中心/内置工具）
- app.client: MCP 客户端
- app.models: 数据模型
- app.config: 配置管理
- app.logger: 日志
"""
from .config import get_config
from .logger import logger
from .models import (
    ClientInfo,
    MCPMessage,
    MessageType,
    ServerInfo,
    ToolCategory,
    ToolInfo,
    ToolResult,
    ToolSchema,
    ToolStatus,
)

__all__ = [
    "get_config",
    "logger",
    "MCPMessage",
    "MessageType",
    "ToolCategory",
    "ToolSchema",
    "ToolInfo",
    "ToolResult",
    "ToolStatus",
    "ServerInfo",
    "ClientInfo",
]
