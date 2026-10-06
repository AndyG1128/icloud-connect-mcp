"""Durable deduplication, not a guarantee of exactly-once delivery."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import threading
import fcntl
from contextlib import contextmanager
from .errors import ConnectorError, require
from .identities import private_state


class OperationStore:
    def __init__(self, directory, key, namespace="default"):
        require(namespace.isalnum(), "CONFIG", "Invalid ledger namespace.")
        path = private_state(directory) / f"operations-{namespace}.sqlite3"
        self.path = path
        require(not path.is_symlink(), "CONFIG", "Ledger must not be a symlink.")
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600); os.close(fd)
        require(path.stat().st_uid == os.geteuid() and not path.stat().st_mode & 0o077,
                "CONFIG", "Ledger must be private and owned by the service user.")
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, result TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.execute("CREATE TABLE IF NOT EXISTS mail_checkpoints (id TEXT PRIMARY KEY, checkpoint TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS sent_reconciliations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, previous_state TEXT NOT NULL, previous_result TEXT, previous_updated TEXT, evidence TEXT NOT NULL, recorded TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.key, self.lock = key, threading.Lock()

    def operation_digest(self, op_id, tool, arguments):
        require(isinstance(op_id, str) and 1 <= len(op_id) <= 128 and all(32 <= ord(c) < 127 for c in op_id),
                "INVALID_OPERATION_ID", "Use a nonempty operation ID of at most 128 ASCII characters.")
        raw = json.dumps([tool, arguments], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hmac.new(self.key, raw, hashlib.sha256).hexdigest()

    def inspect_existing(self, op_id, tool, arguments):
        digest = self.operation_digest(op_id, tool, arguments)
        with self.lock:
            row = self.db.execute("SELECT digest,state,result,updated FROM operations WHERE id=?", (op_id,)).fetchone()
        require(row is not None, "OPERATION_NOT_FOUND", "Reconciliation requires an existing operation.")
        require(row[0] == digest, "OPERATION_ID_CONFLICT", "Reconciliation inputs differ from the original operation.")
        return row

    def reconcile_sent(self, op_id, previous, checkpoint, result, evidence):
        """Commit verified evidence and prior failure together, without losing history."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                current = self.db.execute("SELECT digest,state,result,updated FROM operations WHERE id=?", (op_id,)).fetchone()
                require(current == previous, "LEDGER_CONFLICT", "Operation changed during read-only reconciliation; no ledger update performed.")
                self.db.execute("INSERT INTO sent_reconciliations (id,previous_state,previous_result,previous_updated,evidence) VALUES (?,?,?,?,?)",
                                (op_id, previous[1], previous[2], previous[3], json.dumps(evidence, sort_keys=True)))
                self.db.execute("UPDATE mail_checkpoints SET checkpoint=? WHERE id=?", (json.dumps(checkpoint, sort_keys=True), op_id))
                self.db.execute("UPDATE operations SET state='succeeded',result=?,updated=CURRENT_TIMESTAMP WHERE id=?",
                                (json.dumps(result, sort_keys=True), op_id))
                self.db.execute("COMMIT")
            except BaseException as error:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                if isinstance(error, ConnectorError):
                    raise
                raise ConnectorError("LEDGER_FAILURE", "Sent reconciliation could not be committed; local changes rolled back and no account writes performed.") from None

    def begin(self, op_id, tool, arguments, *, recover=False):
        digest = self.operation_digest(op_id, tool, arguments)
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute("SELECT digest,state,result FROM operations WHERE id=?", (op_id,)).fetchone()
                if row:
                    require(row[0] == digest, "OPERATION_ID_CONFLICT", "This operation ID was already used with different inputs.")
                    if row[1] == "succeeded":
                        result = json.loads(row[2]); self.db.execute("COMMIT"); return result
                    checkpoint = self.db.execute("SELECT checkpoint FROM mail_checkpoints WHERE id=?", (op_id,)).fetchone()
                    progress = json.loads(checkpoint[0]) if checkpoint else {}
                    if recover and (progress.get("smtp_status") in ("prepared", "accepted") or progress.get("copy_status")):
                        self.db.execute("UPDATE operations SET state='in_progress',updated=CURRENT_TIMESTAMP WHERE id=?", (op_id,))
                        self.db.execute("COMMIT")
                        return None
                    raise ConnectorError("OPERATION_NOT_REPLAYABLE", "Previous operation is incomplete, ambiguous or failed. Inspect its status; automatic replay is prohibited.")
                self.db.execute("INSERT INTO operations (id,digest,state) VALUES (?,?,'in_progress')", (op_id, digest))
                self.db.execute("COMMIT")
                return None
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    @contextmanager
    def exclusive(self, op_id):
        # Held by the worker until it really finishes, including after an async timeout.
        # Account-wide serialization also prevents two connector COPY/APPEND workflows
        # racing each other's destination UID baselines. Other mail clients remain external.
        path = self.path.with_suffix(".mail-lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            require(os.fstat(fd).st_uid == os.geteuid() and not os.fstat(fd).st_mode & 0o077,
                    "CONFIG", "Mail operation lock must be private and operator-owned.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConnectorError("BUSY", "Another mail workflow is active; no new account operation started.") from None
            yield
        finally:
            os.close(fd)

    def checkpoint(self, op_id, value=None):
        with self.lock:
            if value is not None:
                try:
                    self.db.execute("INSERT INTO mail_checkpoints VALUES (?,?) ON CONFLICT(id) DO UPDATE SET checkpoint=excluded.checkpoint",
                                    (op_id, json.dumps(value, sort_keys=True)))
                except Exception:
                    raise ConnectorError("LEDGER_FAILURE", "Mail phase could not be persisted. Stop and reconcile; do not repeat any write.") from None
            row = self.db.execute("SELECT checkpoint FROM mail_checkpoints WHERE id=?", (op_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def finish(self, op_id, state, result):
        require(state in ("succeeded", "failed", "ambiguous"), "INTERNAL", "Invalid operation state.")
        with self.lock:
            self.db.execute("UPDATE operations SET state=?,result=?,updated=CURRENT_TIMESTAMP WHERE id=?",
                            (state, json.dumps(result, sort_keys=True), op_id))

    def status(self, op_id):
        with self.lock:
            row = self.db.execute("SELECT state,result,updated FROM operations WHERE id=?", (op_id,)).fetchone()
            count = self.db.execute("SELECT COUNT(*) FROM sent_reconciliations WHERE id=?", (op_id,)).fetchone()[0]
            history = self.db.execute("SELECT previous_state,previous_result,previous_updated,evidence,recorded FROM sent_reconciliations WHERE id=? ORDER BY sequence DESC LIMIT 20", (op_id,)).fetchall()
        require(row is not None, "OPERATION_NOT_FOUND", "Operation ID is unknown.")
        return {"operation_id": op_id, "state": row[0], "result": json.loads(row[1]) if row[1] else None,
                "mail_checkpoint": {k: v for k, v in (self.checkpoint(op_id) or {}).items() if k not in ("recipe", "envelope")},
                "sent_reconciliation_history": [{"previous_state": h[0], "previous_result": json.loads(h[1]) if h[1] else None,
                    "previous_updated_utc": h[2], "evidence": json.loads(h[3]), "recorded_utc": h[4]} for h in reversed(history)],
                "sent_reconciliation_history_total": count,
                "updated_utc": row[2], "automatic_retry": False,
                "warning": "in_progress after a crash may have affected the account; reconcile before a new operation."}
