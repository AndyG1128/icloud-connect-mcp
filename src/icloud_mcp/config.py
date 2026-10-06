"""Operator-only configuration; never inspect another application's configuration."""
from dataclasses import dataclass, field
from pathlib import Path
from email.utils import parseaddr
import os
import stat
import tomllib
from zoneinfo import ZoneInfo
from .errors import require


@dataclass(frozen=True)
class Config:
    profile: str = "read-only"
    timezone: str = "UTC"
    account_email: str = ""
    username: str = ""
    password_file: str = ""
    state_dir: str = field(default_factory=lambda: str(Path(os.getenv("XDG_STATE_HOME", str(Path.home()/".local/state")))/"icloud-mcp"))
    permissions: tuple[str, ...] | None = None
    folders: tuple[str, ...] | None = None
    calendars: tuple[str, ...] | None = None
    permanent_expunge: bool = False
    sent_folder: str = "Sent Messages"
    timeout_seconds: int = 30
    max_results: int = 100
    max_message_bytes: int = 25_000_000
    max_page_chars: int = 16_000
    max_attachment_chunk: int = 48_000
    max_date_days: int = 366
    max_calendar_resources: int = 2_000
    max_event_bytes: int = 2_000_000
    imap_host: str = field(default="imap.mail.me.com", init=False)
    smtp_host: str = field(default="smtp.mail.me.com", init=False)
    caldav_url: str = field(default="https://caldav.icloud.com/", init=False)

    def __post_init__(self):
        require(self.profile in ("read-only", "full-access"), "CONFIG", "Unknown access profile.")
        require(isinstance(self.sent_folder, str) and 0 < len(self.sent_folder) <= 1024 and
                not any(c in self.sent_folder for c in "\r\n\x00"), "CONFIG", "Invalid canonical Sent folder.")
        ZoneInfo(self.timezone)
        require(1 <= self.timeout_seconds <= 120, "CONFIG", "Timeout must be 1–120 seconds.")
        bounds = {"max_results": (1, 1000), "max_message_bytes": (1024, 100_000_000),
                  "max_page_chars": (256, 100_000), "max_attachment_chunk": (1024, 1_000_000),
                  "max_date_days": (1, 3660), "max_calendar_resources": (1, 10_000),
                  "max_event_bytes": (1024, 10_000_000)}
        for k, (lo, hi) in bounds.items():
            require(lo <= getattr(self, k) <= hi, "CONFIG", f"Invalid {k} limit.")
        if self.account_email:
            require(parseaddr(self.account_email)[1] == self.account_email and
                    "@" in self.account_email and not any(c in self.account_email for c in "\r\n\x00"),
                    "CONFIG", "Configure a single account email address.")
        for k in ("permissions", "folders", "calendars"):
            value = getattr(self, k)
            require(value is None or all(isinstance(x, str) for x in value), "CONFIG", f"Invalid {k}.")

    def password(self):
        require(bool(self.account_email and self.username and self.password_file), "NOT_CONFIGURED",
                "Configure this connector's own iCloud account and protected app-password file.")
        p = Path(self.password_file)
        require(not p.is_symlink(), "CREDENTIALS", "Credential file must not be a symlink.")
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            s = os.fstat(fd)
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.geteuid() and
                    not s.st_mode & 0o077 and s.st_nlink == 1 and s.st_size <= 1024,
                    "CREDENTIALS", "Credential file must be private and owned by the service user.")
            with os.fdopen(fd, "r") as f:
                fd = -1
                value = f.read().strip()
            require(bool(value), "CREDENTIALS", "Credential file is empty.")
            return value
        finally:
            if fd >= 0:
                os.close(fd)


def load_config(path: str | None = None):
    selected = path or os.getenv("ICLOUD_MCP_CONFIG")
    if not selected:
        return Config()
    fd = os.open(selected, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        s = os.fstat(f.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_uid in (0, os.geteuid()) and not s.st_mode & 0o022,
                "CONFIG", "Operator config must be owned by the operator/root and not writable by others.")
        data = tomllib.load(f)
    for k in ("permissions", "folders", "calendars"):
        if k in data:
            data[k] = tuple(data[k])
    return Config(**data)
