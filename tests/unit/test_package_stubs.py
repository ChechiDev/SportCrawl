"""Smoke tests for REQ-8.5 and REQ-8.6 package stubs.

Validates that the domains/shared and infrastructure/persistence/models/shared
packages are importable and contain no SQLAlchemy or infrastructure coupling
in the domains layer.
"""

import importlib


class TestDomainsSharedPackage:
    """REQ-8.5: domains/shared package must be importable with no infra coupling."""

    def test_domains_shared_is_importable(self) -> None:
        """domains.shared package must be importable without error."""
        mod = importlib.import_module("domains.shared")
        assert mod is not None

    def test_domains_shared_has_no_sqlalchemy_dependency(self) -> None:
        """domains.shared must not import SQLAlchemy (infrastructure coupling)."""
        import ast
        from pathlib import Path

        source_path = (
            Path(__file__).parent.parent.parent
            / "domains"
            / "shared"
            / "__init__.py"
        )
        source = source_path.read_text()
        tree = ast.parse(source)

        sqlalchemy_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            and (
                (
                    isinstance(node, ast.Import)
                    and any("sqlalchemy" in alias.name for alias in node.names)
                )
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module is not None
                    and "sqlalchemy" in node.module
                )
            )
        ]

        assert not sqlalchemy_imports, (
            "domains.shared/__init__.py must not import SQLAlchemy — "
            f"found: {[ast.dump(n) for n in sqlalchemy_imports]}"
        )


class TestModelsSharedPackage:
    """REQ-8.6: infrastructure/persistence/models/shared package must be importable."""

    def test_models_shared_is_importable(self) -> None:
        """infrastructure.persistence.models.shared must be importable without error."""
        mod = importlib.import_module("infrastructure.persistence.models.shared")
        assert mod is not None
