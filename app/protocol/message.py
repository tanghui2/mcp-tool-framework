"""MCP协议消息定义 - 基于JSON-RPC 2.0

MCP (Model Context Protocol) 消息格式：
- 请求：{jsonrpc, id, method, params}
- 响应：{jsonrpc, id, result}
- 错误：{jsonrpc, id, error: {code, message, data}}
- 通知：{jsonrpc, method, params}（无id，不需要响应）
"""
import json
from typing import Any, Dict, Optional

from ..models import MCPMessage, MessageType


class MessageSerializer:
    """消息序列化/反序列化"""

    @staticmethod
    def serialize(message: MCPMessage) -> str:
        """序列化为JSON字符串"""
        data: Dict[str, Any] = {"jsonrpc": message.jsonrpc}

        if message.id is not None:
            data["id"] = message.id

        if message.method:
            data["method"] = message.method

        if message.params:
            data["params"] = message.params

        if message.result is not None:
            data["result"] = message.result

        if message.error is not None:
            data["error"] = message.error

        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def deserialize(data: str) -> MCPMessage:
        """从JSON字符串反序列化"""
        raw = json.loads(data)

        # 判断消息类型
        if "error" in raw:
            msg_type = MessageType.ERROR
        elif "result" in raw:
            msg_type = MessageType.RESPONSE
        elif "id" not in raw and "method" in raw:
            msg_type = MessageType.NOTIFICATION
        else:
            msg_type = MessageType.REQUEST

        return MCPMessage(
            jsonrpc=raw.get("jsonrpc", "2.0"),
            id=raw.get("id"),
            method=raw.get("method"),
            params=raw.get("params", {}),
            result=raw.get("result"),
            error=raw.get("error"),
            message_type=msg_type,
        )


# MCP标准方法定义
class MCPMethods:
    """MCP标准方法名"""

    # 工具相关
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    TOOLS_REGISTER = "tools/register"
    TOOLS_UNREGISTER = "tools/unregister"

    # 服务器相关
    SERVER_INFO = "server/info"
    SERVER_PING = "server/ping"
    SERVER_SHUTDOWN = "server/shutdown"

    # 客户端相关
    CLIENT_CONNECT = "client/connect"
    CLIENT_DISCONNECT = "client/disconnect"

    # 资源相关
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"

    # 提示相关
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"


# MCP标准错误码
class MCPErrorCodes:
    """MCP标准错误码"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    TOOL_NOT_FOUND = -32001
    TOOL_EXECUTION_ERROR = -32002
    SERVER_ERROR = -32003
    AUTHENTICATION_ERROR = -32004
