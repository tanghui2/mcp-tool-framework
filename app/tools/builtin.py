"""内置工具集 - 不依赖 LLM，可独立运行和测试

包含工具：
- EchoTool: 回显工具（基础测试）
- CalculatorTool: 数学表达式计算
- TextProcessorTool: 文本统计与变换
- TimeTool: 时间查询
- JsonFormatterTool: JSON 格式化与校验
- RandomGeneratorTool: 随机数生成
"""
import ast
import json
import operator
import random
import string
import time
from datetime import datetime, timezone
from typing import Any, Dict

from ..models import ToolCategory
from .base import ToolBase, ToolError


class EchoTool(ToolBase):
    """回显工具 - 基础测试用"""

    name = "echo"
    description = "回显输入内容，用于测试 MCP 协议链路"
    category = ToolCategory.SYSTEM
    version = "1.0.0"
    tags = ["test", "debug"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "要回显的消息"},
            "uppercase": {"type": "boolean", "description": "是否转大写", "default": False},
        },
        "required": ["message"],
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "echo": {"type": "string"},
            "original_length": {"type": "integer"},
        },
    }

    async def execute(self, params: Dict[str, Any]) -> Any:
        message = params["message"]
        uppercase = params.get("uppercase", False)
        if uppercase:
            message = message.upper()
        return {
            "echo": message,
            "original_length": len(params["message"]),
        }


class CalculatorTool(ToolBase):
    """计算器工具 - 安全的数学表达式计算

    安全策略：
    - 使用 AST 解析表达式
    - 仅允许数字、二元运算、一元运算、括号
    - 禁止函数调用、变量、属性访问
    """

    name = "calculator"
    description = "数学表达式计算，支持 + - * / % ** 和括号"
    category = ToolCategory.DATA
    version = "1.0.0"
    tags = ["math", "calc"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "数学表达式，例如 (1+2)*3",
            },
        },
        "required": ["expression"],
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "expression": {"type": "string"},
            "result": {"type": "number"},
        },
    }

    # 允许的二元运算符
    _BIN_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    # 允许的一元运算符
    _UNARY_OPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def _eval_node(self, node: ast.AST) -> Any:
        """递归计算 AST 节点"""
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ToolError(f"不支持的常量类型: {type(node.value).__name__}")
        if isinstance(node, ast.BinOp):
            op_func = self._BIN_OPS.get(type(node.op))
            if op_func is None:
                raise ToolError(f"不支持的二元运算符: {type(node.op).__name__}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            try:
                return op_func(left, right)
            except ZeroDivisionError:
                raise ToolError("除零错误")
        if isinstance(node, ast.UnaryOp):
            op_func = self._UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise ToolError(f"不支持的一元运算符: {type(node.op).__name__}")
            operand = self._eval_node(node.operand)
            return op_func(operand)
        raise ToolError(f"不支持的表达式元素: {type(node).__name__}")

    async def execute(self, params: Dict[str, Any]) -> Any:
        expression = params["expression"].strip()
        if not expression:
            raise ToolError("表达式不能为空")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ToolError(f"表达式语法错误: {e}")

        result = self._eval_node(tree)
        return {
            "expression": expression,
            "result": result,
        }


class TextProcessorTool(ToolBase):
    """文本处理工具 - 统计与变换"""

    name = "text_processor"
    description = "文本统计与变换：字符数、词数、行数、大小写转换"
    category = ToolCategory.DATA
    version = "1.0.0"
    tags = ["text", "stats"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "待处理文本"},
            "operation": {
                "type": "string",
                "enum": ["stats", "upper", "lower", "trim", "reverse"],
                "description": "操作类型",
                "default": "stats",
            },
        },
        "required": ["text"],
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "result": {"type": "string"},
            "stats": {"type": "object"},
        },
    }

    async def execute(self, params: Dict[str, Any]) -> Any:
        text = params["text"]
        operation = params.get("operation", "stats")

        if operation == "stats":
            words = text.split()
            return {
                "operation": "stats",
                "stats": {
                    "char_count": len(text),
                    "char_count_no_spaces": len(text.replace(" ", "")),
                    "word_count": len(words),
                    "line_count": text.count("\n") + 1 if text else 0,
                    "byte_count": len(text.encode("utf-8")),
                },
            }
        elif operation == "upper":
            return {"operation": "upper", "result": text.upper()}
        elif operation == "lower":
            return {"operation": "lower", "result": text.lower()}
        elif operation == "trim":
            return {"operation": "trim", "result": text.strip()}
        elif operation == "reverse":
            return {"operation": "reverse", "result": text[::-1]}
        else:
            raise ToolError(f"不支持的操作: {operation}")


