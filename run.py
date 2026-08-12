"""MCP工具集成框架 - 主入口

演示完整的 MCP 协议链路：
1. 创建 InProcessTransport（无需网络）
2. 启动 MCP 服务器并注册内置工具
3. 启动 MCP 客户端
4. 通过客户端调用服务器上的工具
"""
import asyncio

from app.client import MCPClient
from app.protocol import InProcessTransport, MCPServer
from app.tools import ToolRegistry, register_builtin_tools


async def demo_inprocess():
    """演示进程内 MCP 通信"""
    print("=" * 60)
    print("MCP工具集成框架 - 进程内通信演示")
    print("=" * 60)

    # 创建进程内传输层
    transport = InProcessTransport()
    server_transport = transport.server_side()
    client_transport = transport.client_side()

    # 创建工具注册中心并注册内置工具
    registry = ToolRegistry(default_timeout=10.0)
    register_builtin_tools(registry)
    print(f"\n[初始化] 已注册 {len(registry.list_tools())} 个内置工具:")
    for info in registry.list_tools():
        print(
            f"  - {info.name} ({info.tool_schema.category.value}): "
            f"{info.tool_schema.description}"
        )

    # 创建并启动服务器
    server = MCPServer(transport=server_transport, name="demo-server", version="1.0.0")
    server.set_tool_registry(registry)
    await server.start()

    # 创建并启动客户端
    client = MCPClient(transport=client_transport, name="demo-client", version="1.0.0")
    await client.start()

    try:
        # 1. Ping
        print("\n[1] Ping 服务器")
        ping_result = await client.ping()
        print(f"  响应: {ping_result}")

        # 2. 获取服务器信息
        print("\n[2] 获取服务器信息")
        info = await client.server_info()
        print(f"  服务器名: {info.get('name')}")
        print(f"  版本: {info.get('version')}")
        print(f"  状态: {info.get('status')}")
        print(f"  工具数: {len(info.get('tools', []))}")

        # 3. 列出所有工具
        print("\n[3] 列出所有工具")
        tools = await client.list_tools()
        for t in tools:
            print(f"  - {t['name']}: {t['description']}")

        # 4. 调用 Echo 工具
        print("\n[4] 调用 echo 工具")
        result = await client.call_tool("echo", {"message": "Hello MCP!", "uppercase": True})
        print(f"  结果: {result.get('output')}")
        print(f"  耗时: {result.get('execution_time'):.4f}s")

        # 5. 调用 Calculator 工具
        print("\n[5] 调用 calculator 工具")
        expressions = ["1 + 2", "(3 + 4) * 5", "2 ** 10", "100 / 4", "17 % 5"]
        for expr in expressions:
            result = await client.call_tool(
                "calculator", {"expression": expr}
            )
            output = result.get("output", {})
            print(f"  {expr} = {output.get('result')}")

        # 6. 调用 TextProcessor 工具
        print("\n[6] 调用 text_processor 工具")
        result = await client.call_tool(
            "text_processor",
            {"text": "Hello World MCP Framework", "operation": "stats"},
        )
        print(f"  统计: {result.get('output', {}).get('stats')}")

        result = await client.call_tool(
            "text_processor",
            {"text": "hello world", "operation": "upper"},
        )
        print(f"  大写: {result.get('output', {}).get('result')}")

        # 7. 调用 Time 工具
        print("\n[7] 调用 time 工具")
        result = await client.call_tool(
            "time", {"format": "datetime", "timezone_offset": 8}
        )
        print(f"  当前时间(UTC+8): {result.get('output', {}).get('time')}")

        # 8. 调用 JsonFormatter 工具
        print("\n[8] 调用 json_formatter 工具")
        json_str = '{"name":"MCP","version":"1.0","tools":["echo","calc"]}'
        result = await client.call_tool(
            "json_formatter",
            {"json_string": json_str, "operation": "pretty", "indent": 2},
        )
        print(f"  格式化后:")
        for line in result.get("output", {}).get("result", "").split("\n"):
            print(f"    {line}")

        # 9. 调用 RandomGenerator 工具
        print("\n[9] 调用 random_generator 工具")
        result = await client.call_tool(
            "random_generator", {"type": "int", "min": 1, "max": 100}
        )
        print(f"  随机整数: {result.get('output', {}).get('value')}")

        result = await client.call_tool(
            "random_generator", {"type": "string", "length": 12}
        )
        print(f"  随机字符串: {result.get('output', {}).get('value')}")

        result = await client.call_tool(
            "random_generator", {"type": "uuid"}
        )
        print(f"  UUID: {result.get('output', {}).get('value')}")

        # 10. 测试错误处理
        print("\n[10] 测试错误处理")
        try:
            await client.call_tool("nonexistent_tool", {})
        except Exception as e:
            print(f"  调用不存在工具: {type(e).__name__}: {e}")

        try:
            await client.call_tool("calculator", {"expression": "1/0"})
        except Exception as e:
            print(f"  除零错误: {type(e).__name__}: {e}")

        try:
            await client.call_tool("calculator", {"expression": "import os"})
        except Exception as e:
            print(f"  非法表达式: {type(e).__name__}: {e}")

        # 11. 按分类查询工具
        print("\n[11] 按分类查询工具")
        data_tools = await client.list_tools(category="data")
        print(f"  data 类工具: {[t['name'] for t in data_tools]}")
        system_tools = await client.list_tools(category="system")
        print(f"  system 类工具: {[t['name'] for t in system_tools]}")

        # 12. 工具统计
        print("\n[12] 工具统计")
        stats = registry.get_stats()
        print(f"  总工具数: {stats['total_tools']}")
        print(f"  总调用次数: {stats['total_calls']}")
        print(f"  总错误次数: {stats['total_errors']}")
        print(f"  整体成功率: {stats['overall_success_rate']:.2%}")

        # 显示每个工具的调用次数
        print("\n  各工具调用统计:")
        for info in registry.list_tools():
            print(
                f"    {info.name}: 调用 {info.call_count} 次, "
                f"成功率 {info.success_rate:.2%}"
            )

    finally:
        await client.stop()
        await server.stop()

    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)


