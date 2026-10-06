import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from .errors import require


def private_state(directory):
    p = Path(directory)
    require(not p.is_symlink(), "CONFIG", "State directory must not be a symlink.")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = p.stat()
    require(s.st_uid == os.geteuid() and not s.st_mode & 0o077, "CONFIG",
            "State directory must be owned by the service user with mode 0700.")
    return p


def persistent_key(directory):
    p = private_state(directory) / "identity.key"
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32)); f.flush(); os.fsync(f.fileno())
    except FileExistsError:
        pass
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        s = os.fstat(f.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_uid == os.geteuid() and not s.st_mode & 0o077,
                "CONFIG", "Identity key must be private and owned by the service user.")
        key = f.read(33)
    require(len(key) == 32, "CONFIG", "Invalid identity key.")
    return key


class Identities:
    def __init__(self, key, account):
        self.key = key
        self.account = hashlib.sha256(account.casefold().encode()).hexdigest()[:24]

    def issue(self, kind, **fields):
        raw = json.dumps(dict(v=1, kind=kind, account=self.account, **fields),
                         sort_keys=True, separators=(",", ":")).encode()
        tag = hmac.digest(self.key, raw, "sha256")
        return base64.urlsafe_b64encode(raw + tag).decode().rstrip("=")

    def decode(self, ref, kind):
        require(isinstance(ref, str) and len(ref) <= 8192, "INVALID_REFERENCE", "Invalid resource reference.")
        try:
            data = base64.b64decode(ref + "=" * (-len(ref) % 4), altchars=b"-_", validate=True)
            raw, tag = data[:-32], data[-32:]
            valid = hmac.compare_digest(hmac.digest(self.key, raw, "sha256"), tag)
            obj = json.loads(raw) if valid else {}
        except (ValueError, UnicodeError):
            obj = {}
        require(obj.get("v") == 1 and obj.get("account") == self.account and obj.get("kind") == kind,
                "INVALID_REFERENCE", "Reference is invalid or belongs to another account or server.")
        return obj
