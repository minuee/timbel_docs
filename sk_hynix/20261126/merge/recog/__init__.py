"""Repo-root package shim for src/recog."""
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent.parent / 'src' / 'recog'
__path__ = [str(_pkg_dir)]
