from collections.abc import Mapping
from typing import Any
SENSITIVE_FIELDS = frozenset({"password", "id_card", "phone", "salary"})

class Policy:
    def __init__(self) -> None:
        self._tables: dict[str,set[str]] = {
            "admin": {"*"},
            "manager": {"employees", "departments", "projects", "sales"},
            "employee": {"employees", "departments", "projects"},
        }
        self._tools: dict[str,set[str]] = {
            "admin": {"mysql_query", "redis_get", "api_call"},
            "manager": {"mysql_query", "redis_get", "api_call"},
            "employee": {"redis_get", "api_call"},
        }

    def get_allowed_tables(self, role: str) -> set[str]:
        return self._tables.get(role, set())

    def has_table_access(self,role:str,table:str) -> bool:
        allowed = self.get_allowed_tables(role)
        if not allowed:
            return False
        if "*" in allowed:
            return True
        return table.lower() in {t.lower() for t in allowed}

    def can_use_tool(self, role: str, tool: str) -> bool:
        return tool in self._tools.get(role, set())

    def check_permission(self, role: str, tool_name: str) -> bool:
        return tool_name in self._tools.get(role, set())




def sanitize_data(data:Any,role:str) -> Any:
    if role == "admin":
        return data
    if isinstance(data,(list,tuple)):
        return [sanitize_data(item, role) for item in data]
    if isinstance(data, Mapping):
        return {
            key: ("***" if key.lower() in SENSITIVE_FIELDS else value)
            for key, value in data.items()
        }
    return data