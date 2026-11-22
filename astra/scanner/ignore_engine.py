import os
import fnmatch
from astra.core.constants import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTENSIONS
from astra.core.logger import get_logger

logger = get_logger("astra.scanner.ignore_engine")


class IgnoreEngine:
    def __init__(self, root_path, respect_astraignore: bool = True, respect_gitignore: bool = False):
        self._root = root_path
        self._dir_patterns = set(DEFAULT_IGNORE_DIRS)
        self._ext_patterns = set(DEFAULT_IGNORE_EXTENSIONS)
        self._custom_patterns: list[str] = []
        if respect_astraignore:
            self._load_astraignore()
        if respect_gitignore:
            self._load_gitignore()

    def _load_patterns(self, filename):
        ignore_path = os.path.join(self._root, filename)
        if not os.path.isfile(ignore_path):
            return
        try:
            with open(ignore_path, "r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip().replace("\\", "/")
                    if not line or line.startswith("#") or line.startswith("!"):
                        continue
                    self._custom_patterns.append(line.lstrip("/").rstrip("/"))
        except OSError as exc:
            logger.warning("could not read %s: %s", ignore_path, exc)

    def _load_astraignore(self):
        self._load_patterns(".astraignore")

    def _load_gitignore(self):
        self._load_patterns(".gitignore")

    def is_ignored(self, rel_path):
        parts = rel_path.replace("\\", "/").split("/")
        for part in parts:
            if any(fnmatch.fnmatch(part, pattern) for pattern in self._dir_patterns):
                return True
        for pattern in self._custom_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        ext = os.path.splitext(rel_path)[1]
        return ext in self._ext_patterns

    def is_ignored_dir(self, dir_name):
        if any(fnmatch.fnmatch(dir_name, pattern) for pattern in self._dir_patterns):
            return True
        return any(fnmatch.fnmatch(dir_name, pattern) for pattern in self._custom_patterns)

    def is_ignored_extension(self, extension):
        return extension in self._ext_patterns
