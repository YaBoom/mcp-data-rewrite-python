from __future__ import annotations
from typing import Any,Literal,TypeAlias
from pydantic import  BaseModel,ConfigDict,Field,field_validator
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from datetime import date, datetime
from decimal import Decimal
from collections.abc import Mapping

Role: TypeAlias = Literal["admin","manager","employee"]

SQLParam: TypeAlias = str | int | float | bool | None


def jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", "replace")
    if isinstance(obj, Mapping):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    return obj

class ToolError(MCPToolError):
    """工具层可预期的失败（权限、语句非法、超时）。

    必须继承 SDK 的 ToolError：只有它会被原样透传给客户端，
    其他异常会被包装成 `Error executing tool <name>`。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")

class MySQLQueryArgs(BaseModel):
    model_config = ConfigDict(
        extra= "forbid",
        frozen=True,
        str_strip_whitespace=False,
    )
    sql: str = Field(min_length=1, max_length=10_000)
    params: list[SQLParam] = Field(default_factory=list)

    @field_validator("sql")
    @classmethod
    def sql_must_not_be_blank(cls,v:str) -> str:
        if not v.strip():
            raise  ValueError("sql不能为空")
        return v

class QueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool = True
    row_count: int = 0
    data: Any = None
    execution_time_ms: int = 0