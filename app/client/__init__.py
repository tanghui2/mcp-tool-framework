"""MCP 客户端 - 与 MCP 服务器通信的客户端

核心职责：
- 通过传输层连接到 MCP 服务器
- 提供高层 API：list_tools / call_tool / ping / server_info
- 自动匹配请求-响应（基于消息 ID）
- 支持超时与错误处理
"""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from ..logger import logger
from ..models import ClientInfo, MCPMessage, MessageType
from ..protocol.message import MCPErrorCodes, MCPMethods
from ..protocol.transport import InProcessTransport, TransportBase


class MCPClientError(Exception):
    """MCP 客户端异常"""

    pass


class MCPClient:
    """MCP 客户端

    使用方式：
        transport = InProcessTransport().client_side()
        client = MCPClient(transport=transport, name="my-client")
        await client.start()
        info = await client.server_info()
        tools = await client.list_tools()
        result = await client.call_tool("calculator", {"expression": "1+2"})
        await client.stop()
    """

    def __init__(
        self,
        transport: Optional[TransportBase] = None,
        name: str = "mcp-client",
        version: str = "1.0.0",
        request_timeout: float = 30.0,
    ):
        self.transport = transport or InProcessTransport().client_side()
        self.name = name
        self.version = version
        self.request_timeout = request_timeout
        self._info = ClientInfo(name=name, version=version)
        self._running = False
        self._reader_task: Optional[asyncio.Task] = None
        # 等待响应的 Future 字典：request_id -> Future
        self._pending: Dict[str, asyncio.Future] = {}
        # 通知处理器
        self._notification_handlers: Dict[str, Any] = {}

    def on_notification(self, method: str, handler) -> None:
        """注册通知处理器"""
        self._notification_handlers[method] = handler

    async def start(self) -> None:
        """启动客户端"""
        if self._running:
            return
        await self.transport.start()
        self._running = True
        self._info.connected = True
        self._info.connected_at = time.time()
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info(f"MCP 客户端已启动: {self.name} v{self.version}")

    async def stop(self) -> None:
        """停止客户端"""
        if not self._running:
            return
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        await self.transport.stop()
        self._info.connected = False
        # 取消所有未完成的请求
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("MCP 客户端已停止")

    async def _read_loop(self) -> None:
        """读取响应循环"""
        try:
            async for message in self.transport.receive():
                if not self._running:
                    break
                await self._handle_message(message)
        except asyncio.CancelledError:
            logger.debug("客户端读取循环被取消")
            raise
        except Exception as e:
            logger.error(f"客户端读取循环异常: {e}")

    async def _handle_message(self, message: MCPMessage) -> None:
        """处理来自服务器的消息"""
        if message.message_type == MessageType.NOTIFICATION:
            handler = self._notification_handlers.get(message.method or "")
            if handler:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"通知处理器异常: method={message.method}, error={e}")
            else:
                logger.debug(f"收到未处理的通知: {message.method}")
            return

        # 响应或错误消息：匹配到对应的 Future
        request_id = message.id
        if request_id is None:
            logger.warning("收到无 ID 的响应消息，丢弃")
            return

        fut = self._pending.pop(request_id, None)
        if fut is None or fut.done():
            logger.debug(f"未找到对应的请求或请求已完成: id={request_id}")
            return

        if message.message_type == MessageType.ERROR or message.error is not None:
            err = message.error or {}
            fut.set_exception(
                MCPClientError(
                    f"服务器错误: code={err.get('code')}, message={err.get('message')}"
                )
            )
        else:
            fut.set_result(message.result)

    async def _request(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """发送请求并等待响应"""
        if not self._running:
            raise MCPClientError("客户端未启动")

        request_id = str(uuid.uuid4())
        message = MCPMessage(
            id=request_id,
            method=method,
            params=params or {},
            message_type=MessageType.REQUEST,
        )

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        try:
            await self.transport.send(message)
            result = await asyncio.wait_for(fut, timeout=self.request_timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise MCPClientError(f"请求超时: method={method}, id={request_id}")
        except Exception as e:
            self._pending.pop(request_id, None)
            if isinstance(e, MCPClientError):
                raise
            raise MCPClientError(f"请求失败: {e}") from e

    async def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """发送通知（不需要响应）"""
        if not self._running:
            raise MCPClientError("客户端未启动")
        message = MCPMessage.create_notification(method=method, params=params)
        await self.transport.send(message)

    # ===== 高层 API =====

    async def ping(self) -> Dict[str, Any]:
        """Ping 服务器"""
        return await self._request(MCPMethods.SERVER_PING, {})

    async def server_info(self) -> Dict[str, Any]:
        """获取服务器信息"""
        return await self._request(MCPMethods.SERVER_INFO, {})

    async def list_tools(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出服务器上的工具"""
        params = {}
        if category:
            params["category"] = category
        result = await self._request(MCPMethods.TOOLS_LIST, params)
        return result.get("tools", [])

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """调用工具"""
        params = {"name": name, "arguments": arguments or {}}
        return await self._request(MCPMethods.TOOLS_CALL, params)

    async def register_tool(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """远程注册工具"""
        return await self._request(MCPMethods.TOOLS_REGISTER, {"tool": tool_data})

    async def unregister_tool(self, name: str) -> Dict[str, Any]:
        """注销工具"""
        return await self._request(MCPMethods.TOOLS_UNREGISTER, {"name": name})

    async def shutdown_server(self) -> Dict[str, Any]:
        """请求服务器关闭"""
        return await self._request(MCPMethods.SERVER_SHUTDOWN, {})

    @property
    def is_connected(self) -> bool:
        return self._running and self._info.connected

    @property
    def info(self) -> ClientInfo:
        return self._info
