"""Layered financial glossary: a versioned local YAML, matched in memory (no network at runtime)."""

from .matcher import Glossary, Term, TermHit, load_glossary

__all__ = ["Glossary", "Term", "TermHit", "load_glossary"]
