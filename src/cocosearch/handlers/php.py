"""Handler for PHP files.

Adds support for .inc files (commonly used as PHP includes) by mapping
them to the built-in PHP language in CocoIndex's SplitRecursively.

Note: .php is already handled by CocoIndex's built-in PHP support.
This handler extends coverage to .inc files.
"""

import re

import cocoindex


class PhpHandler:
    """Handler for PHP files including .inc extensions."""

    EXTENSIONS = [".inc"]

    SEPARATOR_SPEC = cocoindex.functions.CustomLanguageSpec(
        language_name="php",
        separators_regex=[
            # Level 1: Class and function definitions
            r"\n(?:abstract |final )?class ",
            r"\n\s*(?:public |protected |private |static )*function ",
            # Level 2: Blank lines
            r"\n\n+",
            # Level 3: Single newlines
            r"\n",
            # Level 4: Whitespace (last resort)
            r" ",
        ],
        aliases=["inc"],
    )

    _COMMENT_LINE = re.compile(r"^\s*(?://|#).*$|^\s*/\*.*?\*/\s*$", re.MULTILINE)

    _CLASS_RE = re.compile(
        r"^(?:abstract\s+|final\s+)?class\s+([a-zA-Z_]\w*)"
    )
    _FUNCTION_RE = re.compile(
        r"^(?:public\s+|protected\s+|private\s+|static\s+)*function\s+([a-zA-Z_]\w*)"
    )

    def extract_metadata(self, text: str) -> dict:
        """Extract metadata from PHP chunk.

        Args:
            text: The chunk text content.

        Returns:
            Dict with block_type, hierarchy, and language_id.
        """
        stripped = self._strip_comments(text)

        match = self._CLASS_RE.match(stripped)
        if match:
            name = match.group(1)
            return {
                "block_type": "class",
                "hierarchy": f"class:{name}",
                "language_id": "php",
            }

        match = self._FUNCTION_RE.match(stripped)
        if match:
            name = match.group(1)
            return {
                "block_type": "function",
                "hierarchy": f"function:{name}",
                "language_id": "php",
            }

        return {"block_type": "", "hierarchy": "", "language_id": "php"}

    def _strip_comments(self, text: str) -> str:
        """Strip leading comments from chunk text."""
        from cocosearch.handlers.utils import strip_leading_comments

        return strip_leading_comments(text, [self._COMMENT_LINE])
