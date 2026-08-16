"""What the distribution actually contains.

A library can be entirely correct and still ship broken. These are the
failures that only exist in the built artifact, so no amount of testing the
source catches them -- the source is right, and what reached PyPI is not.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import sillo_inertia

PACKAGE = Path(sillo_inertia.__file__).parent


class TestTypeInformationIsShipped:
    def test_the_py_typed_marker_exists(self):
        """Without it, every downstream type checker ignores this package.

        PEP 561: a package that is not a stub and carries no ``py.typed`` is
        treated as untyped, whatever annotations it contains. mypy answers
        `Skipping analyzing "sillo_inertia": module is installed, but missing
        library stubs or py.typed marker` and moves on, so a user gets `Any`
        from every call -- while this repo's own mypy config type-checks the
        source and passes.
        """
        assert (PACKAGE / "py.typed").is_file(), (
            "sillo_inertia/py.typed is missing, so this package's annotations "
            "are invisible to anyone who installs it"
        )

    def test_the_marker_is_inside_the_installed_package(self):
        """Placed beside the modules, not at the repository root.

        A ``py.typed`` in the project root is not shipped in the wheel and
        does nothing; it has to sit in the importable package directory.
        """
        assert (PACKAGE / "__init__.py").is_file()
        assert (PACKAGE / "py.typed").parent == PACKAGE


class TestThePublicSurface:
    def test_every_exported_name_resolves(self):
        """``__all__`` is what `from sillo_inertia import *` and the docs
        promise. A name listed but not bound raises only when someone reaches
        for it."""
        missing = [
            name for name in sillo_inertia.__all__ if not hasattr(sillo_inertia, name)
        ]

        assert not missing, f"__all__ names that do not exist: {missing}"

    def test_all_is_sorted_and_unique(self):
        """Sorted so a merge conflict in it is a real conflict rather than
        two people appending to the same line."""
        assert sillo_inertia.__all__ == sorted(sillo_inertia.__all__)
        assert len(sillo_inertia.__all__) == len(set(sillo_inertia.__all__))

    @pytest.mark.parametrize(
        "module",
        ["adapter", "config", "context", "props", "vite"],
    )
    def test_every_module_imports_on_its_own(self, module):
        """Each submodule has to be importable without the package's
        ``__init__`` having run first -- that is what a downstream
        ``from sillo_inertia.vite import ...`` does.
        """
        assert importlib.import_module(f"sillo_inertia.{module}") is not None

    def test_the_version_is_readable(self):
        from importlib.metadata import version

        assert version("sillo-inertia")


class TestNoAccidentalDependencies:
    def test_importing_does_not_require_httpx(self):
        """httpx is a test dependency. If it leaks into the runtime import
        path, every user has to install it to render a page.
        """
        import subprocess
        import sys

        # A subprocess so the already-imported httpx in this session cannot
        # mask the dependency.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.modules['httpx'] = None; import sillo_inertia; "
                "print(sillo_inertia.Inertia is not None)",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "True" in result.stdout
