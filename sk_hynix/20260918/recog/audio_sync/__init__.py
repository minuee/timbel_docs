"""Repo-root package shim for src/audio_sync."""
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent.parent / 'src' / 'audio_sync'
__path__ = [str(_pkg_dir)]
