"""工具注册中心 - 工具的注册、查询、执行管理

核心职责：
- 注册/注销工具实例
- 按名称、分类查询工具
- 执行工具并记录调用统计
- 维护工具状态（ACTIVE/INACTIVE/ERROR）
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from ..logger import logger
from ..models import ToolCategory, ToolInfo, ToolResult, ToolSchema, ToolStatus
from .base import ToolBase, ToolError


class ToolNotFoundError(Exception):
    """工具未找到异常"""

    pass


class ToolAlreadyExistsError(ValueError):
    """工具已存在异常"""

    pass


class ToolRegistry:
    """工具注册中心

    使用方式：
        registry = ToolRegistry()
        registry.register(ToolBase子类实例)
        result = await registry.execute_tool("calculator", {"expression": "1+2"})
    """

    def __init__(self, default_timeout: float = 30.0):
        self._tools: Dict[str, ToolBase] = {}
        self._infos: Dict[str, ToolInfo] = {}
        self._default_timeout = default_timeout
        self._lock = asyncio.Lock()

    def register(self, tool: ToolBase) -> ToolInfo:
        """注册工具实例

        Args:
            tool: 工具实例

        Returns:
            工具信息

        Raises:
            ToolAlreadyExistsError: 工具名已存在
        """
        if tool.name in self._tools:
            raise ToolAlreadyExistsError(f"工具已存在: {tool.name}")

        schema = tool.get_schema()
        info = ToolInfo(
            name=tool.name,
            tool_schema=schema,
            status=ToolStatus.ACTIVE,
        )
        self._tools[tool.name] = tool
        self._infos[tool.name] = info
        logger.info(f"工具已注册: {tool.name} (category={schema.category.value})")
        return info

    def register_tool_dict(self, tool_data: Dict[str, Any]) -> ToolInfo:
        """通过字典描述注册工具

        主要用于通过 MCP 协议远程注册（动态加载）
        """
        name = tool_data.get("name")
        if not name:
            raise ValueError("工具名不能为空")

        if name in self._tools:
            raise ToolAlreadyExistsError(f"工具已存在: {name}")

        # 构造一个动态工具实例
        schema = ToolSchema(
            name=name,
            description=tool_data.get("description", ""),
            category=ToolCategory(tool_data.get("category", "custom")),
            version=tool_data.get("version", "1.0.0"),
            parameters=tool_data.get("parameters", {}),
            returns=tool_data.get("returns", {}),
            tags=tool_data.get("tags", []),
            metadata=tool_data.get("metadata", {}),
        )
        # 远程注册的工具暂时只记录元信息，不可直接执行
        info = ToolInfo(
            name=name,
            tool_schema=schema,
            status=ToolStatus.INACTIVE,  # 远程工具默认未激活
            metadata={"remote": True, **(tool_data.get("metadata", {}) or {})},
        )
        self._infos[name] = info
        logger.info(f"远程工具已注册（不可执行）: {name}")
        return info

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name not in self._tools and name not in self._infos:
            return False
        self._tools.pop(name, None)
        self._infos.pop(name, None)
        logger.info(f"工具已注销: {name}")
        return True

    # 兼容服务器端的别名
    unregister_tool = unregister

    def get_tool(self, name: str) -> Optional[ToolBase]:
        """获取工具实例"""
        return self._tools.get(name)

    def get_info(self, name: str) -> Optional[ToolInfo]:
        """获取工具信息"""
        return self._infos.get(name)

    def list_tools(
        self, category: Optional[str] = None
    ) -> List[ToolInfo]:
        """列出所有工具信息

        Args:
            category: 可选分类过滤
        """
        infos = list(self._infos.values())
        if category:
            infos = [i for i in infos if i.tool_schema.category.value == category]
        return infos

    def list_names(self) -> List[str]:
        """列出所有工具名"""
        return list(self._tools.keys())

    def set_status(self, name: str, status: ToolStatus) -> bool:
        """设置工具状态"""
        info = self._infos.get(name)
        if info is None:
            return False
        info.status = status
        return True

    async def execute_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> ToolResult:
        """执行工具

        Args:
            name: 工具名
            arguments: 参数字典

        Returns:
            ToolResult 工具执行结果

        Raises:
            ToolNotFoundError: 工具未找到
        """
        tool = self._tools.get(name)
        if tool is None:
            # 区分"未注册"与"仅注册了元信息"
            if name in self._infos:
                raise ToolNotFoundError(
                    f"工具 {name} 仅注册了元信息，不可执行"
                )
            raise ToolNotFoundError(f"工具未找到: {name}")

        info = self._infos[name]
        if info.status == ToolStatus.INACTIVE:
            raise ToolError(f"工具 {name} 当前状态为 inactive，不可执行")
        if info.status == ToolStatus.ERROR:
            raise ToolError(f"工具 {name} 当前状态为 error，不可执行")

        # 调用 safe_execute，统计调用信息
        result_data = await asyncio.wait_for(
            tool.safe_execute(arguments),
            timeout=self._default_timeout,
        )

        info.call_count += 1
        info.last_called = time.time()
        if not result_data["success"]:
            info.error_count += 1
            # 业务错误（ToolError）不改变工具状态，工具仍可用
            # 只有 safe_execute 内部捕获的未知异常才标记为 ERROR
            # 但 safe_execute 已经把所有异常都包装为 success=False
            # 因此这里根据 error 内容判断：包含"内部错误"的视为严重错误
            error_msg = result_data.get("error") or ""
            if error_msg.startswith("内部错误"):
                info.status = ToolStatus.ERROR
            else:
                info.status = ToolStatus.ACTIVE
        else:
            info.status = ToolStatus.ACTIVE

        return ToolResult(
            tool_id=info.tool_id,
            tool_name=name,
            success=result_data["success"],
            output=result_data["output"],
            error=result_data["error"],
            execution_time=result_data["execution_time"],
            metadata={"arguments": arguments},
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取工具统计信息"""
        total = len(self._infos)
        active = sum(1 for i in self._infos.values() if i.status == ToolStatus.ACTIVE)
        inactive = sum(
            1 for i in self._infos.values() if i.status == ToolStatus.INACTIVE
        )
        error = sum(1 for i in self._infos.values() if i.status == ToolStatus.ERROR)
        total_calls = sum(i.call_count for i in self._infos.values())
        total_errors = sum(i.error_count for i in self._infos.values())
        return {
            "total_tools": total,
            "active": active,
            "inactive": inactive,
            "error": error,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "overall_success_rate": (total_calls - total_errors) / total_calls
            if total_calls > 0
            else 1.0,
        }
