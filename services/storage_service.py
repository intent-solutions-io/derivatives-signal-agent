"""
Storage service — thin wrapper selecting backend from config.
"""

import logging
import json
from typing import Optional

from config.schema import StorageConfig, StorageBackendType
from storage.base import StorageBackend
from storage.sqlite_backend import SQLiteBackend
from storage.supabase_backend import SupabaseBackend

logger = logging.getLogger(__name__)


def create_storage(config: StorageConfig) -> StorageBackend:
    """Create storage backend from config."""
    if config.backend == StorageBackendType.SUPABASE:
        logger.info(json.dumps({
            "severity": "INFO",
            "component": "storage_service",
            "event": "backend_selected",
            "backend": "supabase",
        }))
        return SupabaseBackend(table_name=config.supabase.table_name)
    else:
        logger.info(json.dumps({
            "severity": "INFO",
            "component": "storage_service",
            "event": "backend_selected",
            "backend": "sqlite",
            "path": config.sqlite.path,
        }))
        return SQLiteBackend(db_path=config.sqlite.path)
