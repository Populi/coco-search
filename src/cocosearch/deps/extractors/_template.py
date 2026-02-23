"""Template for creating new dependency extractors.

Copy this file to <language>.py and implement the TODOs.

Example: To add support for Go files, copy this to go.py and:
1. Set LANGUAGES to {"go"}
2. Implement extract() to parse Go import statements and function calls

The extractor will be autodiscovered at import time by the registry
in cocosearch.deps.registry. Files prefixed with ``_`` are skipped.
"""

from cocosearch.deps.models import DependencyEdge


class TemplateExtractor:
    """Extractor for <LANGUAGE> dependency edges.

    TODO: Replace <LANGUAGE> with the target language name.
    """

    # TODO: Set of language_ids this extractor handles.
    # Must match the language_id values used by the indexer
    # (e.g., "python", "go", "typescript").
    # Leave empty in the template so it is skipped during discovery.
    LANGUAGES: set[str] = set()

    def extract(self, file_path: str, content: str) -> list[DependencyEdge]:
        """Extract dependency edges from a source file.

        TODO: Implement language-specific extraction logic:
        1. Parse import/require/use statements
        2. Optionally parse function calls and symbol references
        3. Return a list of DependencyEdge objects

        Args:
            file_path: Relative path to the source file within the project.
            content: Full text content of the source file.

        Returns:
            List of DependencyEdge instances found in the file.
        """
        return []
