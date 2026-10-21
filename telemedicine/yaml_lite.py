"""A small reader for flat YAML files.

The project has **one dependency**, and it is the PostgreSQL driver. A YAML
library would be a second one, so the two configuration files that need one
read it by hand.

What this reads: a flat mapping of ``key: value`` lines, with ``#`` comments
and blank lines. The key may contain dots, so that a file can group things
by a prefix (``sendgrid.host: api.sendgrid.com``).

What this does not read: lists, nested mappings, quoted strings, multi-line
values. A file that needs them is a file that needs a YAML library, and the
right answer then is to add the dependency rather than to grow this.

**It reads strictly.** An unknown key, a missing key, a value of the wrong
type or a line that is not a key and a value is an error, not something
quietly ignored. The files this reads decide what is deleted from a
patient's record and where their data may go, and a configuration that is
half-read is one nobody can rely on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Type


class ConfigurationError(ValueError):
    """The file could not be read, or does not make sense."""


def read_flat_yaml(text: str, path="the file") -> Dict[str, str]:
    """The keys of a flat ``key: value`` file.

    The values are returned as they were written, with the comments removed
    and the surrounding space taken off. The caller decides what type each
    one is, and says so.
    """
    values: Dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ConfigurationError(
                f"{path}:{number}: this is not a 'key: value' line: {stripped!r}")
        key, _, raw = stripped.partition(":")
        key = key.strip()
        raw = strip_comment(raw).strip()
        if not key:
            raise ConfigurationError(f"{path}:{number}: the key is empty")
        if key in values:
            raise ConfigurationError(f"{path}:{number}: '{key}' is set twice")
        values[key] = raw
    return values


def read_flat_yaml_file(path) -> Dict[str, str]:
    """The keys of a flat ``key: value`` file, read from disk."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"{path}: the file does not exist")
    return read_flat_yaml(path.read_text(encoding="utf-8"), path)


def strip_comment(value: str) -> str:
    """Drop a trailing ``# comment``.

    A ``#`` only starts a comment when it is at the start of the value or
    after a space, so that a value may contain one.
    """
    if value.startswith("#"):
        return ""
    position = value.find(" #")
    if position >= 0:
        return value[:position]
    return value


def as_bool(value: str, key: str, path="the file") -> bool:
    """A value that has to be true or false."""
    lowered = str(value).strip().lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    raise ConfigurationError(f"{path}: '{key}' must be true or false, not {value!r}")


def as_int(value: str, key: str, path="the file") -> int:
    """A value that has to be a whole number."""
    try:
        return int(str(value).strip())
    except ValueError:
        raise ConfigurationError(
            f"{path}: '{key}' must be a whole number, not {value!r}") from None


def as_optional_int(value: str, key: str, path="the file") -> Optional[int]:
    """A value that has to be a whole number, or nothing."""
    if not str(value).strip():
        return None
    return as_int(value, key, path)


def group_by_prefix(values: Dict[str, str], separator: str = ".") -> Dict[str, Dict[str, str]]:
    """The keys, grouped by the part before the first dot.

    ``{"sendgrid.host": "x"}`` becomes ``{"sendgrid": {"host": "x"}}``. A key
    with no dot is a group of its own, under its own name.
    """
    grouped: Dict[str, Dict[str, str]] = {}
    for key, value in values.items():
        name, _, rest = key.partition(separator)
        if not rest:
            grouped.setdefault(name, {})["_"] = value
            continue
        grouped.setdefault(name, {})[rest] = value
    return grouped
