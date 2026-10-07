"""Versioned operational records sharing the protected action journal transaction boundary."""
from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from nanobot.security.actions import ActionStore, now_ms


class RuntimeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    id: str
    revision: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


_RecordT = TypeVar("_RecordT", bound=RuntimeRecord)


class RecordStore(Generic[_RecordT]):
    def __init__(self, namespace: str, model: type[_RecordT], journal: ActionStore | None = None):
        self.journal = journal or ActionStore()
        self.namespace, self.model = namespace, model
        with self.journal.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (namespace TEXT, id TEXT, revision INTEGER NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))")

    def get(self, record_id: str) -> _RecordT:
        with self.journal.transaction() as db:
            row = db.execute("SELECT record FROM records WHERE namespace=? AND id=?", (self.namespace, record_id)).fetchone()
        if row is None:
            raise ValueError("Unknown runtime record")
        return self.model.model_validate_json(row[0])

    def list(self) -> list[_RecordT]:
        with self.journal.transaction() as db:
            rows = db.execute("SELECT record FROM records WHERE namespace=? ORDER BY id", (self.namespace,)).fetchall()
        return [self.model.model_validate_json(row[0]) for row in rows]

    def create(self, record: _RecordT) -> _RecordT:
        with self.journal.transaction() as db:
            db.execute("INSERT INTO records VALUES (?,?,?,?)", (self.namespace, record.id, record.revision, record.model_dump_json()))
        return record.model_copy(deep=True)

    def save(self, record: _RecordT) -> _RecordT:
        updated = record.model_copy(deep=True)
        updated.revision += 1
        updated.updated_at = now_ms()
        with self.journal.transaction() as db:
            cursor = db.execute("UPDATE records SET revision=?,record=? WHERE namespace=? AND id=? AND revision=?",
                                (updated.revision, updated.model_dump_json(), self.namespace, record.id, record.revision))
            if cursor.rowcount != 1:
                raise ValueError("Runtime record revision conflict")
        return updated
