"""工具基类 - 所有工具的抽象基础

设计要点：
- ToolBase 是抽象基类，所有工具必须实现 execute 方法
- 每个工具通过 schema 属性暴露自身的元信息
- execute 接收 Dict 参数，返回任意 JSON 可序列化结果
- 工具应当是异步的，以适配 MCP 服务器的异步消息循环
"""
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..logger import logger
from ..models import ToolCategory, ToolSchema


class ToolError(Exception):
    """工具执行异常"""

    pass


class ToolBase(ABC):
    """工具抽象基类"""

    # 子类应当覆盖以下属性
    name: str = "base_tool"
    description: str = ""
    category: ToolCategory = ToolCategory.CUSTOM
    version: str = "1.0.0"
    tags: list = []
    parameters_schema: Dict[str, Any] = {}
    returns_schema: Dict[str, Any] = {}

    def get_schema(self) -> ToolSchema:
        """获取工具 Schema"""
        return ToolSchema(
            name=self.name,
            description=self.description,
            category=self.category,
            version=self.version,
            parameters=self.parameters_schema,
            returns=self.returns_schema,
            tags=list(self.tags),
            metadata={"class": self.__class__.__name__},
        )

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Any:
        """执行工具

        Args:
            params: 参数字典

        Returns:
            任意 JSON 可序列化的结果

        Raises:
            ToolError: 工具执行失败
        """
        ...

    def validate_params(self, params: Dict[str, Any]) -> None:
        """参数校验 - 简单实现，校验必填参数

        子类可覆盖以实现更复杂的校验逻辑。
        """
        if not self.parameters_schema:
            return
        required = self.parameters_schema.get("required", [])
        properties = self.parameters_schema.get("properties", {})
        for key in required:
            if key not in params:
                raise ToolError(f"缺少必填参数: {key}")
            expected_type = properties.get(key, {}).get("type")
            if expected_type and not self._check_type(params[key], expected_type):
                raise ToolError(
                    f"参数类型错误: {key} 应为 {expected_type}, "
                    f"实际为 {type(params[key]).__name__}"
                )

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """简单类型检查"""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        # 注意：bool 是 int 的子类，需要单独排除
        if expected_type == "integer" and isinstance(value, bool):
            return False
        if expected_type == "number" and isinstance(value, bool):
            return False
        return isinstance(value, expected)

    async def safe_execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """安全执行 - 包装 execute，捕获异常，返回结构化结果

        供 ToolRegistry 调用，避免异常冒泡到消息循环
        """
        start_time = time.time()
        try:
            self.validate_params(params)
            result = await self.execute(params)
            elapsed = time.time() - start_time
            return {
                "success": True,
                "output": result,
                "error": None,
                "execution_time": elapsed,
            }
        except ToolError as e:
            elapsed = time.time() - start_time
            logger.warning(f"工具 {self.name} 执行失败: {e}")
            return {
                "success": False,
                "output": None,
                "error": str(e),
                "execution_time": elapsed,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"工具 {self.name} 执行异常: {e}", exc_info=True
            )
            return {
                "success": False,
                "output": None,
                "error": f"内部错误: {e}",
                "execution_time": elapsed,
            }
