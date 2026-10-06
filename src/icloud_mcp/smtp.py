"""One SMTP attempt per operation. DATA disconnects are retained as ambiguous."""
import asyncio
from email.message import EmailMessage
from email import policy
from email.utils import formatdate, parseaddr
from email.parser import BytesParser
import hashlib
import hmac
import aiosmtplib
from .errors import ConnectorError, require


def address(value):
    require(isinstance(value, str) and len(value) <= 320 and not any(c in value for c in "\r\n\x00"),
            "INVALID_ADDRESS", "Invalid recipient address.")
    parsed = parseaddr(value)[1]
    require(parsed == value and "@" in parsed and value.isascii(), "INVALID_ADDRESS",
            "Provide a plain ASCII mailbox address, without a display name.")
    return parsed


class TrackedSMTP(aiosmtplib.SMTP):
    data_started = False

    async def data(self, *args, **kwargs):
        self.data_started = True
        return await super().data(*args, **kwargs)


class SMTP:
    def __init__(self, config, mail, key, factory=None):
        self.config, self.mail, self.key, self.factory = config, mail, key, factory

    def build(self, operation_id, to, subject, text, html=None, cc=None, bcc=None, reply_headers=None, *, recipe=None):
        require(bool(self.config.account_email), "NOT_CONFIGURED", "Configure this connector's account.")
        to, cc, bcc = [address(x) for x in to], [address(x) for x in cc or []], [address(x) for x in bcc or []]
        recipients = list(dict.fromkeys(to+cc+bcc))
        require(1 <= len(recipients) <= 100, "INVALID_INPUT", "Provide 1–100 recipients.")
        require(not any(c in subject for c in "\r\n\x00") and len(subject) <= 998,
                "INVALID_INPUT", "Invalid subject header.")
        require(len(text) + len(html or "") <= self.config.max_message_bytes // 2,
                "MESSAGE_TOO_LARGE", "Outgoing message exceeds its configured size limit.")
        msg = EmailMessage(policy=policy.SMTP)
        msg["From"] = self.config.account_email
        if to: msg["To"] = ", ".join(to)
        if cc: msg["Cc"] = ", ".join(cc)
        msg["Subject"], msg["Date"] = subject, (recipe["date"] if recipe else formatdate(localtime=False, usegmt=True))
        digest = hmac.new(self.key, operation_id.encode(), hashlib.sha256).hexdigest()[:40]
        msg["Message-ID"] = f"<{digest}@icloud-mcp.invalid>"
        if reply_headers:
            for k, v in reply_headers.items():
                require(not any(c in v for c in "\r\n\x00") and len(v) <= 8000,
                        "INVALID_HEADER", "Reply source contains an invalid threading header.")
                msg[k] = v
        msg.set_content(text)
        if html is not None:
            msg.add_alternative(html, subtype="html")
            if recipe:
                msg.set_boundary(recipe["boundary"])
        raw = msg.as_bytes()
        require(len(raw) <= self.config.max_message_bytes, "MESSAGE_TOO_LARGE", "Encoded message exceeds configured limit.")
        return msg, recipients, raw

    async def transmit(self, msg, recipients, raw):
        password = self.config.password() if not self.factory else "synthetic"
        client = self.factory() if self.factory else TrackedSMTP(hostname=self.config.smtp_host, port=587,
                            start_tls=True, use_tls=False, validate_certs=True, timeout=self.config.timeout_seconds)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                await client.connect()
                await client.login(self.config.account_email, password)
                errors, _ = await client.sendmail(self.config.account_email, recipients, raw)
                # SMTP accepted the message, but delivery is a separate event. Do not await QUIT
                # before recording success; a failed QUIT must not turn acceptance into a resend.
                return {"smtp_accepted": True, "delivery_confirmed": False, "message_id": str(msg["Message-ID"]),
                        "accepted_recipient_count": len(recipients)-len(errors), "rejected_recipient_count": len(errors),
                        "automatic_retry": False, "sent_folder_copy_created": False}
        except aiosmtplib.errors.SMTPResponseException:
            raise ConnectorError("SMTP_REJECTED", "SMTP returned a definitive negative response; no automatic resend.") from None
        except aiosmtplib.errors.SMTPRecipientsRefused:
            raise ConnectorError("SMTP_REJECTED", "All recipients were rejected; no automatic resend.") from None
        except BaseException:
            if client.data_started:
                raise ConnectorError("SMTP_AMBIGUOUS", "Connection ended during DATA. Delivery may have occurred; reconcile using the operation's Message-ID before considering any new send.") from None
            raise ConnectorError("SMTP_NOT_SENT", "SMTP failed before DATA; no automatic resend.") from None
        finally:
            try:
                client.close()
            except Exception:
                pass  # Local cleanup cannot undo an already confirmed DATA response.

    def reply_source(self, message_ref, reply_all=False):
        self.mail.prevalidate(message_ref)
        with self.mail.connection() as client:
            _, _, _, uid = self.mail.reference(client, message_ref)
            raw, _ = self.mail.read_raw(client, uid)
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        from email.utils import getaddresses
        targets = getaddresses(msg.get_all("Reply-To", []) or msg.get_all("From", []))
        # Preserve the explicit reply target, including a message sent to self.
        # Exclude this account only from additional reply-all To/Cc recipients.
        primary = [address(a) for _, a in targets if a]
        additional = []
        if reply_all:
            additional = [address(a) for _, a in getaddresses(msg.get_all("To", [])+msg.get_all("Cc", []))
                          if a and a.casefold() != self.config.account_email.casefold()]
        to = list(dict.fromkeys(primary + additional))
        require(bool(to), "INVALID_ADDRESS", "Reply has no valid recipient.")
        subject = str(msg.get("Subject", ""))
        if not subject.casefold().startswith("re:"):
            subject = "Re: " + subject
        mid = str(msg.get("Message-ID", ""))
        headers = {"In-Reply-To": mid, "References": (str(msg.get("References", ""))+" "+mid).strip()} if mid else {}
        return to, subject, headers
