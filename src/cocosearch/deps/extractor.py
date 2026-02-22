"""Extraction orchestrator for dependency graph construction.

Runs language-specific dependency extractors over all indexed files,
collecting edges and batch-inserting them into the deps table.
After extraction, resolves Python module names to file paths so that
both forward (get_dependencies) and reverse (get_dependents) queries work.
"""

import logging
import os
from pathlib import PurePosixPath

from cocosearch.deps.db import create_deps_table, drop_deps_table, insert_edges
from cocosearch.deps.models import DependencyEdge
from cocosearch.deps.registry import get_extractor
from cocosearch.search.db import get_connection_pool, get_table_name

logger = logging.getLogger(__name__)

# Common source directory prefixes to strip when building module names.
_COMMON_PREFIXES = ("src/", "lib/")


def _build_module_index(indexed_files: list[tuple[str, str]]) -> dict[str, str]:
    """Build module_name -> relative_file_path mapping from indexed files.

    Converts file paths to dotted module names by stripping ``.py`` (or
    ``/__init__.py``) and replacing ``/`` with ``.``.  Each path is
    registered both with its full prefix and with common prefixes
    (``src/``, ``lib/``) stripped, so ``src/cocosearch/exceptions.py``
    maps to both ``src.cocosearch.exceptions`` and
    ``cocosearch.exceptions``.

    Args:
        indexed_files: List of (relative_path, language_id) tuples.

    Returns:
        Dict mapping dotted module names to their relative file paths.
    """
    index: dict[str, str] = {}

    for filepath, language_id in indexed_files:
        if language_id != "py":
            continue

        # Normalise backslashes (Windows compat)
        filepath_posix = filepath.replace("\\", "/")

        # Strip extension to get a "raw" module path
        if filepath_posix.endswith("/__init__.py"):
            module_path = filepath_posix[: -len("/__init__.py")]
        elif filepath_posix.endswith(".py"):
            module_path = filepath_posix[:-3]
        else:
            continue

        # Register with full path
        dotted = module_path.replace("/", ".")
        index[dotted] = filepath

        # Also register with common prefixes stripped
        for prefix in _COMMON_PREFIXES:
            if filepath_posix.startswith(prefix):
                stripped = module_path[len(prefix) :]
                index[stripped.replace("/", ".")] = filepath

    return index


def _resolve_target_files(
    edges: list[DependencyEdge],
    module_index: dict[str, str],
) -> None:
    """Resolve ``metadata.module`` to ``target_file`` on edges (in place).

    For relative imports (starting with ``.``), resolves relative to the
    source file's package directory.  For absolute imports, looks up the
    module directly in *module_index*.

    Args:
        edges: Dependency edges to mutate.
        module_index: Mapping from dotted module names to file paths.
    """
    for edge in edges:
        if edge.target_file is not None:
            continue
        module = edge.metadata.get("module")
        if not module:
            continue

        if module.startswith("."):
            resolved = _resolve_relative_import(edge.source_file, module, module_index)
        else:
            resolved = _resolve_absolute_import(module, module_index)

        if resolved is not None:
            edge.target_file = resolved


def _resolve_absolute_import(
    module: str, module_index: dict[str, str]
) -> str | None:
    """Look up an absolute module name in the index.

    Tries the full module name first, then progressively shorter parent
    packages to handle ``from cocosearch.deps.models import X`` where
    the module is ``cocosearch.deps.models``.
    """
    # Try exact match first
    if module in module_index:
        return module_index[module]

    # Try parent packages (from cocosearch.deps.models -> cocosearch.deps.models,
    # cocosearch.deps, cocosearch) to handle submodule imports
    parts = module.split(".")
    for i in range(len(parts) - 1, 0, -1):
        parent = ".".join(parts[:i])
        if parent in module_index:
            return module_index[parent]

    return None


