"""Small atomic JSON checkpoint store for resumable, single-runner jobs.

This module deliberately handles state only. The caller is responsible for
persisting the JSON file to the repository (for example, by committing it after
a successful batch) and for ensuring only one writer runs at a time.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointStore:
    """Store item status keyed by a stable source item ID.

    Example:
        store = CheckpointStore("database/processed.json")
        if not store.is_completed("item-123"):
            store.mark_processing("item-123", title="Example")
            # perform work and verify the remote upload
            store.mark_completed(
                "item-123",
                title="Example",
                destination_message_id=12345,
            )
    """

    VALID_STATUSES = {"pending", "processing", "completed", "failed"}

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {"schema_version": 1, "items": {}}
        self.load()

    def load(self) -> dict[str, Any]:
        """Load the checkpoint file; initialize an empty database if absent."""
        if not self.path.exists():
            self.data = {"schema_version": 1, "items": {}}
            return self.data

        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)

        if not isinstance(loaded, dict) or not isinstance(loaded.get("items"), dict):
            raise ValueError(f"Invalid checkpoint database format: {self.path}")

        self.data = {
            "schema_version": int(loaded.get("schema_version", 1)),
            "items": loaded["items"],
        }
        return self.data

    def get(self, item_id: str) -> dict[str, Any] | None:
        item = self.data["items"].get(str(item_id))
        return dict(item) if isinstance(item, dict) else None

    def is_completed(self, item_id: str) -> bool:
        item = self.get(item_id)
        return bool(item and item.get("status") == "completed")

    def mark(
        self,
        item_id: str,
        status: str,
        *,
        title: str | None = None,
        error: str | None = None,
        destination_message_id: int | str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update one item and atomically write the local JSON file."""
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Unsupported status: {status!r}")

        key = str(item_id).strip()
        if not key:
            raise ValueError("item_id must not be empty")

        previous = self.data["items"].get(key, {})
        record: dict[str, Any] = {
            **(previous if isinstance(previous, dict) else {}),
            "item_id": key,
            "status": status,
            "updated_at": _utc_now(),
            "attempts": int(previous.get("attempts", 0)) if isinstance(previous, dict) else 0,
        }
        if status == "processing":
            record["attempts"] += 1
            record["started_at"] = _utc_now()
            record.pop("error", None)
        if status == "completed":
            record["completed_at"] = _utc_now()
            record.pop("error", None)
        if title is not None:
            record["title"] = title
        if error is not None:
            record["error"] = error[:2000]
        if destination_message_id is not None:
            record["destination_message_id"] = str(destination_message_id)
        if extra:
            record["extra"] = extra

        self.data["items"][key] = record
        self.save()
        return dict(record)

    def mark_processing(self, item_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.mark(item_id, "processing", **kwargs)

    def mark_completed(self, item_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.mark(item_id, "completed", **kwargs)

    def mark_failed(self, item_id: str, error: str, **kwargs: Any) -> dict[str, Any]:
        return self.mark(item_id, "failed", error=error, **kwargs)

    def pending_ids(self) -> list[str]:
        """Return IDs that are not completed, including interrupted processing items."""
        return [
            item_id
            for item_id, record in self.data["items"].items()
            if not isinstance(record, dict) or record.get("status") != "completed"
        ]

    def summary(self) -> dict[str, int]:
        counts = {status: 0 for status in self.VALID_STATUSES}
        for record in self.data["items"].values():
            status = record.get("status") if isinstance(record, dict) else None
            if status in counts:
                counts[status] += 1
        counts["total"] = len(self.data["items"])
        return counts

    def save(self) -> None:
        """Write atomically so interruption cannot leave a partially-written JSON file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            try:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
            except OSError:
                pass
