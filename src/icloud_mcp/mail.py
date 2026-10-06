"""IMAPClient owns wire quoting/UTF-7. All public reads select EXAMINE and PEEK."""
import base64
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
import imaplib
import json
from imapclient import IMAPClient as BaseIMAPClient
from .errors import ConnectorError, require


class NegativeIMAPResponse(Exception):
    """A checked tagged NO response, without its potentially private diagnostic."""


class IMAPClient(BaseIMAPClient):
    def _check_resp(self, expected, command, typ, data):
        if expected == "OK" and typ == "NO":
            raise NegativeIMAPResponse()
        return super()._check_resp(expected, command, typ, data)


class Mail:
    def __init__(self, config, permissions, identities, factory=None):
        self.config, self.permissions, self.ids = config, permissions, identities
        self.factory = factory

    @contextmanager
    def connection(self):
        if self.factory:
            client = self.factory()
        else:
            password = self.config.password()
            client = IMAPClient(self.config.imap_host, ssl=True, use_uid=True, timeout=self.config.timeout_seconds)
            client.normalise_times = False
            try:
                # iCloud IMAP authenticates with the mail address, whereas
                # CalDAV uses the Apple Account login (which may be Outlook).
                client.login(self.config.account_email, password)
            except BaseException:
                client.shutdown(); raise
        try:
            yield client
        finally:
            # LOGOUT or shutdown never calls CLOSE/EXPUNGE.
            try:
                client.logout()
            except Exception:
                client.shutdown()

    def folders(self, client):
        out = []
        for flags, delimiter, name in client.list_folders():
            flags = [x.decode("ascii", "replace") if isinstance(x, bytes) else x for x in flags]
            if "\\Noselect" not in flags:
                out.append({"folder": name, "delimiter": delimiter.decode() if isinstance(delimiter, bytes) else delimiter,
                            "flags": flags})
        require(len(out) <= 10_000, "LIMIT_EXCEEDED", "Account has too many folders to enumerate safely.")
        return out

    def canonical(self, client, folder):
        self.permissions.folder(folder)
        names = [x["folder"] for x in self.folders(client)]
        if folder not in names and folder.upper() == "INBOX":
            folder = next((x for x in names if x.upper() == "INBOX"), folder)
        require(folder in names, "FOLDER_NOT_FOUND", "Choose an existing selectable folder.")
        self.permissions.folder(folder)
        return folder

    def select(self, client, folder, readonly=True):
        name = self.canonical(client, folder)
        info = client.select_folder(name, readonly=readonly)
        # iCloud advertises READ-WRITE even in its successful EXAMINE response.
        # For the real library verify the command mode: imaplib sets this flag
        # when it sends EXAMINE. Reads still use PEEK and compare flags; the
        # response marker cannot prove the server's enforcement of read-only.
        wire = getattr(client, "_imap", None)
        requested_readonly = (wire.is_readonly is True if wire is not None
                              else not info.get(b"READ-WRITE", False))
        require(not readonly or requested_readonly, "READ_ONLY_REQUIRED",
                "Read-only mailbox selection was not requested.")
        uv = int(info.get(b"UIDVALIDITY", info.get("UIDVALIDITY", 0)))
        require(uv > 0, "IMAP_PROTOCOL", "Mailbox did not provide UIDVALIDITY.")
        return name, uv

    def reference(self, client, ref, readonly=True):
        obj = self.ids.decode(ref, "message")
        folder, uv = self.select(client, obj["folder"], readonly)
        require(uv == obj["uidvalidity"], "STALE_REFERENCE", "Mailbox UIDVALIDITY changed; search again.")
        uid = int(obj["uid"])
        require(uid in client.fetch([uid], ["UID"]), "MESSAGE_NOT_FOUND", "Message no longer exists in this folder.")
        return obj, folder, uv, uid

    def prevalidate(self, message_ref):
        obj = self.ids.decode(message_ref, "message")
        self.permissions.folder(obj["folder"])
        return obj

    @staticmethod
    def flags(client, uid):
        data = client.fetch([uid], ["FLAGS"])
        require(uid in data, "MESSAGE_NOT_FOUND", "Message no longer exists.")
        return tuple(sorted(data[uid].get(b"FLAGS", ())))

    def read_raw(self, client, uid):
        before = self.flags(client, uid)
        size = client.fetch([uid], ["RFC822.SIZE"])[uid][b"RFC822.SIZE"]
        require(size <= self.config.max_message_bytes, "MESSAGE_TOO_LARGE",
                "Message exceeds the configured complete-message limit; it was not truncated.")
        data = client.fetch([uid], ["BODY.PEEK[]"])
        require(uid in data and b"BODY[]" in data[uid], "IMAP_PROTOCOL", "Full message body was not returned.")
        raw = data[uid][b"BODY[]"]
        require(len(raw) <= self.config.max_message_bytes, "MESSAGE_TOO_LARGE", "Message exceeded its advertised size.")
        after = self.flags(client, uid)
        require(after == before, "FLAGS_CHANGED", "Flags changed during the read, possibly by another client; no flag restoration was attempted.")
        return raw, before

    def list_mail_folders(self, offset=0, limit=25):
        with self.connection() as client:
            rows = [x for x in self.folders(client) if self.config.folders is None or x["folder"] in self.config.folders]
            rows.sort(key=lambda x: x["folder"])
            return {"folders": rows[offset:offset+limit], "total": len(rows),
                    "next_offset": offset+limit if offset+limit < len(rows) else None}

    def search_messages(self, folder, query="", offset=0, limit=25, unread_only=False):
        self.permissions.folder(folder)
        with self.connection() as client:
            folder, uv = self.select(client, folder)
            criteria = ["ALL"]
            if query:
                require(len(query) <= 1024 and not any(c in query for c in "\r\n\x00"), "INVALID_INPUT", "Invalid search text.")
                # IMAPClient quotes typed arguments, no natural-language routing or raw IMAP criteria.
                criteria = ["TEXT", query]
            if unread_only:
                criteria.append("UNSEEN")
            try:
                # ASCII keeps the unlabelled path; non-ASCII requires an explicit
                # encoding. IMAPClient sends 8-bit arguments as quoted literals.
                charset = None if query.isascii() else "UTF-8"
                matches = sorted(client.search(criteria, charset=charset), reverse=True)
            except UnicodeEncodeError:
                raise ConnectorError("SEARCH_ENCODING_UNSUPPORTED", "Server search cannot encode this text without a supported Unicode extension.") from None
            except imaplib.IMAP4.error:
                raise ConnectorError("SEARCH_ENCODING_UNSUPPORTED" if not query.isascii() else "SEARCH_FAILED",
                    "Server rejected this literal search; no preview filtering or account fallback was used.") from None
            require(len(matches) <= 100_000, "SEARCH_LIMIT", "Too many search matches; narrow the query.")
            uids = matches[offset:offset+limit]
            rows = client.fetch(uids, ["FLAGS", "RFC822.SIZE", "INTERNALDATE"]) if uids else {}
            results = [{"message_ref": self.ids.issue("message", folder=folder, uidvalidity=uv, uid=uid),
                        "flags": [x.decode("ascii", "replace") for x in rows[uid].get(b"FLAGS", ())],
                        "size_bytes": rows[uid].get(b"RFC822.SIZE"),
                        "internal_date": rows[uid][b"INTERNALDATE"].isoformat() if rows[uid].get(b"INTERNALDATE") else None}
                       for uid in uids if uid in rows]
            return {"folder": folder, "uidvalidity": uv, "messages": results, "total": len(matches),
                    "next_offset": offset+limit if offset+limit < len(matches) else None}

    def message_document(self, raw, ref):
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        headers_raw = raw.split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in raw else raw.split(b"\n\n", 1)[0]
        sections = {"headers": {"headers": list(msg.raw_items()),
                                "wire_headers_base64": base64.b64encode(headers_raw).decode()},
                    "text": [], "html": [], "attachments": []}
        parts = list(msg.walk())
        require(len(parts) <= 2000, "LIMIT_EXCEEDED", "Message has too many MIME parts.")
        for idx, part in enumerate(parts):
            filename = part.get_filename()
            attached = part.get_content_disposition() == "attachment" or filename is not None
            if part.is_multipart() and not attached:
                continue
            data = self.part_bytes(part)
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html") and not attached:
                charset = part.get_content_charset() or "utf-8"
                try:
                    text = data.decode(charset, errors="replace")
                except LookupError:
                    text = data.decode("utf-8", errors="replace")
                sections["text" if ctype == "text/plain" else "html"].append(
                    {"mime_part": idx, "charset": charset, "content": text,
                     "raw_content_base64": base64.b64encode(data).decode(),
                     "decode_errors": "replacement permitted; decoded MIME-part bytes are preserved in raw_content_base64",
                     "parse_defects": [type(d).__name__ for d in part.defects]})
            else:
                sections["attachments"].append({"attachment_ref": self.ids.issue("attachment", message_ref=ref,
                    part=idx, digest=hashlib.sha256(data).hexdigest()), "filename": filename, "content_type": ctype,
                    "content_id": str(part.get("Content-ID", "")), "size_bytes": len(data)})
                if part.is_multipart():
                    sections["attachments"][-1]["representation"] = "serialized embedded MIME message; line endings normalized"
        return sections, parts

    @staticmethod
    def part_bytes(part):
        decoded = part.get_payload(decode=True)
        if decoded is not None:
            return decoded
        payload = part.get_payload()
        if part.get_content_type() == "message/rfc822" and isinstance(payload, list):
            return b"\r\n".join(p.as_bytes(policy=policy.default.clone(linesep="\r\n", refold_source="none")) for p in payload)
        if part.is_multipart():
            return part.as_bytes(policy=policy.default.clone(linesep="\r\n", refold_source="none"))
        return b""

    def fetch_message(self, message_ref, section="headers", offset=0, limit=16000):
        self.prevalidate(message_ref)
        with self.connection() as client:
            _, folder, uv, uid = self.reference(client, message_ref)
            raw, flags = self.read_raw(client, uid)
        sections, _ = self.message_document(raw, message_ref)
        require(section in sections, "INVALID_INPUT", "Unknown message section.")
        serialized = json.dumps(sections[section], ensure_ascii=False)
        require(offset <= len(serialized), "INVALID_OFFSET", "Offset exceeds section length.")
        return {"message_ref": message_ref, "folder": folder, "uidvalidity": uv, "uid": uid,
                "flags": [x.decode("ascii", "replace") for x in flags], "flags_verified_unchanged": True,
                "section": section, "encoding": "concatenate JSON string pages then parse JSON",
                "untrusted_data": serialized[offset:offset+limit], "offset": offset,
                "total_chars": len(serialized), "source_sha256": hashlib.sha256(raw).hexdigest(),
                "page_complete": offset+limit >= len(serialized), "section_complete_in_this_page": offset == 0 and limit >= len(serialized),
                "next_offset": offset+limit if offset+limit < len(serialized) else None}

    def fetch_attachment(self, attachment_ref, offset=0, limit=48000):
        a = self.ids.decode(attachment_ref, "attachment")
        self.prevalidate(a["message_ref"])
        with self.connection() as client:
            _, _, _, uid = self.reference(client, a["message_ref"])
            raw, _ = self.read_raw(client, uid)
        _, parts = self.message_document(raw, a["message_ref"])
        require(0 <= a["part"] < len(parts), "STALE_REFERENCE", "Attachment no longer exists.")
        data = self.part_bytes(parts[a["part"]])
        require(hashlib.sha256(data).hexdigest() == a["digest"], "STALE_REFERENCE", "Attachment content changed.")
        require(offset <= len(data), "INVALID_OFFSET", "Offset exceeds attachment length.")
        return {"attachment_ref": attachment_ref, "untrusted_data_base64": base64.b64encode(data[offset:offset+limit]).decode(),
                "offset_bytes": offset, "total_bytes": len(data), "sha256": a["digest"],
                "next_offset": offset+limit if offset+limit < len(data) else None, "flags_verified_unchanged": True}

    def set_message_read(self, message_ref, read):
        self.prevalidate(message_ref)
        with self.connection() as client:
            _, _, _, uid = self.reference(client, message_ref, readonly=False)
            (client.add_flags if read else client.remove_flags)([uid], [b"\\Seen"], silent=True)
            flags = self.flags(client, uid)
            require((b"\\Seen" in flags) == read, "POSTCONDITION_FAILED", "Read flag did not match the requested value.")
            return {"message_ref": message_ref, "read": read}