class TimeTool(ToolBase):
    """时间工具 - 获取当前时间"""

    name = "time"
    description = "获取当前时间，支持多种格式和时区"
    category = ToolCategory.SYSTEM
    version = "1.0.0"
    tags = ["time", "date"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["iso", "timestamp", "datetime", "date"],
                "description": "返回格式",
                "default": "iso",
            },
            "timezone_offset": {
                "type": "number",
                "description": "时区偏移（小时），默认 0（UTC）",
                "default": 0,
            },
        },
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "format": {"type": "string"},
            "time": {"type": "string"},
            "timestamp": {"type": "number"},
        },
    }

    async def execute(self, params: Dict[str, Any]) -> Any:
        fmt = params.get("format", "iso")
        tz_offset = params.get("timezone_offset", 0)

        from datetime import timedelta

        tz = timezone(timedelta(hours=tz_offset))
        now = datetime.now(tz)
        ts = now.timestamp()

        if fmt == "iso":
            time_str = now.isoformat()
        elif fmt == "timestamp":
            time_str = str(ts)
        elif fmt == "datetime":
            time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        elif fmt == "date":
            time_str = now.strftime("%Y-%m-%d")
        else:
            raise ToolError(f"不支持的格式: {fmt}")

        return {
            "format": fmt,
            "time": time_str,
            "timestamp": ts,
            "timezone_offset": tz_offset,
        }


class JsonFormatterTool(ToolBase):
    """JSON 格式化工具"""

    name = "json_formatter"
    description = "JSON 字符串格式化、压缩、校验"
    category = ToolCategory.CODE
    version = "1.0.0"
    tags = ["json", "format"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "json_string": {"type": "string", "description": "JSON 字符串"},
            "operation": {
                "type": "string",
                "enum": ["pretty", "compact", "validate"],
                "description": "操作类型",
                "default": "pretty",
            },
            "indent": {
                "type": "integer",
                "description": "缩进空格数（pretty 模式）",
                "default": 2,
            },
        },
        "required": ["json_string"],
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "result": {"type": "string"},
            "valid": {"type": "boolean"},
        },
    }

    async def execute(self, params: Dict[str, Any]) -> Any:
        json_str = params["json_string"]
        operation = params.get("operation", "pretty")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            if operation == "validate":
                return {"operation": "validate", "valid": False, "error": str(e)}
            raise ToolError(f"JSON 解析失败: {e}")

        if operation == "pretty":
            indent = params.get("indent", 2)
            result = json.dumps(data, indent=indent, ensure_ascii=False)
            return {"operation": "pretty", "result": result, "valid": True}
        elif operation == "compact":
            result = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            return {"operation": "compact", "result": result, "valid": True}
        elif operation == "validate":
            return {"operation": "validate", "valid": True, "data_type": type(data).__name__}
        else:
            raise ToolError(f"不支持的操作: {operation}")


class RandomGeneratorTool(ToolBase):
    """随机数生成工具"""

    name = "random_generator"
    description = "生成随机数、随机字符串、UUID"
    category = ToolCategory.DATA
    version = "1.0.0"
    tags = ["random", "generator"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["int", "float", "string", "choice", "uuid"],
                "description": "生成类型",
                "default": "int",
            },
            "min": {"type": "number", "description": "最小值（int/float）", "default": 0},
            "max": {"type": "number", "description": "最大值（int/float）", "default": 100},
            "length": {
                "type": "integer",
                "description": "字符串长度",
                "default": 10,
            },
            "choices": {
                "type": "array",
                "description": "choice 类型的选项列表",
            },
            "seed": {"type": "integer", "description": "随机种子（用于复现）"},
        },
    }
    returns_schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "value": {"type": "string"},
        },
    }

    async def execute(self, params: Dict[str, Any]) -> Any:
        gen_type = params.get("type", "int")
        seed = params.get("seed")

        if seed is not None:
            random.seed(seed)

        if gen_type == "int":
            min_val = int(params.get("min", 0))
            max_val = int(params.get("max", 100))
            if min_val > max_val:
                raise ToolError("min 不能大于 max")
            value = random.randint(min_val, max_val)
        elif gen_type == "float":
            min_val = float(params.get("min", 0))
            max_val = float(params.get("max", 1))
            if min_val > max_val:
                raise ToolError("min 不能大于 max")
            value = random.uniform(min_val, max_val)
        elif gen_type == "string":
            length = int(params.get("length", 10))
            if length <= 0:
                raise ToolError("length 必须为正数")
            chars = string.ascii_letters + string.digits
            value = "".join(random.choice(chars) for _ in range(length))
        elif gen_type == "choice":
            choices = params.get("choices")
            if not choices:
                raise ToolError("choice 类型必须提供 choices 参数")
            value = random.choice(choices)
        elif gen_type == "uuid":
            import uuid as uuid_module

            value = str(uuid_module.uuid4())
        else:
            raise ToolError(f"不支持的类型: {gen_type}")

        return {"type": gen_type, "value": value}


# 内置工具列表
BUILTIN_TOOLS: list = [
    EchoTool,
    CalculatorTool,
    TextProcessorTool,
    TimeTool,
    JsonFormatterTool,
    RandomGeneratorTool,
]


def register_builtin_tools(registry: Any) -> None:
    """向注册中心注册所有内置工具"""
    for tool_cls in BUILTIN_TOOLS:
        registry.register(tool_cls())
