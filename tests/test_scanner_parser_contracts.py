from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

from astra.models.file_node import FileCategory
from astra.parser import registry as registry_module
from astra.parser.registry import ParserRegistry, _JSTSTreeSitterAdapter
from astra.scanner.binary_detector import BinaryDetector
from astra.scanner.hash_engine import HashEngine
from astra.scanner.language_detector import LanguageDetector
from astra.scanner.metadata_extractor import MetadataExtractor


def _extractor(root, max_kb=64):
    return MetadataExtractor(
        str(root),
        LanguageDetector(),
        BinaryDetector(),
        HashEngine(),
        max_file_size_kb=max_kb,
    )


def test_metadata_extractor_returns_stable_metadata_and_hidden_flag(tmp_path):
    source = tmp_path / ".config" / "main.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    extractor = _extractor(tmp_path)
    metadata, error = extractor.extract(
        str(source), ".config/main.py", FileCategory.SOURCE
    )

    assert error is None
    assert metadata is not None
    assert metadata.language == "python"
    assert metadata.extension == ".py"
    assert metadata.kind.value == "text"
    assert metadata.is_hidden is True
    assert metadata.lines_count == 1
    assert metadata.rel_path == ".config/main.py"
    assert metadata.id == extractor.deterministic_id(".CONFIG\\MAIN.PY")
    assert metadata.id == extractor.deterministic_id(".config/main.py")


def test_metadata_extractor_skips_oversized_files(tmp_path):
    source = tmp_path / "large.py"
    source.write_text("x" * 2048, encoding="utf-8")
    metadata, error = _extractor(tmp_path, max_kb=1).extract(
        str(source), "large.py", FileCategory.SOURCE
    )
    assert metadata is None
    assert error == "file exceeds max_file_size_kb"


def test_metadata_extractor_handles_binary_and_latin1_profiles(tmp_path):
    binary = tmp_path / "image.bin"
    binary.write_bytes(b"\x00\x01\x02")
    metadata, error = _extractor(tmp_path).extract(
        str(binary), "image.bin", FileCategory.ASSET
    )
    assert error is None
    assert metadata is not None and metadata.is_binary
    assert metadata.encoding == ""
    assert metadata.lines_count == 0

    legacy = tmp_path / "legacy.txt"
    legacy.write_bytes(b"caf\xe9\n")
    metadata, error = _extractor(tmp_path).extract(
        str(legacy), "legacy.txt", FileCategory.DOCUMENT
    )
    assert error is None
    assert metadata is not None
    assert metadata.encoding == "latin-1"
    assert metadata.lines_count == 1


def test_metadata_extractor_text_profile_stops_after_os_error(tmp_path, monkeypatch):
    source = tmp_path / "unreadable.txt"
    source.write_text("text", encoding="utf-8")
    extractor = _extractor(tmp_path)
    original_open = builtins.open

    def fail_open(path, *args, **kwargs):
        if str(path) == str(source):
            raise OSError("permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)
    assert extractor._text_profile(str(source), False) == ("", 0)


class FakeAdapter:
    language = "sample"
    file_extensions = (".SMP",)

    def can_parse(self, file_path):
        return file_path.lower().endswith(".smp")

    def parse(self, file_path, content):
        return SimpleNamespace(file_path=file_path, content=content)


def test_parser_registry_normalizes_extensions_and_dispatches():
    registry = ParserRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)

    assert registry.get_by_language("sample") is adapter
    assert registry.get_by_language("missing") is None
    assert registry.get_by_file_path("src/MAIN.SMP") is adapter
    assert registry.can_parse("src/MAIN.SMP")
    assert not registry.can_parse("README.md")
    parsed = registry.parse("src/MAIN.SMP", "content")
    assert parsed.file_path == "src/MAIN.SMP"
    assert parsed.content == "content"
    assert registry.parse("README.md", "ignored") is None
    assert registry.supported_languages() == ("sample",)
    assert registry.supported_extensions() == (".smp",)



def test_parser_registry_global_instance_is_cached(monkeypatch):
    sentinel = ParserRegistry()
    monkeypatch.setattr(registry_module, "_global_registry", None)
    monkeypatch.setattr(
        registry_module, "build_default_parser_registry", lambda: sentinel
    )
    assert registry_module.get_parser_registry() is sentinel
    assert registry_module.get_parser_registry() is sentinel


def test_js_ts_adapter_dispatches_by_extension(monkeypatch):
    class FakeTreeSitterAdapter:
        def __init__(self, language):
            self.language = language

        def parse(self, file_path, content):
            return self.language, file_path, content

    monkeypatch.setattr(
        "astra.parser.tree_sitter_adapter.TreeSitterAdapter",
        FakeTreeSitterAdapter,
    )
    fake_language_pack = SimpleNamespace(
        SupportedLanguage=str,
        get_parser=lambda language: object(),
    )
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", fake_language_pack)

    adapter = _JSTSTreeSitterAdapter()
    assert adapter.can_parse("component.TSX")
    assert not adapter.can_parse("component.vue")
    assert adapter.parse("component.tsx", "code")[0] == "tsx"
    assert adapter.parse("component.ts", "code")[0] == "typescript"
    assert adapter.parse("component.jsx", "code")[0] == "javascript"


def test_js_ts_adapter_falls_back_when_tsx_grammar_is_unavailable(monkeypatch):
    class FakeTreeSitterAdapter:
        def __init__(self, language):
            self.language = language

        def parse(self, file_path, content):
            return self.language

    monkeypatch.setattr(
        "astra.parser.tree_sitter_adapter.TreeSitterAdapter",
        FakeTreeSitterAdapter,
    )

    def get_parser(language):
        if language == "tsx":
            return None
        return object()

    monkeypatch.setitem(
        sys.modules,
        "tree_sitter_language_pack",
        SimpleNamespace(SupportedLanguage=str, get_parser=get_parser),
    )
    adapter = _JSTSTreeSitterAdapter()
    assert adapter._tsx is None
    assert adapter.parse("component.tsx", "code") == "typescript"


def test_js_ts_adapter_handles_grammar_probe_failure(monkeypatch):
    def fail_get_parser(language):
        raise RuntimeError("missing")

    monkeypatch.setitem(
        sys.modules,
        "tree_sitter_language_pack",
        SimpleNamespace(SupportedLanguage=str, get_parser=fail_get_parser),
    )
    assert not _JSTSTreeSitterAdapter._has_parser("javascript")
