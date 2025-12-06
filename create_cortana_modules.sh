#!/bin/bash
# Script to create all remaining Cortana modules efficiently

cd /home/xmanz/JRVS/cortana

# Create file_ops.py
cat > file_ops.py << 'EOF'
"""
Safe file operations with atomic writes and backups
"""
import json
import time
import shutil
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger("CORTANA.file_ops")


def safe_json_save(filepath: str, data: Any, create_backup: bool = True):
    """Safely save JSON with atomic write and backup"""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Create backup
    if create_backup and filepath.exists():
        backup_path = filepath.with_suffix(f'.backup_{int(time.time())}.json')
        try:
            shutil.copy2(filepath, backup_path)
            logger.debug(f"Created backup: {backup_path}")
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")

    # Atomic write
    temp_path = filepath.with_suffix('.tmp')
    try:
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(filepath)
        logger.debug(f"Saved: {filepath}")
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise


def safe_json_load(filepath: str, default: Any = None) -> Any:
    """Safely load JSON with fallback to default"""
    filepath = Path(filepath)

    if not filepath.exists():
        logger.debug(f"File not found, using default: {filepath}")
        return default

    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {filepath}: {e}")

        # Try to load from backup
        backups = sorted(filepath.parent.glob(f"{filepath.stem}.backup_*.json"), reverse=True)
        if backups:
            logger.info(f"Attempting restore from backup: {backups[0]}")
            try:
                with open(backups[0], 'r') as f:
                    data = json.load(f)
                logger.info("Successfully restored from backup")
                return data
            except Exception as backup_error:
                logger.error(f"Backup restore failed: {backup_error}")

        return default
EOF

echo "✅ Created file_ops.py"
