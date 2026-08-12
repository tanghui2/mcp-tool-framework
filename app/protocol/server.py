"""MCP 服务器 - 协议处理与消息分发

核心职责：
- 接收传输层消息并分发到对应的处理器
- 提供标准 MCP 方法实现（tools/list, tools/call, server/info 等）
- 与 ToolRegistry 集成，实现工具的注册、查询、调用
- 生命周期管理（启动/停止）
"""
import asyncio
import time
from typing import Any, Callable, Coroutine, Dict, Optional

from ..logger import logger
from ..models import (
    MCPMessage,
    MessageType,
    ServerInfo,
)
from ..tools.base import ToolError
from ..tools.registry import ToolNotFoundError
from .message import MCPErrorCodes, MCPMethods, MessageSerializer
from .transport import InProcessTransport, TransportBase


# 处理器类型：接收 MCPMessage，返回任意结果（成功）或抛出异常
MessageHandler = Callable[[MCPMessage], Coroutine[Any, Any, Any]]


class MCPServer:
    """MCP 服务器

    使用方式：
        server = MCPServer(transport=InProcessTransport().server_side())
        server.set_tool_registry(registry)
        await server.start()
        # ...
        await server.stop()
    """

    def __init__(
        self,
        transport: Optional[TransportBase] = None,
        name: str = "mcp-server",
        version: str = "1.0.0",
    ):
        self.transport = transport or InProcessTransport().server_side()
        self.name = name
        self.version = version
        self._handlers: Dict[str, MessageHandler] = {}
        self._tool_registry: Optional[Any] = None  # 延迟注入，避免循环依赖
        self._info: Optional[ServerInfo] = None
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._register_default_handlers()

    def set_tool_registry(self, registry: Any) -> None:
        """注入工具注册中心"""
        self._tool_registry = registry
        # 更新服务器信息中的工具列表
        if self._info is not None:
            self._info.tools = [t.name for t in registry.list_tools()]

    def register_handler(self, method: str, handler: MessageHandler) -> None:
        """注册方法处理器"""
        self._handlers[method] = handler
        logger.debug(f"已注册方法处理器: {method}")

    def _register_default_handlers(self) -> None:
        """注册默认的 MCP 标准方法处理器"""
        self.register_handler(MCPMethods.SERVER_PING, self._handle_ping)
        self.register_handler(MCPMethods.SERVER_INFO, self._handle_server_info)
        self.register_handler(MCPMethods.SERVER_SHUTDOWN, self._handle_shutdown)
        self.register_handler(MCPMethods.TOOLS_LIST, self._handle_tools_list)
        self.register_handler(MCPMethods.TOOLS_CALL, self._handle_tools_call)
        self.register_handler(MCPMethods.TOOLS_REGISTER, self._handle_tools_register)
        self.register_handler(
            MCPMethods.TOOLS_UNREGISTER, self._handle_tools_unregister
        )

    async def start(self) -> None:
        """启动服务器"""
        if self._running:
            logger.warning("服务器已经在运行")
            return

        # 构建服务器信息
        self._info = ServerInfo(
            name=self.name,
            version=self.version,
            tools=[t.name for t in self._tool_registry.list_tools()]
            if self._tool_registry
            else [],
            status="running",
            started_at=time.time(),
        )

        await self.transport.start()
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info(f"MCP 服务器已启动: {self.name} v{self.version}")

    async def stop(self) -> None:
        """停止服务器"""
        if not self._running:
            return
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        await self.transport.stop()
        if self._info:
            self._info.status = "stopped"
        logger.info("MCP 服务器已停止")

    async def _dispatch_loop(self) -> None:
        """消息分发主循环"""
        try:
            async for message in self.transport.receive():
                if not self._running:
                    break
                # 异步处理每条消息，避免阻塞接收
                asyncio.create_task(self._process_message(message))
        except asyncio.CancelledError:
            logger.debug("分发循环被取消")
            raise
        except Exception as e:
            logger.error(f"分发循环异常: {e}")

    async def _process_message(self, message: MCPMessage) -> None:
        """处理单条消息"""
        try:
            # 通知消息不需要响应
            if message.message_type == MessageType.NOTIFICATION:
                handler = self._handlers.get(message.method or "")
                if handler:
                    try:
                        await handler(message)
                    except Exception as e:
                        logger.error(
                            f"通知处理器异常: method={message.method}, error={e}"
                        )
                else:
                    logger.debug(f"未注册的通知: {message.method}")
                return

            # 请求消息
            handler = self._handlers.get(message.method or "")
            if handler is None:
                error_msg = MCPMessage.create_error(
                    request_id=message.id or "",
                    code=MCPErrorCodes.METHOD_NOT_FOUND,
                    message=f"未找到方法: {message.method}",
                )
                await self.transport.send(error_msg)
                return

            try:
                result = await handler(message)
                response = MCPMessage.create_response(
                    request_id=message.id or "", result=result
                )
                await self.transport.send(response)
            except ValueError as e:
                # 参数错误
                error_msg = MCPMessage.create_error(
                    request_id=message.id or "",
                    code=MCPErrorCodes.INVALID_PARAMS,
                    message=str(e),
                )
                await self.transport.send(error_msg)
            except ToolNotFoundError as e:
                # 工具未找到
                error_msg = MCPMessage.create_error(
                    request_id=message.id or "",
                    code=MCPErrorCodes.TOOL_NOT_FOUND,
                    message=str(e),
                )
                await self.transport.send(error_msg)
            except ToolError as e:
                # 工具执行错误（业务错误）
                error_msg = MCPMessage.create_error(
                    request_id=message.id or "",
                    code=MCPErrorCodes.TOOL_EXECUTION_ERROR,
                    message=str(e),
                )
                await self.transport.send(error_msg)
            except Exception as e:
                logger.error(
                    f"处理器执行异常: method={message.method}, error={e}",
                    exc_info=True,
                )
                error_msg = MCPMessage.create_error(
                    request_id=message.id or "",
                    code=MCPErrorCodes.INTERNAL_ERROR,
                    message=f"内部错误: {e}",
                )
                await self.transport.send(error_msg)
        except Exception as e:
            logger.error(f"消息处理失败: {e}", exc_info=True)

    # ===== 默认方法处理器 =====

    async def _handle_ping(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 ping 请求"""
        return {"status": "ok", "timestamp": time.time()}

    async def _handle_server_info(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 server/info 请求"""
        if self._info is None:
            return {"status": "not_started"}
        if self._tool_registry is not None:
            self._info.tools = [t.name for t in self._tool_registry.list_tools()]
        return self._info.model_dump()

    async def _handle_shutdown(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 server/shutdown 请求"""
        asyncio.create_task(self.stop())
        return {"status": "shutting_down"}

    async def _handle_tools_list(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 tools/list 请求"""
        if self._tool_registry is None:
            return {"tools": []}
        category = message.params.get("category")
        tools = self._tool_registry.list_tools(category=category)
        return {
            "tools": [
                {
                    "tool_id": t.tool_id,
                    "name": t.name,
                    "description": t.tool_schema.description,
                    "category": t.tool_schema.category.value,
                    "version": t.tool_schema.version,
                    "parameters": t.tool_schema.parameters,
                    "returns": t.tool_schema.returns,
                    "tags": t.tool_schema.tags,
                    "status": t.status.value,
                    "call_count": t.call_count,
                    "success_rate": t.success_rate,
                }
                for t in tools
            ]
        }

    async def _handle_tools_call(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 tools/call 请求"""
        if self._tool_registry is None:
            raise RuntimeError("工具注册中心未初始化")

        tool_name = message.params.get("name")
        if not tool_name:
            raise ValueError("缺少参数: name")

        arguments = message.params.get("arguments", {})
        result = await self._tool_registry.execute_tool(tool_name, arguments)
        return {
            "tool_id": result.tool_id,
            "tool_name": result.tool_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "execution_time": result.execution_time,
            "timestamp": result.timestamp,
        }

    async def _handle_tools_register(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 tools/register 请求"""
        if self._tool_registry is None:
            raise RuntimeError("工具注册中心未初始化")

        tool_data = message.params.get("tool")
        if not tool_data:
            raise ValueError("缺少参数: tool")

        tool = self._tool_registry.register_tool_dict(tool_data)
        return {"tool_id": tool.tool_id, "name": tool.name, "status": "registered"}

    async def _handle_tools_unregister(self, message: MCPMessage) -> Dict[str, Any]:
        """处理 tools/unregister 请求"""
        if self._tool_registry is None:
            raise RuntimeError("工具注册中心未初始化")

        tool_name = message.params.get("name")
        if not tool_name:
            raise ValueError("缺少参数: name")

        success = self._tool_registry.unregister_tool(tool_name)
        return {"name": tool_name, "unregistered": success}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def server_info(self) -> Optional[ServerInfo]:
        return self._info
