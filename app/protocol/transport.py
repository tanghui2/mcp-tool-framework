"""MCP传输层 - 支持 SSE / WebSocket / InProcess 三种传输方式

设计要点：
- TransportBase: 抽象基类，定义统一的发送/接收接口
- InProcessTransport: 进程内直连，用于测试和单进程场景
- SSETransport: 基于 aiohttp 的 Server-Sent Events 传输
- WebSocketTransport: 基于 aiohttp 的 WebSocket 传输
"""
import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional

from ..logger import logger
from ..models import MCPMessage
from .message import MessageSerializer


class TransportBase(ABC):
    """传输层抽象基类"""

    @abstractmethod
    async def start(self) -> None:
        """启动传输层"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止传输层"""
        ...

    @abstractmethod
    async def send(self, message: MCPMessage) -> None:
        """发送消息"""
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[MCPMessage]:
        """接收消息流"""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """是否已连接"""
        ...


class InProcessTransport:
    """进程内传输对 - 使用 asyncio.Queue 实现消息直连

    用于测试和单进程场景，无需网络通信。
    本类是一个"传输对"工厂，通过 server_side() / client_side()
    返回真正的 TransportBase 实现。

    内部维护两条队列：
    - 服务器侧接收队列：客户端 send 时写入
    - 客户端侧接收队列：服务器 send 时写入
    """

    def __init__(self):
        # 服务器读取队列（客户端写入）
        self._server_inbox: "asyncio.Queue[MCPMessage]" = asyncio.Queue()
        # 客户端读取队列（服务器写入）
        self._client_inbox: "asyncio.Queue[MCPMessage]" = asyncio.Queue()
        self._server_started = False
        self._client_started = False

    # 服务器侧接口
    def server_side(self) -> "InProcessTransport.ServerSide":
        return InProcessTransport.ServerSide(self)

    # 客户端侧接口
    def client_side(self) -> "InProcessTransport.ClientSide":
        return InProcessTransport.ClientSide(self)

    class ServerSide(TransportBase):
        """服务器侧句柄"""

        def __init__(self, owner: "InProcessTransport"):
            self._owner = owner

        async def start(self) -> None:
            self._owner._server_started = True
            logger.info("InProcessTransport 服务器侧已启动")

        async def stop(self) -> None:
            self._owner._server_started = False
            logger.info("InProcessTransport 服务器侧已停止")

        async def send(self, message: MCPMessage) -> None:
            await self._owner._client_inbox.put(message)

        async def receive(self) -> AsyncIterator[MCPMessage]:
            while self._owner._server_started:
                try:
                    msg = await asyncio.wait_for(
                        self._owner._server_inbox.get(), timeout=0.5
                    )
                    yield msg
                except asyncio.TimeoutError:
                    continue

        async def is_connected(self) -> bool:
            return self._owner._server_started

    class ClientSide(TransportBase):
        """客户端侧句柄"""

        def __init__(self, owner: "InProcessTransport"):
            self._owner = owner

        async def start(self) -> None:
            self._owner._client_started = True
            logger.info("InProcessTransport 客户端侧已启动")

        async def stop(self) -> None:
            self._owner._client_started = False
            logger.info("InProcessTransport 客户端侧已停止")

        async def send(self, message: MCPMessage) -> None:
            await self._owner._server_inbox.put(message)

        async def receive(self) -> AsyncIterator[MCPMessage]:
            while self._owner._client_started:
                try:
                    msg = await asyncio.wait_for(
                        self._owner._client_inbox.get(), timeout=0.5
                    )
                    yield msg
                except asyncio.TimeoutError:
                    continue

        async def is_connected(self) -> bool:
            return self._owner._client_started


