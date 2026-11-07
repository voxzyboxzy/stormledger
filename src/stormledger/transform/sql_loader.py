"""Load the SQL shipped with the package."""

from __future__ import annotations

from pathlib import Path


def read_sql(name: str) -> str:
    path = Path(__file__).resolve().parent / "sql" / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text()


def execute_script(connection, sql: str) -> None:
    statements = []
    current: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    tail = "\n".join(current).strip().rstrip(";").strip()
    if tail:
        statements.append(tail)
    for statement in statements:
        connection.execute(statement)
