"""Audio sync merge service MVP.

Keep package import side effects minimal so shared adapters can import
`recog.models` without triggering the full API/pipeline stack and causing
circular imports with `audio_sync.export`.
"""

__all__ = ["AudioSyncPipeline", "SessionStore", "create_app"]


def __getattr__(name: str):
    if name == "create_app":
        from .api import create_app

        return create_app
    if name == "AudioSyncPipeline":
        from .pipeline import AudioSyncPipeline

        return AudioSyncPipeline
    if name == "SessionStore":
        from .store import SessionStore

        return SessionStore
    raise AttributeError(name)
