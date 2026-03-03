"""Tests for cocosearch.handlers.php module."""

import pytest

from cocosearch.handlers.php import PhpHandler


@pytest.mark.unit
class TestPhpHandlerExtensions:
    """Tests for PhpHandler EXTENSIONS."""

    def test_extensions_contains_inc(self):
        """EXTENSIONS should contain .inc."""
        handler = PhpHandler()
        assert ".inc" in handler.EXTENSIONS


@pytest.mark.unit
class TestPhpHandlerSeparatorSpec:
    """Tests for PhpHandler SEPARATOR_SPEC."""

    def test_language_name_is_php(self):
        """SEPARATOR_SPEC.language_name should be 'php'."""
        handler = PhpHandler()
        assert handler.SEPARATOR_SPEC.language_name == "php"

    def test_aliases_contains_inc(self):
        """SEPARATOR_SPEC.aliases should contain 'inc'."""
        handler = PhpHandler()
        assert "inc" in handler.SEPARATOR_SPEC.aliases

    def test_has_separators(self):
        """SEPARATOR_SPEC should have a non-empty separators_regex list."""
        handler = PhpHandler()
        assert len(handler.SEPARATOR_SPEC.separators_regex) > 0

    def test_no_lookaheads_in_separators(self):
        """PHP separators must not contain lookahead or lookbehind patterns."""
        handler = PhpHandler()
        for sep in handler.SEPARATOR_SPEC.separators_regex:
            assert "(?=" not in sep, f"Lookahead found in PHP separator: {sep}"
            assert "(?<=" not in sep, f"Lookbehind found in PHP separator: {sep}"
            assert "(?!" not in sep, (
                f"Negative lookahead found in PHP separator: {sep}"
            )
            assert "(?<!" not in sep, (
                f"Negative lookbehind found in PHP separator: {sep}"
            )


@pytest.mark.unit
class TestPhpHandlerExtractMetadata:
    """Tests for PhpHandler.extract_metadata()."""

    def test_class_definition(self):
        """Class definition is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("class UserController {")
        assert m["block_type"] == "class"
        assert m["hierarchy"] == "class:UserController"
        assert m["language_id"] == "php"

    def test_abstract_class(self):
        """Abstract class definition is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("abstract class BaseModel {")
        assert m["block_type"] == "class"
        assert m["hierarchy"] == "class:BaseModel"
        assert m["language_id"] == "php"

    def test_final_class(self):
        """Final class definition is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("final class Config {")
        assert m["block_type"] == "class"
        assert m["hierarchy"] == "class:Config"
        assert m["language_id"] == "php"

    def test_public_function(self):
        """Public function is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("public function getUser() {")
        assert m["block_type"] == "function"
        assert m["hierarchy"] == "function:getUser"
        assert m["language_id"] == "php"

    def test_private_static_function(self):
        """Private static function is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("private static function getInstance() {")
        assert m["block_type"] == "function"
        assert m["hierarchy"] == "function:getInstance"
        assert m["language_id"] == "php"

    def test_plain_function(self):
        """Plain function (no visibility modifier) is recognized."""
        handler = PhpHandler()
        m = handler.extract_metadata("function helper() {")
        assert m["block_type"] == "function"
        assert m["hierarchy"] == "function:helper"
        assert m["language_id"] == "php"

    def test_comment_before_function(self):
        """Comment line before function definition is correctly skipped."""
        handler = PhpHandler()
        m = handler.extract_metadata("// Get the user\npublic function getUser() {")
        assert m["block_type"] == "function"
        assert m["hierarchy"] == "function:getUser"
        assert m["language_id"] == "php"

    def test_non_function_content_returns_empty(self):
        """Non-function content produces empty block_type and hierarchy."""
        handler = PhpHandler()
        m = handler.extract_metadata('$x = new Foo();')
        assert m["block_type"] == ""
        assert m["hierarchy"] == ""
        assert m["language_id"] == "php"

    def test_leading_newline(self):
        """Leading newline from separator split is handled."""
        handler = PhpHandler()
        m = handler.extract_metadata("\nfunction deploy() {")
        assert m["block_type"] == "function"
        assert m["hierarchy"] == "function:deploy"
        assert m["language_id"] == "php"
