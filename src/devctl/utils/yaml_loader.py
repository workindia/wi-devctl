"""YAML loading utilities."""

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    """Load YAML from a file path."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
