"""数据模型 - MCP协议数据结构"""
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """MCP消息类型"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    ERROR = "error"


class ToolCategory(str, Enum):
    """工具分类"""
    SEARCH = "search"
    FILE = "file"
    CODE = "code"
    WEB = "web"
    DATA = "data"
    SYSTEM = "system"
    CUSTOM = "custom"


class ToolStatus(str, Enum):
    """工具状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class MCPMessage(BaseModel):
    """MCP协议消息 - 基于JSON-RPC 2.0"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC版本")
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), description="消息ID")
    method: Optional[str] = Field(default=None, description="方法名")
    params: Dict[str, Any] = Field(default_factory=dict, description="参数")
    result: Optional[Any] = Field(default=None, description="结果")
    error: Optional[Dict[str, Any]] = Field(default=None, description="错误信息")
    message_type: MessageType = Field(default=MessageType.REQUEST, description="消息类型")
    timestamp: float = Field(default_factory=time.time, description="时间戳")

    def is_request(self) -> bool:
        return self.message_type == MessageType.REQUEST

    def is_response(self) -> bool:
        return self.message_type == MessageType.RESPONSE

    def is_error(self) -> bool:
        return self.message_type == MessageType.ERROR or self.error is not None

    @classmethod
    def create_request(cls, method: str, params: Optional[Dict] = None) -> "MCPMessage":
        """创建请求消息"""
        return cls(
            method=method,
            params=params or {},
            message_type=MessageType.REQUEST,
        )

    @classmethod
    def create_response(cls, request_id: str, result: Any) -> "MCPMessage":
        """创建响应消息"""
        return cls(
            id=request_id,
            result=result,
            message_type=MessageType.RESPONSE,
        )

    @classmethod
    def create_error(cls, request_id: str, code: int, message: str, data: Optional[Any] = None) -> "MCPMessage":
        """创建错误消息"""
        error_data = {"code": code, "message": message}
        if data is not None:
            error_data["data"] = data
        return cls(
            id=request_id,
            error=error_data,
            message_type=MessageType.ERROR,
        )

    @classmethod
    def create_notification(cls, method: str, params: Optional[Dict] = None) -> "MCPMessage":
        """创建通知消息（不需要响应）"""
        return cls(
            id=None,
            method=method,
            params=params or {},
            message_type=MessageType.NOTIFICATION,
        )


class ToolSchema(BaseModel):
    """工具Schema定义"""
    name: str = Field(..., description="工具名称")
    description: str = Field(default="", description="工具描述")
    category: ToolCategory = Field(default=ToolCategory.CUSTOM, description="工具分类")
    version: str = Field(default="1.0.0", description="版本号")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="参数Schema")
    returns: Dict[str, Any] = Field(default_factory=dict, description="返回值Schema")
    tags: List[str] = Field(default_factory=list, description="标签")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class ToolInfo(BaseModel):
    """工具信息"""
    tool_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="工具名称")
    tool_schema: ToolSchema = Field(..., description="工具Schema")
    status: ToolStatus = Field(default=ToolStatus.ACTIVE, description="工具状态")
    registered_at: float = Field(default_factory=time.time, description="注册时间")
    last_called: Optional[float] = Field(default=None, description="最后调用时间")
    call_count: int = Field(default=0, description="调用次数")
    error_count: int = Field(default=0, description="错误次数")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.call_count == 0:
            return 1.0
        return (self.call_count - self.error_count) / self.call_count


class ToolResult(BaseModel):
    """工具执行结果"""
    tool_id: str = Field(..., description="工具ID")
    tool_name: str = Field(..., description="工具名称")
    success: bool = Field(..., description="是否成功")
    output: Any = Field(default=None, description="输出结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time: float = Field(default=0.0, description="执行时间（秒）")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    timestamp: float = Field(default_factory=time.time, description="时间戳")


class ServerInfo(BaseModel):
    """服务器信息"""
    server_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="服务器名称")
    version: str = Field(default="1.0.0", description="版本号")
    host: str = Field(default="localhost", description="主机地址")
    port: int = Field(default=8080, description="端口")
    transport: str = Field(default="sse", description="传输协议（sse/websocket）")
    tools: List[str] = Field(default_factory=list, description="已注册工具列表")
    status: str = Field(default="stopped", description="服务器状态")
    started_at: Optional[float] = Field(default=None, description="启动时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class ClientInfo(BaseModel):
    """客户端信息"""
    client_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="客户端名称")
    version: str = Field(default="1.0.0", description="版本号")
    connected: bool = Field(default=False, description="是否已连接")
    connected_at: Optional[float] = Field(default=None, description="连接时间")
    server_url: Optional[str] = Field(default=None, description="服务器地址")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
