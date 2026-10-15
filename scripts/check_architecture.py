#!/usr/bin/env python3
"""Repeatable check of the architecture rules accepted in ADR-01 (C03).

Rule 1: only reservations/lifecycle.py may write Reservation.status.
Rule 2: the domain modules must not depend on the web framework.

Usage: python scripts/check_architecture.py   (exit 1 and a report if a rule is broken)
"""

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src" / "reservations"

STATUS_OWNER = "lifecycle.py"
DOMAIN_MODULES = {"lifecycle.py", "availability.py", "approval.py", "notifications.py", "models.py"}
FORBIDDEN_IMPORTS = ("rest_framework", "django.http", "django.shortcuts")


def production_modules(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "tests" not in p.parts)


def status_writes(tree: ast.AST) -> list[int]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "status":
                    found.append(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "update":
                if any(keyword.arg == "status" for keyword in node.keywords):
                    found.append(node.lineno)
    return sorted(set(found))


def forbidden_imports(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name.startswith(FORBIDDEN_IMPORTS):
                found.append((node.lineno, name))
    return found


def violations(root: Path = APP) -> list[str]:
    report = []
    for path in production_modules(root):
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(root.parent.parent)

        if path.name != STATUS_OWNER:
            for line in status_writes(tree):
                report.append(f"{relative}:{line}: writes Reservation.status outside {STATUS_OWNER}")

        if path.name in DOMAIN_MODULES:
            for line, module in forbidden_imports(tree):
                report.append(f"{relative}:{line}: domain module imports {module}")
    return report


def main() -> int:
    report = violations()
    if report:
        print("Architecture rules broken:")
        for line in report:
            print(f"  {line}")
        return 1
    print("Architecture rules hold: Reservation.status is written only by lifecycle.py,")
    print("and no domain module depends on the web framework.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
