# MCP 工具集成框架

基于 MCP（Model Context Protocol）协议的工具集成框架，提供标准化的工具注册、发现、调用和远程通信能力。

## 特性

- **MCP 协议完整实现**：基于 JSON-RPC 2.0 的消息层，支持请求、响应、通知、错误四种消息类型
- **多种传输方式**：进程内直连（InProcess）、SSE（Server-Sent Events）、WebSocket 三种传输层
- **工具标准化**：统一的工具基类、Schema 定义、参数校验、调用统计
- **动态工具注册**：支持运行时注册/注销工具，支持远程元信息注册
- **6 个内置工具**：Echo、Calculator（AST 安全计算）、TextProcessor、Time、JsonFormatter、RandomGenerator
- **异步架构**：基于 asyncio 的高性能异步设计，支持并发工具调用
- **错误分层处理**：区分业务错误（ToolError）与系统错误，业务错误不阻塞工具可用性

## 项目结构

```
mcp-tool-framework/
├── app/
│   ├── protocol/                # MCP 协议层
│   │   ├── message.py           # 消息序列化/反序列化、标准方法与错误码
│   │   ├── transport.py         # 传输层（InProcess/SSE/WebSocket）
│   │   └── server.py            # MCP 服务器与消息分发
│   ├── tools/                   # 工具层
│   │   ├── base.py              # 工具抽象基类
│   │   ├── registry.py          # 工具注册中心
│   │   └── builtin.py           # 6 个内置工具
│   ├── client/                  # MCP 客户端
│   │   └── __init__.py          # 请求-响应匹配、高层 API
│   ├── config.py                # 单例配置管理
│   ├── logger.py                # 日志模块
│   └── models.py                # Pydantic 数据模型
├── config/
│   └── config.example.toml      # 示例配置
├── run.py                       # 主入口（演示脚本）
├── requirements.txt
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config/config.example.toml config/config.toml
```

### 3. 运行演示

```bash
python run.py
```

演示包含两个场景：
- **进程内通信演示**：完整的 MCP 协议链路，包括 ping、工具列表、工具调用、错误处理、统计信息
- **远程工具注册演示**：通过 MCP 协议远程注册和注销工具

## 内置工具

| 工具 | 分类 | 描述 |
|------|------|------|
| `echo` | system | 回显输入内容，用于测试协议链路 |
| `calculator` | data | 数学表达式计算（AST 安全解析） |
| `text_processor` | data | 文本统计与变换（字符数、词数、大小写） |
| `time` | system | 获取当前时间，支持多格式与时区 |
| `json_formatter` | code | JSON 格式化、压缩、校验 |
| `random_generator` | data | 随机数、随机字符串、UUID 生成 |

## 架构设计

### 分层架构

```
应用层    run.py / 示例脚本
  ↓
客户端层  MCPClient（请求-响应匹配、高层 API）
  ↓
协议层    MCPServer（消息分发）+ MessageSerializer（序列化）
  ↓
传输层    InProcessTransport / SSETransport / WebSocketTransport
  ↓
工具层    ToolRegistry（注册中心）+ ToolBase（基类）+ 内置工具
  ↓
基础设施  Config（单例配置）+ Logger + Models（Pydantic）
```

### MCP 协议消息格式

```json
{
    "jsonrpc": "2.0",
    "id": "uuid",
    "method": "tools/call",
    "params": {"name": "calculator", "arguments": {"expression": "1+2"}}
}
```

### 标准 MCP 方法

| 方法 | 描述 |
|------|------|
| `tools/list` | 列出所有已注册工具 |
| `tools/call` | 调用指定工具 |
| `tools/register` | 远程注册工具（仅元信息） |
| `tools/unregister` | 注销工具 |
| `server/info` | 获取服务器信息 |
| `server/ping` | 心跳检测 |
| `server/shutdown` | 关闭服务器 |

## 自定义工具

继承 `ToolBase` 并实现 `execute` 方法：

```python
from app.tools import ToolBase
from app.models import ToolCategory

class MyTool(ToolBase):
    name = "my_tool"
    description = "我的自定义工具"
    category = ToolCategory.CUSTOM
    parameters_schema = {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }

    async def execute(self, params):
        return {"result": params["input"].upper()}

# 注册到注册中心
registry.register(MyTool())
```

## 技术栈

- Python 3.11+
- Pydantic V2（数据模型与校验）
- aiohttp（SSE/WebSocket 传输）
- asyncio（异步并发）

## License

MIT
