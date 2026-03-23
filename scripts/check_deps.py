#!/usr/bin/env python3
"""Verify all third-party imports in src/ are listed in requirements.txt.

Catches missing dependencies BEFORE CI tests run — prevents the class of
failure where code works locally (package installed globally) but breaks in
CI (only requirements.txt packages installed).

Usage:
    python scripts/check_deps.py        # exits 0 if ok, 1 if missing
    python scripts/check_deps.py -v     # verbose: list all found imports

Exit code 1 = missing dependency → CI should fail early with clear message.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Map Python import names → pip package names (only non-obvious ones)
IMPORT_TO_PKG = {
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "gi": "PyGObject",
    "fitz": "pymupdf",
}

# Imports that are optional (guarded by try/except in the code)
OPTIONAL_IMPORTS = {"playwright"}

# Standard library modules (Python 3.9+)
STDLIB = {
    "__future__", "abc", "argparse", "ast", "asyncio", "atexit", "base64",
    "bisect", "builtins", "calendar", "cmath", "cmd", "codecs", "collections",
    "colorsys", "compileall", "concurrent", "configparser", "contextlib",
    "copy", "copyreg", "cProfile", "csv", "ctypes", "dataclasses", "datetime",
    "decimal", "difflib", "dis", "distutils", "doctest", "email", "encodings",
    "enum", "errno", "faulthandler", "filecmp", "fileinput", "fnmatch",
    "fractions", "ftplib", "functools", "gc", "getopt", "getpass", "gettext",
    "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "linecache", "locale", "logging", "lzma", "mailbox", "math", "mimetypes",
    "mmap", "multiprocessing", "netrc", "numbers", "operator", "os",
    "pathlib", "pdb", "pickle", "pkgutil", "platform", "plistlib", "poplib",
    "posixpath", "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
    "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtpd",
    "smtplib", "sndhdr", "socket", "socketserver", "sqlite3", "ssl", "stat",
    "statistics", "string", "stringprep", "struct", "subprocess", "sunau",
    "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
    "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib",
    "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "_thread",
}


def find_third_party_imports(src_dir: Path) -> set[str]:
    """AST-parse all .py files in src_dir and return third-party import names."""
    imports = set()
    for f in src_dir.glob("*.py"):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            print(f"  ⚠️  Syntax error in {f} — skipping", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.module.startswith("src"):
                    imports.add(node.module.split(".")[0])
    # Filter to third-party only
    return imports - STDLIB - {"src"}


def parse_requirements(req_path: Path) -> set[str]:
    """Parse requirements.txt into a set of lowercase package names."""
    pkgs = set()
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers: "requests>=2.31.0" → "requests"
        name = line.split(">=")[0].split("<=")[0].split("==")[0].split("~=")[0].split("!=")[0].split("[")[0].strip()
        pkgs.add(name.lower())
    return pkgs


def main() -> int:
    verbose = "-v" in sys.argv

    project_root = Path(__file__).resolve().parent.parent
    src_dir = project_root / "src"
    req_path = project_root / "requirements.txt"

    if not req_path.exists():
        print("❌ requirements.txt not found", file=sys.stderr)
        return 1

    third_party = find_third_party_imports(src_dir)
    requirements = parse_requirements(req_path)

    if verbose:
        print(f"Third-party imports found in src/: {sorted(third_party)}")
        print(f"Packages in requirements.txt: {sorted(requirements)}")

    missing = []
    for imp in sorted(third_party):
        if imp in OPTIONAL_IMPORTS:
            if verbose:
                print(f"  ⚠️  {imp} — optional (guarded by try/except)")
            continue

        # Check if the import or its pip name is in requirements
        pkg_name = IMPORT_TO_PKG.get(imp, imp).lower()
        if pkg_name not in requirements and imp.lower() not in requirements:
            missing.append((imp, pkg_name))

    if missing:
        print("❌ Missing dependencies in requirements.txt:")
        for imp, pkg in missing:
            print(f"   {imp} → pip install {pkg}")
        print(f"\nAdd these to requirements.txt to fix CI.")
        return 1

    print(f"✅ All {len(third_party)} third-party imports covered by requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