class SSETransport(TransportBase):
    """SSE 传输层 - 基于 aiohttp

    使用场景：
    - 服务器侧：aiohttp.web.Application 提供 /sse 端点
    - 客户端侧：通过 aiohttp 连接到 SSE 端点

    单向通信：服务器 -> 客户端
    客户端 -> 服务器的请求通过普通 HTTP POST
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        endpoint: str = "/sse",
        is_server: bool = True,
    ):
        self.host = host
        self.port = port
        self.endpoint = endpoint
        self.is_server = is_server
        self._app: Optional[Any] = None
        self._runner: Optional[Any] = None
        self._site: Optional[Any] = None
        self._session: Optional[Any] = None
        self._response: Optional[Any] = None
        self._client_queue: "asyncio.Queue[MCPMessage]" = asyncio.Queue()
        self._connected = False

    async def start(self) -> None:
        if self.is_server:
            await self._start_server()
        else:
            await self._start_client()

    async def _start_server(self) -> None:
        """启动 SSE 服务器"""
        from aiohttp import web

        async def sse_handler(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
            await response.prepare(request)

            # 注册到服务器，使服务器可以推送消息
            self._server_response = response
            self._connected = True

            try:
                # 保持连接
                while not response.force_close:
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            finally:
                self._connected = False
            return response

        async def message_handler(request: web.Request) -> web.Response:
            """接收客户端发来的消息"""
            data = await request.text()
            try:
                msg = MessageSerializer.deserialize(data)
                await self._server_inbox.put(msg)
                return web.json_response({"status": "ok"})
            except Exception as e:
                logger.error(f"SSE 服务器消息解析失败: {e}")
                return web.json_response(
                    {"status": "error", "message": str(e)}, status=400
                )

        self._server_response: Optional[web.StreamResponse] = None
        self._server_inbox: "asyncio.Queue[MCPMessage]" = asyncio.Queue()

        self._app = web.Application()
        self._app.router.add_get(self.endpoint, sse_handler)
        self._app.router.add_post(f"{self.endpoint}/message", message_handler)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        self._connected = True
        logger.info(f"SSE 服务器已启动: http://{self.host}:{self.port}{self.endpoint}")

    async def _start_client(self) -> None:
        """启动 SSE 客户端"""
        import aiohttp

        url = f"http://{self.host}:{self.port}{self.endpoint}"
        self._session = aiohttp.ClientSession()
        self._response = await self._session.get(url)
        self._connected = True
        logger.info(f"SSE 客户端已连接: {url}")

        # 启动后台任务读取 SSE 流
        self._reader_task = asyncio.create_task(self._read_sse_stream())

    async def _read_sse_stream(self) -> None:
        """读取 SSE 流"""
        try:
            async for line in self._response.content:
                line_str = line.decode("utf-8").strip()
                if not line_str or not line_str.startswith("data: "):
                    continue
                data = line_str[6:]
                try:
                    msg = MessageSerializer.deserialize(data)
                    await self._client_queue.put(msg)
                except Exception as e:
                    logger.error(f"SSE 客户端消息解析失败: {e}")
        except Exception as e:
            logger.error(f"SSE 流读取异常: {e}")
        finally:
            self._connected = False

    async def send(self, message: MCPMessage) -> None:
        data = MessageSerializer.serialize(message)
        if self.is_server:
            # 服务器推送消息到 SSE 流
            if hasattr(self, "_server_response") and self._server_response is not None:
                await self._server_response.write(f"data: {data}\n\n".encode("utf-8"))
            else:
                logger.warning("SSE 服务器尚未建立连接，无法发送消息")
        else:
            # 客户端通过 HTTP POST 发送消息
            if self._session is None:
                raise RuntimeError("SSE 客户端尚未启动")
            url = f"http://{self.host}:{self.port}{self.endpoint}/message"
            async with self._session.post(url, data=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"SSE 客户端发送失败: {resp.status} - {text}")

    async def receive(self) -> AsyncIterator[MCPMessage]:
        if self.is_server:
            while self._connected:
                try:
                    msg = await asyncio.wait_for(self._server_inbox.get(), timeout=0.5)
                    yield msg
                except asyncio.TimeoutError:
                    continue
        else:
            while self._connected:
                try:
                    msg = await asyncio.wait_for(self._client_queue.get(), timeout=0.5)
                    yield msg
                except asyncio.TimeoutError:
                    continue

    async def is_connected(self) -> bool:
        return self._connected

    async def stop(self) -> None:
        self._connected = False
        if self.is_server:
            if self._site:
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        else:
            if hasattr(self, "_reader_task"):
                self._reader_task.cancel()
            if self._response:
                self._response.close()
            if self._session:
                await self._session.close()
        logger.info("SSE 传输层已停止")


class WebSocketTransport(TransportBase):
    """WebSocket 传输层 - 基于 aiohttp

    双向通信，比 SSE 更适合频繁交互的场景
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        endpoint: str = "/ws",
        is_server: bool = True,
    ):
        self.host = host
        self.port = port
        self.endpoint = endpoint
        self.is_server = is_server
        self._app: Optional[Any] = None
        self._runner: Optional[Any] = None
        self._site: Optional[Any] = None
        self._session: Optional[Any] = None
        self._ws: Optional[Any] = None
        self._inbox: "asyncio.Queue[MCPMessage]" = asyncio.Queue()
        self._connected = False
        self._reader_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self.is_server:
            await self._start_server()
        else:
            await self._start_client()

    async def _start_server(self) -> None:
        from aiohttp import web

        async def ws_handler(request: web.Request) -> web.WebSocketResponse:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            self._ws = ws
            self._connected = True
            logger.info("WebSocket 服务器收到客户端连接")

            try:
                async for msg in ws:
                    if msg.type == 1:  # aiohttp.WSMsgType.TEXT
                        try:
                            mcp_msg = MessageSerializer.deserialize(msg.data)
                            await self._inbox.put(mcp_msg)
                        except Exception as e:
                            logger.error(f"WebSocket 服务器消息解析失败: {e}")
                    elif msg.type == 2:  # aiohttp.WSMsgType.BINARY
                        logger.debug("WebSocket 收到二进制消息，忽略")
                    elif msg.type == 8:  # aiohttp.WSMsgType.CLOSE
                        break
            finally:
                self._connected = False
            return ws

        self._app = web.Application()
        self._app.router.add_get(self.endpoint, ws_handler)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(
            f"WebSocket 服务器已启动: ws://{self.host}:{self.port}{self.endpoint}"
        )

    async def _start_client(self) -> None:
        import aiohttp

        url = f"ws://{self.host}:{self.port}{self.endpoint}"
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(url)
        self._connected = True
        logger.info(f"WebSocket 客户端已连接: {url}")

        # 后台读取任务
        self._reader_task = asyncio.create_task(self._read_ws())

    async def _read_ws(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type == 1:  # TEXT
                    try:
                        mcp_msg = MessageSerializer.deserialize(msg.data)
                        await self._inbox.put(mcp_msg)
                    except Exception as e:
                        logger.error(f"WebSocket 客户端消息解析失败: {e}")
                elif msg.type == 8:  # CLOSE
                    break
        except Exception as e:
            logger.error(f"WebSocket 读取异常: {e}")
        finally:
            self._connected = False

    async def send(self, message: MCPMessage) -> None:
        if self._ws is None:
            raise RuntimeError("WebSocket 未建立连接")
        data = MessageSerializer.serialize(message)
        await self._ws.send_str(data)

    async def receive(self) -> AsyncIterator[MCPMessage]:
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._inbox.get(), timeout=0.5)
                yield msg
            except asyncio.TimeoutError:
                continue

    async def is_connected(self) -> bool:
        return self._connected

    async def stop(self) -> None:
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        if self.is_server:
            if self._site:
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        logger.info("WebSocket 传输层已停止")


def create_transport(transport_type: str = "inprocess", **kwargs) -> Any:
    """传输层工厂函数

    Args:
        transport_type: 传输类型（inprocess/sse/websocket）
        **kwargs: 传输层参数

    Returns:
        - inprocess: 返回 InProcessTransport 实例（需调用 .server_side() / .client_side()）
        - sse/websocket: 返回 TransportBase 实例
    """
    transport_type = transport_type.lower()
    if transport_type == "inprocess":
        return InProcessTransport()
    elif transport_type == "sse":
        return SSETransport(**kwargs)
    elif transport_type == "websocket":
        return WebSocketTransport(**kwargs)
    else:
        raise ValueError(f"不支持的传输类型: {transport_type}")
