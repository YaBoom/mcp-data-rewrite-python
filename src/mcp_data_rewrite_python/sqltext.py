# sqltext.py
from __future__ import annotations

import re

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(--|#)[^\n]*")
_SINGLE_QUOTED = re.compile(r"'(?:[^'\\]|\\.|'')*'")
_DOUBLE_QUOTED = re.compile(r'"(?:[^"\\]|\\.|"")*"')

_TABLE_RE = re.compile(
    r'\b(?:from|join)\s+[`"]?(?:\w+[`"]?\s*\.\s*[`"]?)?(\w+)[`"]?',
    re.IGNORECASE | re.ASCII,
    )

FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\binto\s+(outfile|dumpfile)\b", re.I),
     "禁止 SELECT ... INTO OUTFILE / DUMPFILE（会写服务器文件）"),
    (re.compile(r"\bfor\s+update\b", re.I),
     "禁止 FOR UPDATE（会加行锁）"),
    (re.compile(r"\block\s+in\s+share\s+mode\b", re.I),
     "禁止 LOCK IN SHARE MODE（会加共享锁）"),
    (re.compile(r";\s*\S"),
     "禁止一次提交多条语句"),
]


def strip_literals_and_comments(sql: str) -> str:
    s = _BLOCK_COMMENT.sub(" ", sql)
    s = _LINE_COMMENT.sub(" ", s)
    s = _SINGLE_QUOTED.sub("''", s)
    s = _DOUBLE_QUOTED.sub('""', s)
    return s


def extract_tables(clean_sql: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _TABLE_RE.finditer(clean_sql):
        seen.setdefault(m.group(1), None)
    return list(seen)


def count_placeholders(clean_sql: str) -> int:
    return clean_sql.count("?")

def to_pyformat(sql: str) -> str:
    """把 ? 换成 %s，跳过字符串字面量内部（含 '' 和 \\ 转义）。"""
    out: list[str] = []
    i, n = 0, len(sql)
    quote: str | None = None

    while i < n:
        ch = sql[i]

        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:          # 反斜杠转义
                out.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:   # '' 双写转义
                    out.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue

        out.append("%s" if ch == "?" else ch)
        i += 1

    return "".join(out)