async def demo_remote_register():
    """演示远程工具注册（仅元信息）"""
    print("\n" + "=" * 60)
    print("MCP工具集成框架 - 远程工具注册演示")
    print("=" * 60)

    transport = InProcessTransport()
    registry = ToolRegistry()
    register_builtin_tools(registry)

    server = MCPServer(transport=transport.server_side(), name="registry-demo")
    server.set_tool_registry(registry)
    await server.start()

    client = MCPClient(transport=transport.client_side(), name="reg-client")
    await client.start()

    try:
        print("\n[1] 注册前工具列表:")
        tools = await client.list_tools()
        print(f"  工具数: {len(tools)}")

        print("\n[2] 远程注册新工具（仅元信息）:")
        reg_result = await client.register_tool(
            {
                "name": "custom_search",
                "description": "自定义搜索引擎",
                "category": "search",
                "version": "0.1.0",
                "tags": ["search", "custom"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            }
        )
        print(f"  注册结果: {reg_result}")

        print("\n[3] 注册后工具列表:")
        tools = await client.list_tools()
        print(f"  工具数: {len(tools)}")
        for t in tools:
            status = t.get("status", "?")
            print(f"  - {t['name']} [{status}]")

        print("\n[4] 注销工具:")
        unreg_result = await client.unregister_tool("custom_search")
        print(f"  注销结果: {unreg_result}")

        print("\n[5] 注销后工具列表:")
        tools = await client.list_tools()
        print(f"  工具数: {len(tools)}")

    finally:
        await client.stop()
        await server.stop()


async def main():
    await demo_inprocess()
    await demo_remote_register()


if __name__ == "__main__":
    asyncio.run(main())
