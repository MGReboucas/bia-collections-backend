# Re-export settings from core so new code can import from app.config
from app.core.config import settings  # noqa: F401

__all__ = ["settings"]
