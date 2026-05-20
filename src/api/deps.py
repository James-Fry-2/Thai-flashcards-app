from src.db.database import get_db  # re-export for routes
from src.config.settings import get_settings, Settings
from fastapi import Depends

__all__ = ["get_db", "get_settings", "Settings"]
