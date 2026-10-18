"""Versioned prompt templates in prompts/*.md with {{placeholders}}.

The version is a short hash of the file: stored with every call/generation so any output can be
traced back to the exact prompt that produced it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    template: str
    version: str

    def render(self, **values: object) -> str:
        missing = set(_VAR.findall(self.template)) - set(values)
        if missing:
            raise KeyError(f"prompt {self.name}: faltam variáveis {sorted(missing)}")
        return _VAR.sub(lambda m: str(values[m.group(1)]), self.template)


@cache
def load_prompt(name: str, directory: Path = PROMPTS_DIR) -> Prompt:
    text = (directory / f"{name}.md").read_text(encoding="utf-8")
    version = f"{name}@{hashlib.sha256(text.encode()).hexdigest()[:10]}"
    return Prompt(name=name, template=text, version=version)
