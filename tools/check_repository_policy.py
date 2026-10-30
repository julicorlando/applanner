"""Fail safely on generated/private artifacts in the index; never print contents."""

import re
import ast
from collections import Counter
import subprocess
from pathlib import Path


FORBIDDEN = re.compile(
    r"(^|/)(node_modules|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)(/|$)"
    r"|(^|/)\.env($|\.(?!example$))|\.(pyc|pyo|sqlite3|pfx|p12|key|pem|tmp|old|log)(\.|$)"
    r"|\.bak($|-)|\.zip\.enc$|^config/(app|database)\.php$|^error_log"
    r"|^storage/(private/backups|update-backups|private/cleanup-manifests|updates)/"
    r"|^storage/(cache|rate_limits)/(?!\.gitkeep$)|^storage/installed\.lock$"
)


def main():
    root = Path(__file__).resolve().parents[1]
    paths = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        .decode()
        .split("\0")
    )
    failures = [path for path in paths if path and FORBIDDEN.search(path)]
    for path in failures:
        print("Forbidden tracked artifact:", path)
    for path in paths:
        if not path.startswith("django/") or not path.endswith(".py"):
            continue
        tree = ast.parse((root / path).read_text())
        definitions = Counter(
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for name, count in definitions.items():
            if count > 1:
                print("Overridden module function:", path, name)
                failures.append(path)
    if failures:
        return 1
    print("Repository artifact policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
