"""Prototype-grade structural tests for Feature 01.

These tests are intentionally lightweight - they verify that the
scaffolding promised in `docs/features.md` (section 01) is actually on
disk and well-formed, without requiring any third-party packages.

Run with stdlib only:
    python -m unittest logs/01-project-scaffolding/tests/test_scaffold.py
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestRepoLayout(unittest.TestCase):
    """Top-level folders and anchor files must exist."""

    REQUIRED_PATHS = [
        "README.md",
        "docs/features.md",
        ".gitignore",
        "Makefile",
        "docker-compose.yml",
        "backend",
        "backend/pyproject.toml",
        "backend/README.md",
        "backend/app/__init__.py",
        "backend/app/main.py",
        "backend/app/config.py",
        "backend/tests/__init__.py",
        "simulator/__init__.py",
        "simulator/README.md",
        "frontend/package.json",
        "frontend/index.html",
        "frontend/README.md",
        "db/migrations/README.md",
        "db/seed/README.md",
        "infra/.env.sample",
        "infra/Dockerfile.backend",
        "infra/Dockerfile.frontend",
        "logs/README.md",
    ]

    def test_required_paths_exist(self) -> None:
        missing = [p for p in self.REQUIRED_PATHS if not (REPO_ROOT / p).exists()]
        self.assertEqual(missing, [], f"Missing scaffolding paths: {missing}")

    def test_22_feature_log_folders(self) -> None:
        log_dirs = sorted(p.name for p in (REPO_ROOT / "logs").iterdir() if p.is_dir())
        numbered = [d for d in log_dirs if re.match(r"^\d{2}-", d)]
        self.assertEqual(
            len(numbered), 22,
            f"Expected 22 numbered feature folders; found {len(numbered)}: {numbered}",
        )

    def test_each_feature_folder_has_log_files(self) -> None:
        required = {"tests", "test_review.md", "changes.md", "errors.md"}
        missing_report: list[str] = []
        for folder in (REPO_ROOT / "logs").iterdir():
            if not folder.is_dir() or not re.match(r"^\d{2}-", folder.name):
                continue
            present = {p.name for p in folder.iterdir()}
            absent = required - present
            if absent:
                missing_report.append(f"{folder.name}: missing {sorted(absent)}")
        self.assertEqual(missing_report, [], "\n".join(missing_report))


class TestFrontendPackageJson(unittest.TestCase):
    """package.json must be valid JSON and declare the core libs."""

    def setUp(self) -> None:
        self.pkg = json.loads((REPO_ROOT / "frontend" / "package.json").read_text())

    def test_valid_json(self) -> None:
        self.assertIn("name", self.pkg)
        self.assertEqual(self.pkg["name"], "vidyutdrishti-frontend")

    def test_core_libraries_declared(self) -> None:
        deps = self.pkg.get("dependencies", {})
        for required in ("react", "react-dom", "leaflet", "react-leaflet", "recharts"):
            self.assertIn(required, deps, f"Missing frontend dep: {required}")

    def test_dev_libraries_declared(self) -> None:
        dev = self.pkg.get("devDependencies", {})
        for required in ("vite", "typescript", "vitest"):
            self.assertIn(required, dev, f"Missing frontend devDep: {required}")


class TestDockerCompose(unittest.TestCase):
    """docker-compose.yml must declare the three baseline services."""

    def test_core_services_present(self) -> None:
        content = (REPO_ROOT / "docker-compose.yml").read_text()
        for svc in ("timescaledb:", "backend:", "frontend:"):
            self.assertIn(svc, content, f"Service {svc!r} not declared in docker-compose.yml")


class TestPyProjectToml(unittest.TestCase):
    """Regex-level sanity (stdlib tomllib is Python 3.11+ only)."""

    def setUp(self) -> None:
        self.content = (REPO_ROOT / "backend" / "pyproject.toml").read_text()

    def test_requires_python_311(self) -> None:
        self.assertRegex(self.content, r'requires-python\s*=\s*">=3\.11"')

    def test_core_dependencies_declared(self) -> None:
        for pkg in ("fastapi", "SQLAlchemy", "alembic", "prophet", "scikit-learn",
                    "APScheduler", "holidays", "pandas"):
            self.assertIn(pkg, self.content, f"pyproject.toml missing dep: {pkg}")


if __name__ == "__main__":
    unittest.main()
