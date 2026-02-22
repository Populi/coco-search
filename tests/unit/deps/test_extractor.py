"""Tests for cocosearch.deps.extractor module."""

from unittest.mock import patch

from cocosearch.deps.extractor import _build_module_index, _resolve_target_files
from cocosearch.deps.models import DependencyEdge, DepType


# ============================================================================
# Tests: get_indexed_files
# ============================================================================


class TestGetIndexedFiles:
    """Tests for get_indexed_files()."""

    def test_returns_correct_tuples(self, mock_db_pool):
        """Should return (filename, language_id) tuples from the DB query."""
        pool, cursor, conn = mock_db_pool(
            results=[
                ("src/main.py", "py"),
                ("src/utils.go", "go"),
                ("README.md", "md"),
            ]
        )

        with patch(
            "cocosearch.deps.extractor.get_connection_pool",
            return_value=pool,
        ), patch(
            "cocosearch.deps.extractor.get_table_name",
            return_value="codeindex_test__test_chunks",
        ):
            from cocosearch.deps.extractor import get_indexed_files

            result = get_indexed_files("test")

        assert result == [
            ("src/main.py", "py"),
            ("src/utils.go", "go"),
            ("README.md", "md"),
        ]

    def test_query_contains_distinct_filename_language_id(self, mock_db_pool):
        """Query should use SELECT DISTINCT with filename and language_id."""
        pool, cursor, conn = mock_db_pool(results=[])

        with patch(
            "cocosearch.deps.extractor.get_connection_pool",
            return_value=pool,
        ), patch(
            "cocosearch.deps.extractor.get_table_name",
            return_value="codeindex_test__test_chunks",
        ):
            from cocosearch.deps.extractor import get_indexed_files

            get_indexed_files("test")

        cursor.assert_query_contains("DISTINCT")
        cursor.assert_query_contains("filename")
        cursor.assert_query_contains("language_id")

    def test_query_filters_null_language_id(self, mock_db_pool):
        """Query should filter out rows where language_id IS NOT NULL."""
        pool, cursor, conn = mock_db_pool(results=[])

        with patch(
            "cocosearch.deps.extractor.get_connection_pool",
            return_value=pool,
        ), patch(
            "cocosearch.deps.extractor.get_table_name",
            return_value="codeindex_test__test_chunks",
        ):
            from cocosearch.deps.extractor import get_indexed_files

            get_indexed_files("test")

        cursor.assert_query_contains("language_id IS NOT NULL")


# ============================================================================
# Tests: extract_dependencies
# ============================================================================


class TestExtractDependencies:
    """Tests for extract_dependencies()."""

    def test_extracts_and_stores_edges_from_python_file(
        self, mock_db_pool, tmp_path
    ):
        """Should extract edges from a real Python file and store them."""
        # Create a real Python file with imports
        py_file = tmp_path / "src" / "main.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("import os\nfrom sys import argv\n")

        pool, cursor, conn = mock_db_pool()

        indexed_files = [("src/main.py", "py")]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ) as mock_drop, patch(
            "cocosearch.deps.extractor.create_deps_table",
        ) as mock_create, patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            stats = extract_dependencies("test", str(tmp_path))

        # Should drop and recreate the table
        mock_drop.assert_called_once_with("test")
        mock_create.assert_called_once_with("test")

        # Should have inserted edges
        mock_insert.assert_called_once()
        call_args = mock_insert.call_args
        assert call_args[0][0] == "test"  # index_name
        edges = call_args[0][1]
        assert len(edges) == 2  # import os + from sys import argv

        # All edges should have source_file set
        for edge in edges:
            assert edge.source_file == "src/main.py"
            assert edge.dep_type == DepType.IMPORT

        # Stats
        assert stats["files_processed"] == 1
        assert stats["files_skipped"] == 0
        assert stats["edges_found"] == 2
        assert stats["errors"] == 0

    def test_skips_files_without_registered_extractor(
        self, mock_db_pool, tmp_path
    ):
        """Files with no registered extractor should be skipped."""
        # Create a markdown file (no extractor for "md")
        md_file = tmp_path / "README.md"
        md_file.write_text("# Hello")

        indexed_files = [("README.md", "md")]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            stats = extract_dependencies("test", str(tmp_path))

        assert stats["files_processed"] == 0
        assert stats["files_skipped"] == 1
        assert stats["edges_found"] == 0
        assert stats["errors"] == 0

        # insert_edges should be called with empty list
        mock_insert.assert_called_once_with("test", [])

    def test_handles_missing_file_gracefully(self, mock_db_pool, tmp_path):
        """Missing file should increment errors, not crash."""
        # Don't create the file — it's "missing"
        indexed_files = [("nonexistent.py", "py")]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            stats = extract_dependencies("test", str(tmp_path))

        assert stats["files_processed"] == 0
        assert stats["files_skipped"] == 0
        assert stats["edges_found"] == 0
        assert stats["errors"] == 1

        # insert_edges should be called with empty list (no edges from missing file)
        mock_insert.assert_called_once_with("test", [])

    def test_mixed_files_correct_stats(self, mock_db_pool, tmp_path):
        """Mix of valid, skipped, and missing files should produce correct stats."""
        # Create a valid Python file
        py_file = tmp_path / "app.py"
        py_file.write_text("import json\n")

        indexed_files = [
            ("app.py", "py"),           # valid
            ("README.md", "md"),         # no extractor -> skipped
            ("missing.py", "py"),        # missing -> error
        ]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ):
            from cocosearch.deps.extractor import extract_dependencies

            stats = extract_dependencies("test", str(tmp_path))

        assert stats["files_processed"] == 1
        assert stats["files_skipped"] == 1
        assert stats["edges_found"] == 1  # import json
        assert stats["errors"] == 1

    def test_sets_source_file_on_edges(self, mock_db_pool, tmp_path):
        """Orchestrator should set source_file on each returned edge."""
        py_file = tmp_path / "lib.py"
        py_file.write_text("from os.path import join\n")

        indexed_files = [("lib.py", "py")]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            extract_dependencies("test", str(tmp_path))

        edges = mock_insert.call_args[0][1]
        assert len(edges) == 1
        assert edges[0].source_file == "lib.py"