def _resolve_relative_import(
    source_file: str,
    module: str,
    module_index: dict[str, str],
) -> str | None:
    """Resolve a relative import to a file path.

    Counts the leading dots to determine how many parent levels to
    traverse, then appends the remainder as a module name.

    For ``from . import utils`` in ``src/cocosearch/deps/extractor.py``:
    - 1 dot -> parent package = ``src/cocosearch/deps``
    - Looks up ``cocosearch.deps.utils`` (with prefix stripping)

    Args:
        source_file: Relative path of the importing file.
        module: The relative import string (e.g., ``.models``, ``..utils``).
        module_index: The module name -> file path mapping.

    Returns:
        Resolved file path or None if not found.
    """
    # Count leading dots
    dots = 0
    for ch in module:
        if ch == ".":
            dots += 1
        else:
            break
    remainder = module[dots:]

    # Get the package directory of the source file
    source_posix = source_file.replace("\\", "/")
    source_path = PurePosixPath(source_posix)

    # Go up `dots` levels from the source file's directory.
    # 1 dot = current package (parent dir of source file)
    # 2 dots = parent package (grandparent dir), etc.
    package_dir = source_path.parent
    for _ in range(dots - 1):
        package_dir = package_dir.parent

    # Build the absolute module name from the resolved package dir
    package_module = str(package_dir).replace("/", ".")

    if remainder:
        absolute_module = f"{package_module}.{remainder}"
    else:
        absolute_module = package_module

    # Try with the full path first (e.g., src.cocosearch.deps.utils),
    # then with common prefixes stripped (e.g., cocosearch.deps.utils)
    result = _resolve_absolute_import(absolute_module, module_index)
    if result is not None:
        return result

    for prefix in _COMMON_PREFIXES:
        dotted_prefix = prefix.replace("/", ".")
        if absolute_module.startswith(dotted_prefix):
            stripped = absolute_module[len(dotted_prefix) :]
            result = _resolve_absolute_import(stripped, module_index)
            if result is not None:
                return result

    return None


def get_indexed_files(index_name: str) -> list[tuple[str, str]]:
    """Query the chunks table for distinct indexed file paths and languages.

    Args:
        index_name: The index name to look up files in.

    Returns:
        List of (filename, language_id) tuples for all files that have
        a non-null language_id in the chunks table.
    """
    table = get_table_name(index_name)
    pool = get_connection_pool()

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT filename, language_id "
                f"FROM {table} "
                f"WHERE language_id IS NOT NULL"
            )
            return cur.fetchall()


def extract_dependencies(index_name: str, codebase_path: str) -> dict:
    """Extract dependency edges from all indexed files and store them.

    Drops and recreates the deps table, then iterates over all indexed
    files. For each file with a registered extractor, reads the file
    content, runs the extractor, and sets ``source_file`` on each
    returned edge. All edges are batch-inserted at the end.

    Args:
        index_name: The index name to extract dependencies for.
        codebase_path: Absolute path to the codebase root directory.

    Returns:
        Stats dict with keys: ``files_processed``, ``files_skipped``,
        ``edges_found``, ``errors``.
    """
    indexed_files = get_indexed_files(index_name)

    drop_deps_table(index_name)
    create_deps_table(index_name)

    all_edges: list[DependencyEdge] = []
    files_processed = 0
    files_skipped = 0
    edges_found = 0
    errors = 0

    for filename, language_id in indexed_files:
        extractor = get_extractor(language_id)

        if extractor is None:
            logger.info(
                "No extractor for language_id=%s, skipping %s",
                language_id,
                filename,
            )
            files_skipped += 1
            continue

        file_path = os.path.join(codebase_path, filename)

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            logger.warning("Could not read %s: %s", file_path, exc)
            errors += 1
            continue

        try:
            edges = extractor.extract(filename, content)
        except Exception as exc:
            logger.warning("Extraction failed for %s: %s", filename, exc)
            errors += 1
            continue

        for edge in edges:
            edge.source_file = filename

        all_edges.extend(edges)
        files_processed += 1
        edges_found += len(edges)

    module_index = _build_module_index(indexed_files)
    _resolve_target_files(all_edges, module_index)

    insert_edges(index_name, all_edges)

    logger.info(
        "Dependency extraction complete: %d files processed, "
        "%d skipped, %d edges found, %d errors",
        files_processed,
        files_skipped,
        edges_found,
        errors,
    )

    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "edges_found": edges_found,
        "errors": errors,
    }