# ============================================================================
# Tests: _build_module_index
# ============================================================================


class TestBuildModuleIndex:
    """Tests for _build_module_index()."""

    def test_regular_python_file(self):
        """Should map dotted module name to file path."""
        files = [("src/cocosearch/exceptions.py", "py")]
        index = _build_module_index(files)

        assert index["cocosearch.exceptions"] == "src/cocosearch/exceptions.py"
        assert index["src.cocosearch.exceptions"] == "src/cocosearch/exceptions.py"

    def test_init_file_maps_to_package(self):
        """__init__.py should map to the package (without __init__)."""
        files = [("src/cocosearch/__init__.py", "py")]
        index = _build_module_index(files)

        assert index["cocosearch"] == "src/cocosearch/__init__.py"
        assert index["src.cocosearch"] == "src/cocosearch/__init__.py"

    def test_top_level_file_without_src_prefix(self):
        """Files without src/ prefix should still be indexed."""
        files = [("utils.py", "py")]
        index = _build_module_index(files)

        assert index["utils"] == "utils.py"

    def test_skips_non_python_files(self):
        """Non-Python files should be ignored."""
        files = [
            ("src/main.go", "go"),
            ("README.md", "md"),
        ]
        index = _build_module_index(files)

        assert index == {}

    def test_multiple_files(self):
        """Should index all Python files correctly."""
        files = [
            ("src/cocosearch/cli.py", "py"),
            ("src/cocosearch/search/query.py", "py"),
            ("src/cocosearch/__init__.py", "py"),
            ("README.md", "md"),
        ]
        index = _build_module_index(files)

        assert index["cocosearch.cli"] == "src/cocosearch/cli.py"
        assert index["cocosearch.search.query"] == "src/cocosearch/search/query.py"
        assert index["cocosearch"] == "src/cocosearch/__init__.py"

    def test_lib_prefix_stripped(self):
        """Files under lib/ should have prefix stripped."""
        files = [("lib/mypackage/core.py", "py")]
        index = _build_module_index(files)

        assert index["mypackage.core"] == "lib/mypackage/core.py"
        assert index["lib.mypackage.core"] == "lib/mypackage/core.py"

    def test_nested_init_file(self):
        """Nested __init__.py should map to subpackage."""
        files = [("src/cocosearch/deps/__init__.py", "py")]
        index = _build_module_index(files)

        assert index["cocosearch.deps"] == "src/cocosearch/deps/__init__.py"


# ============================================================================
# Tests: _resolve_target_files
# ============================================================================


class TestResolveTargetFiles:
    """Tests for _resolve_target_files()."""

    def _make_edge(self, source_file, module, target_file=None, target_symbol=None):
        return DependencyEdge(
            source_file=source_file,
            source_symbol=None,
            target_file=target_file,
            target_symbol=target_symbol,
            dep_type=DepType.IMPORT,
            metadata={"module": module, "line": 1},
        )

    def test_resolves_absolute_import(self):
        """Absolute import should resolve to file path."""
        module_index = {
            "cocosearch.exceptions": "src/cocosearch/exceptions.py",
        }
        edges = [self._make_edge("src/app.py", "cocosearch.exceptions")]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/exceptions.py"

    def test_skips_already_resolved_edges(self):
        """Edges with target_file already set should be left alone."""
        module_index = {
            "cocosearch.exceptions": "src/cocosearch/exceptions.py",
        }
        edges = [
            self._make_edge(
                "src/app.py",
                "cocosearch.exceptions",
                target_file="already/set.py",
            )
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "already/set.py"

    def test_skips_edges_without_module_metadata(self):
        """Edges with no module in metadata should be skipped."""
        edge = DependencyEdge(
            source_file="src/app.py",
            source_symbol=None,
            target_file=None,
            target_symbol=None,
            dep_type=DepType.IMPORT,
            metadata={"line": 1},
        )

        _resolve_target_files([edge], {})

        assert edge.target_file is None

    def test_unresolved_import_stays_none(self):
        """External imports (not in index) should remain target_file=None."""
        edges = [self._make_edge("src/app.py", "numpy")]

        _resolve_target_files(edges, {})

        assert edges[0].target_file is None

    def test_resolves_relative_import_single_dot(self):
        """from . import utils in a package should resolve."""
        module_index = {
            "cocosearch.deps.utils": "src/cocosearch/deps/utils.py",
        }
        edges = [
            self._make_edge(
                "src/cocosearch/deps/extractor.py",
                ".utils",
                target_symbol="utils",
            )
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/deps/utils.py"

    def test_resolves_relative_import_double_dot(self):
        """from ..models import X should resolve up two levels."""
        module_index = {
            "cocosearch.deps.models": "src/cocosearch/deps/models.py",
        }
        edges = [
            self._make_edge(
                "src/cocosearch/deps/extractors/python.py",
                "..models",
                target_symbol="DependencyEdge",
            )
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/deps/models.py"

    def test_resolves_relative_import_dot_only(self):
        """from . import X (bare dot, no module name) should resolve to package."""
        module_index = {
            "cocosearch.deps": "src/cocosearch/deps/__init__.py",
        }
        edges = [
            self._make_edge(
                "src/cocosearch/deps/extractor.py",
                ".",
                target_symbol="something",
            )
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/deps/__init__.py"

    def test_resolves_submodule_import_to_parent(self):
        """from cocosearch.deps.models import X should resolve to models.py."""
        module_index = {
            "cocosearch.deps.models": "src/cocosearch/deps/models.py",
        }
        edges = [
            self._make_edge(
                "src/cocosearch/cli.py",
                "cocosearch.deps.models",
                target_symbol="DependencyEdge",
            )
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/deps/models.py"

    def test_multiple_edges_resolved(self):
        """Should resolve multiple edges in a single pass."""
        module_index = {
            "cocosearch.cli": "src/cocosearch/cli.py",
            "cocosearch.search.query": "src/cocosearch/search/query.py",
        }
        edges = [
            self._make_edge("src/app.py", "cocosearch.cli"),
            self._make_edge("src/app.py", "cocosearch.search.query"),
            self._make_edge("src/app.py", "os"),  # external, won't resolve
        ]

        _resolve_target_files(edges, module_index)

        assert edges[0].target_file == "src/cocosearch/cli.py"
        assert edges[1].target_file == "src/cocosearch/search/query.py"
        assert edges[2].target_file is None


# ============================================================================
# Tests: extract_dependencies integration with module resolution
# ============================================================================


class TestExtractDependenciesModuleResolution:
    """Tests verifying module resolution runs during extract_dependencies()."""

    def test_resolves_internal_imports(self, mock_db_pool, tmp_path):
        """Internal imports should get target_file populated."""
        # Create two Python files where one imports the other
        (tmp_path / "src" / "mypackage").mkdir(parents=True)
        (tmp_path / "src" / "mypackage" / "__init__.py").write_text("")
        (tmp_path / "src" / "mypackage" / "models.py").write_text(
            "class User: pass\n"
        )
        (tmp_path / "src" / "mypackage" / "cli.py").write_text(
            "from mypackage.models import User\n"
        )

        indexed_files = [
            ("src/mypackage/__init__.py", "py"),
            ("src/mypackage/models.py", "py"),
            ("src/mypackage/cli.py", "py"),
        ]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            extract_dependencies("test", str(tmp_path))

        edges = mock_insert.call_args[0][1]

        # Find the edge for "from mypackage.models import User"
        model_edges = [
            e
            for e in edges
            if e.metadata.get("module") == "mypackage.models"
        ]
        assert len(model_edges) == 1
        assert model_edges[0].target_file == "src/mypackage/models.py"

    def test_external_imports_stay_none(self, mock_db_pool, tmp_path):
        """External imports should keep target_file=None."""
        py_file = tmp_path / "app.py"
        py_file.write_text("import numpy\n")

        indexed_files = [("app.py", "py")]

        with patch(
            "cocosearch.deps.extractor.get_indexed_files",
            return_value=indexed_files,
        ), patch(
            "cocosearch.deps.extractor.drop_deps_table",
        ), patch(
            "cocosearch.deps.extractor.create_deps_table",
        ), patch(
            "cocosearch.deps.extractor.insert_edges",
        ) as mock_insert:
            from cocosearch.deps.extractor import extract_dependencies

            extract_dependencies("test", str(tmp_path))

        edges = mock_insert.call_args[0][1]
        assert len(edges) == 1
        assert edges[0].target_file is None  # numpy is external
