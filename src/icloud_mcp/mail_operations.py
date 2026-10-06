"""Checkpointed mail writes. Re-entry is explicit recovery, never automatic resend.

The ledger stores MIME construction metadata and digests, not message bodies.
An identical caller input plus the frozen recipe reconstructs the original MIME.
Every uncertain remote command is reconciled by reads before further writes.
"""
import asyncio
from email import policy
from email.parser import BytesParser
import hashlib
import re
import time
from .mail import NegativeIMAPResponse
from .errors import ConnectorError, require


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def persistent_flags(flags):
    # Recent belongs to the session and must never be stored/copied by a client.
    return tuple(sorted(f for f in flags if f != b"\\Recent"))


def negative_response(error):
    # IMAPClient's checked tagged negative response is distinct from imaplib
    # parser/state/transport errors. Unknown protocol errors stay uncertain.
    return isinstance(error, NegativeIMAPResponse)


def response_identity(response, kind, source_uid=None):
    """Only one UID per operation; refuse malformed/ranged mappings."""
    if not isinstance(response, (str, bytes)):
        return None
    if isinstance(response, bytes):
        response = response.decode("ascii", "replace")
    pattern = (r"\[APPENDUID ([1-9][0-9]*) ([1-9][0-9]*)\]" if kind == "APPENDUID"
               else r"\[COPYUID ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*)\]")
    match = re.search(pattern, response, re.ASCII | re.IGNORECASE)
    if not match:
        return None
    values = tuple(int(x) for x in match.groups())
    if source_uid is not None:
        require(values[1] == source_uid, "MAIL_UNCERTAIN", "COPYUID did not identify the requested source UID.")
    return values[0], values[-1]


class MailOperations:
    def __init__(self, config, mail, smtp, ledger):
        self.config, self.mail, self.smtp, self.ledger = config, mail, smtp, ledger

    def save(self, op, checkpoint, **changes):
        checkpoint.update(changes)
        self.ledger.checkpoint(op, checkpoint)

    @staticmethod
    def deadline(end):
        require(time.monotonic() < end, "TIMEOUT", "Mail workflow deadline exceeded; inspect its checkpoint before recovery.")

    def execute(self, tool, arguments):
        if tool == "expunge_messages":
            self.mail.permissions.tool(tool)
        op = arguments["operation_id"]
        end = time.monotonic() + self.config.timeout_seconds
        with self.ledger.exclusive(op):
            cached = self.ledger.begin(op, tool, arguments, recover=tool != "expunge_messages")
            if cached is not None:
                return {"ok": True, "replayed_local_result": True, "result": cached}
            checkpoint = self.ledger.checkpoint(op) or {}
            try:
                if tool == "expunge_messages":
                    result = self.expunge(op, checkpoint, arguments, end)
                elif tool == "move_message":
                    result = self.move(op, checkpoint, arguments, end)
                else:
                    result = self.send(op, checkpoint, arguments, tool, end)
                if tool == "expunge_messages":
                    try:
                        self.ledger.finish(op, "succeeded", result)
                    except Exception:
                        raise ConnectorError("LEDGER_FAILURE", "Deletion may have completed but its result could not be persisted; inspect its checkpoint, never repeat automatically.") from None
                else:
                    self.ledger.finish(op, "succeeded", result)
                return {"ok": True, "result": result}
            except BaseException as error:
                if not isinstance(error, ConnectorError):
                    error = ConnectorError("MAIL_UNCERTAIN", "Mail workflow interrupted; inspect the checkpoint. No automatic retry.")
                payload = error.result()
                # Acceptance and Sent persistence are distinct even when the tool returns an error.
                if tool == "expunge_messages":
                    payload["result"] = {"expunge_progress": dict(checkpoint), "automatic_retry": False}
                elif checkpoint.get("smtp_result"):
                    payload["result"] = dict(checkpoint["smtp_result"], sent_copy={
                        "status": checkpoint.get("sent_status", "not_started"),
                        "folder": checkpoint["sent_folder"],
                        "message_ref": checkpoint.get("sent_ref"),
                        "append_outcome": checkpoint.get("append_outcome", "not_attempted"),
                        "connector_append_attempted": bool(checkpoint.get("append_attempted"))})
                elif tool != "move_message" and checkpoint.get("message_id"):
                    payload["message_id"] = checkpoint["message_id"]
                if error.code != "LEDGER_FAILURE":
                    uncertain = error.code in {"MAIL_UNCERTAIN", "SMTP_AMBIGUOUS", "TIMEOUT", "POSTCONDITION_FAILED"}
                    try:
                        self.ledger.finish(op, "ambiguous" if uncertain else "failed", payload)
                    except Exception:
                        return ConnectorError("LEDGER_FAILURE", "Outcome could not be persisted; reconcile before any further write.").result()
                return payload

    def expunge_rows(self, client, uids):
        require(getattr(client, "use_uid", None) is True,
                "IMAP_PROTOCOL", "Target validation requires UID-mode FETCH.")
        rows = client.fetch(uids, ["UID", "FLAGS"])
        # IMAPClient consumes the wire UID as the dictionary key in UID mode.
        # SEQ inside each row is a mailbox sequence number, never an identity.
        # Check a redundant UID if supplied, but do not require a field the
        # pinned library deliberately removes from its normal response.
        require(isinstance(rows, dict) and all(
            type(uid) is int and uid in uids and isinstance(row, dict)
            and (b"UID" not in row or (type(row[b"UID"]) is int and row[b"UID"] == uid))
            and isinstance(row.get(b"FLAGS"), tuple)
            and all(isinstance(flag, bytes) and flag and flag.isascii() for flag in row[b"FLAGS"])
            for uid, row in rows.items()),
                "IMAP_PROTOCOL", "Server returned inconsistent message identities or flags.")
        return rows

    @staticmethod
    def expunge_flags(rows):
        return {str(uid): [f.decode("ascii") for f in persistent_flags(row[b"FLAGS"])] for uid, row in rows.items()}

    def expunge_observation(self, op, cp, client):
        _, uv = self.mail.select(client, cp["folder"])
        require(uv == cp["uidvalidity"], "STALE_REFERENCE", "Mailbox identity changed during read-back.")
        rows = self.expunge_rows(client, cp["uids"])
        self.save(op, cp, observation="read_back_after_error", observed_flags=self.expunge_flags(rows),
                  observed_absent_uids=[uid for uid in cp["uids"] if uid not in rows],
                  remaining_uids=[uid for uid in cp["uids"] if uid in rows])

    def expunge(self, op, cp, args, end):
        """Validate all targets, mark only targets, then UID EXPUNGE that batch.

        Failed/incomplete same-ID attempts cannot re-enter this workflow.
        """
        self.mail.permissions.tool("expunge_messages")
        refs = args["message_refs"]
        require(0 < len(refs) <= self.config.max_results, "INVALID_INPUT", "Choose a bounded nonempty list of explicit message references.")
        objs = [self.mail.prevalidate(ref) for ref in refs]
        require(len({o["folder"] for o in objs}) == 1 and len({o["uidvalidity"] for o in objs}) == 1,
                "INVALID_INPUT", "Expunge requires one explicit mailbox identity.")
        uids = [o["uid"] for o in objs]
        require(all(type(uid) is int and 0 < uid <= 4294967295 for uid in uids) and len(set(uids)) == len(uids),
                "INVALID_INPUT", "Every target must have a distinct valid UID.")
        with self.mail.connection() as client:
            folder, uv = self.mail.select(client, objs[0]["folder"])
            require(uv == objs[0]["uidvalidity"], "STALE_REFERENCE", "Mailbox UIDVALIDITY changed; no mutation performed.")
            require(client.has_capability("UIDPLUS"), "UNSUPPORTED", "Targeted deletion requires UIDPLUS; no broad expunge fallback.")
            rows = self.expunge_rows(client, uids)
            require(set(rows) == set(uids), "MESSAGE_NOT_FOUND", "An explicit target is missing; no mutation performed.")
            initial = self.expunge_flags(rows)
            expected = {str(uid): sorted(set(initial[str(uid)]) | {"\\Deleted"}) for uid in uids}
            to_mark = [uid for uid in uids if "\\Deleted" not in initial[str(uid)]]
            self.save(op, cp, workflow="permanent_expunge", folder=folder, uidvalidity=uv,
                      uids=uids, message_refs=refs, initial_flags=initial, expected_marked_flags=expected,
                      mark_attempted_uids=[], mark_status="not_started", expunge_status="not_started")
            try:
                _, selected_uv = self.mail.select(client, folder, readonly=False)
                require(selected_uv == uv, "STALE_REFERENCE", "Mailbox identity changed before marking; no mutation performed.")
                rows = self.expunge_rows(client, uids)
                require(set(rows) == set(uids), "MESSAGE_NOT_FOUND", "A target disappeared before marking; no mutation performed.")
                require(self.expunge_flags(rows) == initial, "MAIL_CONFLICT", "Target flags changed before marking; no mutation performed.")
                if to_mark:
                    self.deadline(end)
                    self.save(op, cp, mark_status="started", mark_attempted_uids=to_mark)
                    try:
                        client.add_flags(to_mark, [b"\\Deleted"], silent=True)
                    except BaseException as error:
                        self.save(op, cp, mark_status="rejected" if negative_response(error) else "uncertain")
                        raise ConnectorError("EXPUNGE_INCOMPLETE" if negative_response(error) else "MAIL_UNCERTAIN",
                                             "Target marking did not complete definitively; no expunge attempted. Inspect partial outcomes, never retry automatically.") from None
                    self.save(op, cp, mark_status="accepted")
                rows = self.expunge_rows(client, uids)
                require(set(rows) == set(uids), "MAIL_UNCERTAIN", "A target disappeared during marking; no expunge attempted.")
                observed = self.expunge_flags(rows)
                self.save(op, cp, observed_flags=observed, observed_absent_uids=[], remaining_uids=uids)
                require(observed == expected, "MAIL_UNCERTAIN", "Marking postcondition failed or other flags changed; no expunge attempted.")
                self.save(op, cp, mark_status="verified")
                _, selected_uv = self.mail.select(client, folder, readonly=False)
                require(selected_uv == uv, "MAIL_UNCERTAIN", "Mailbox identity changed after marking; no expunge attempted.")
                rows = self.expunge_rows(client, uids)
                require(set(rows) == set(uids) and self.expunge_flags(rows) == expected,
                        "MAIL_UNCERTAIN", "Targets changed after marking; no expunge attempted.")
                self.deadline(end)
                self.save(op, cp, expunge_status="started")
                try:
                    client.uid_expunge(uids)
                except BaseException as error:
                    self.save(op, cp, expunge_status="rejected" if negative_response(error) else "uncertain")
                    raise ConnectorError("EXPUNGE_INCOMPLETE" if negative_response(error) else "MAIL_UNCERTAIN",
                                         "Targeted expunge did not complete definitively. Reconcile these exact UIDs; never repeat automatically.") from None
                self.save(op, cp, expunge_status="accepted")
                rows = self.expunge_rows(client, uids)
                remaining = [uid for uid in uids if uid in rows]
                self.save(op, cp, observed_absent_uids=[uid for uid in uids if uid not in rows],
                          remaining_uids=remaining, observed_flags=self.expunge_flags(rows))
                require(not remaining, "POSTCONDITION_FAILED", "Some targets remain after accepted expunge; inspect partial outcomes, never retry automatically.")
                self.save(op, cp, expunge_status="verified")
                return {"permanently_expunged": len(uids), "folder": folder, "uidvalidity": uv,
                        "uids": uids, "marked_uids": to_mark, "other_flags_preserved_before_expunge": True,
                        "target_absence_verified": True, "broad_expunge": False}
            except BaseException as error:
                if cp["mark_status"] != "not_started" or cp["expunge_status"] != "not_started":
                    if not (isinstance(error, ConnectorError) and error.code == "LEDGER_FAILURE") and time.monotonic() < end:
                        try:
                            self.expunge_observation(op, cp, client)
                        except BaseException:
                            pass  # Started/uncertain checkpoints still prohibit replay.
                raise

    def identity(self, client, folder):
        folder, uv = self.mail.select(client, folder)
        info = client.folder_status(folder, ["UIDVALIDITY", "UIDNEXT"])
        require(int(info[b"UIDVALIDITY"]) == uv and int(info[b"UIDNEXT"]) > 0,
                "MAIL_UNCERTAIN", "Destination mailbox identity changed during inspection.")
        return folder, uv, int(info[b"UIDNEXT"])

    def candidates(self, client, message_id=None, minimum_uid=None):
        criteria = ["HEADER", "Message-ID", message_id] if message_id else ["UID", f"{minimum_uid}:*"]
        uids = client.search(criteria)
        require(len(uids) <= self.config.max_results, "MAIL_UNCERTAIN", "Too many candidates to reconcile safely.")
        return [int(u) for u in uids if minimum_uid is None or int(u) >= minimum_uid]

    def match(self, client, uids, expected_hash, *, message_id=None, flags=None, internal_date=None):
        matches = []
        for uid in uids:
            if not client.fetch([uid], ["UID"]):
                continue
            raw, current_flags = self.mail.read_raw(client, uid)
            if message_id and str(BytesParser(policy=policy.default).parsebytes(raw)["Message-ID"]) != message_id:
                continue
            if digest(raw) != expected_hash:
                continue
            if flags is not None and persistent_flags(current_flags) != flags:
                continue
            if internal_date is not None:
                value = client.fetch([uid], ["INTERNALDATE"])[uid].get(b"INTERNALDATE")
                from datetime import datetime
                if value != datetime.fromisoformat(internal_date):
                    continue
            matches.append(uid)
        require(len(matches) <= 1, "MAIL_UNCERTAIN", "Multiple matching copies exist; no further account write is safe.")
        return matches[0] if matches else None

    def match_sent(self, client, uids, submitted, message_id):
        """Sent-only byte comparison. Never used by COPY/move verification."""
        require(len(uids) <= 1, "MAIL_UNCERTAIN", "Multiple Sent candidates exist; no reconciliation or APPEND is safe.")
        if not uids or not client.fetch([uids[0]], ["UID"]):
            return None
        raw, _ = self.mail.read_raw(client, uids[0])
        if str(BytesParser(policy=policy.default).parsebytes(raw).get("Message-ID")) != message_id:
            return None
        exact = raw == submitted
        extra_crlf = raw == submitted + b"\r\n"
        if not exact and not extra_crlf:
            return None
        return {"uid": uids[0], "mime_verified": True, "exact_mime_verified": exact,
                "trailing_crlf_exception_used": extra_crlf,
                "verification_rule": "exact" if exact else "submitted_plus_one_trailing_crlf",
                "submitted_sha256": digest(submitted), "stored_sha256": digest(raw),
                "read_flags_verified_unchanged": True}

    def sent_result(self, cp, verification, ref):
        return dict(cp["smtp_result"], sent_folder_copy_created=cp.get("append_outcome") == "accepted",
                    sent_copy={"status": "saved", "folder": cp["sent_folder"], "message_ref": ref,
                               "append_outcome": cp.get("append_outcome", "not_attempted"),
                               "connector_append_attempted": bool(cp.get("append_attempted")),
                               **{k: v for k, v in verification.items() if k != "uid"}})

    def reconcile_sent(self, tool, arguments):
        """Operator-only recovery: remote reads followed by one atomic local update.

        No SMTP or APPEND call exists in this execution path. Not an MCP tool.
        """
        require(tool in ("send_message", "reply_message"), "INVALID_INPUT", "Only Sent persistence can be reconciled here.")
        self.mail.permissions.tool(tool)
        op = arguments["operation_id"]
        with self.ledger.exclusive(op):
            previous = self.ledger.inspect_existing(op, tool, arguments)
            cp = self.ledger.checkpoint(op)
            require(cp and cp.get("smtp_status") == "accepted" and cp.get("smtp_result", {}).get("smtp_accepted"),
                    "MAIL_UNCERTAIN", "Durable SMTP acceptance evidence is required; no send is performed.")
            require(cp.get("sent_status") in ("started", "accepted", "uncertain", "saved"), "MAIL_UNCERTAIN",
                    "Reconciliation requires a previously attempted Sent persistence phase.")
            self.mail.permissions.folder(cp["sent_folder"])
            _, _, raw = self.smtp.build(op, text=arguments["text"], html=arguments.get("html"),
                                        recipe=cp["recipe"], **cp["envelope"])
            require(digest(raw) == cp["raw_hash"], "MAIL_UNCERTAIN", "Submitted MIME reconstruction differs from the original hash.")
            with self.mail.connection() as client:
                folder, uv = self.mail.select(client, cp["sent_folder"])
                require(uv == cp["sent_uv"], "MAIL_UNCERTAIN", "Sent UIDVALIDITY changed; no ledger update performed.")
                candidates = self.candidates(client, cp["message_id"])
                require(len(candidates) == 1, "MAIL_UNCERTAIN", "Require exactly one existing Sent copy; no APPEND is performed.")
                verification = self.match_sent(client, candidates, raw, cp["message_id"])
                require(verification is not None, "MAIL_UNCERTAIN", "Sent evidence fails the strict byte rule; no ledger update performed.")
                ref = self.mail.ids.issue("message", folder=folder, uidvalidity=uv, uid=verification["uid"])
            cp.update(sent_status="saved", sent_ref=ref, sent_verification=verification)
            result = self.sent_result(cp, verification, ref)
            if previous[1] != "succeeded":
                evidence = {"method": "read_only_sent_reconciliation", "smtp_sends": 0, "appends": 0,
                            "matching_copies": 1, "message_ref": ref, **verification}
                self.ledger.reconcile_sent(op, previous, cp, result, evidence)
            return result

    def send(self, op, cp, args, tool, end):
        if not cp:
            self.mail.permissions.folder(self.config.sent_folder)
            with self.mail.connection() as client:
                folder, uv, _ = self.identity(client, self.config.sent_folder)
            envelope = {k: args[k] for k in ("to", "subject", "cc", "bcc") if k in args}
            if tool == "reply_message":
                to, subject, headers = self.smtp.reply_source(args["message_ref"], args.get("reply_all", False))
                envelope = {"to": to, "subject": subject, "reply_headers": headers}
            msg, recipients, raw = self.smtp.build(op, text=args["text"], html=args.get("html"), **envelope)
            self.save(op, cp, smtp_status="prepared", sent_status="not_started", append_outcome="not_attempted", sent_folder=folder,
                      sent_uv=uv, message_id=str(msg["Message-ID"]), raw_hash=digest(raw),
                      recipe={"date": str(msg["Date"]), "boundary": msg.get_boundary()}, envelope=envelope)
        else:
            self.mail.permissions.folder(cp["sent_folder"])
            msg, recipients, raw = self.smtp.build(op, text=args["text"], html=args.get("html"),
                                                    recipe=cp["recipe"], **cp["envelope"])
            require(digest(raw) == cp["raw_hash"], "MAIL_UNCERTAIN", "Original sent MIME could not be reconstructed exactly.")
        if cp["smtp_status"] != "accepted":
            require(cp["smtp_status"] == "prepared", "OPERATION_NOT_REPLAYABLE",
                    "SMTP was already attempted without durable confirmed acceptance; no resend is allowed.")
            self.deadline(end)
            self.save(op, cp, smtp_status="started")
            try:
                accepted = asyncio.run(self.smtp.transmit(msg, recipients, raw))
            except ConnectorError as error:
                self.save(op, cp, smtp_status="uncertain" if error.code == "SMTP_AMBIGUOUS" else "failed")
                raise
            # Durably retain acceptance BEFORE touching the Sent mailbox.
            self.save(op, cp, smtp_status="accepted", smtp_result=accepted)
        self.deadline(end)
        with self.mail.connection() as client:
            folder, uv = self.mail.select(client, cp["sent_folder"])
            require(uv == cp["sent_uv"], "MAIL_UNCERTAIN", "Sent UIDVALIDITY changed; no APPEND or resend will be attempted.")
            candidates = self.candidates(client, cp["message_id"])
            require(len(candidates) <= 1, "MAIL_UNCERTAIN", "Multiple Sent messages share this Message-ID; no additional copy or send is safe.")
            verification = self.match_sent(client, candidates, raw, cp["message_id"])
            if verification is None:
                require(not candidates, "MAIL_UNCERTAIN", "Sent contains this Message-ID with different MIME; no duplicate APPEND or SMTP resend is safe.")
                # Tagged OK or lost response cannot justify repeating APPEND, even if a
                # subsequent search is empty (replication/delayed execution is possible).
                require(cp["sent_status"] in ("not_started", "failed"), "MAIL_UNCERTAIN",
                        "An APPEND may already have completed, but its exact copy cannot be established. No second APPEND or SMTP send.")
                self.deadline(end)
                self.save(op, cp, sent_status="started", append_outcome="started", append_attempted=True)
                try:
                    response = client.append(folder, raw, flags=[b"\\Seen"])
                except BaseException as error:
                    self.save(op, cp, sent_status="failed" if negative_response(error) else "uncertain",
                              append_outcome="rejected" if negative_response(error) else "uncertain")
                    raise ConnectorError("SENT_COPY_FAILED" if negative_response(error) else "MAIL_UNCERTAIN",
                                         "SMTP was accepted; Sent APPEND did not complete definitively. Never resend SMTP.") from None
                mapping = response_identity(response, "APPENDUID")
                self.save(op, cp, sent_status="accepted", append_outcome="accepted", append_identity=list(mapping) if mapping else None)
                _, after_uv = self.mail.select(client, folder)
                require(after_uv == uv and (mapping is None or mapping[0] == uv), "MAIL_UNCERTAIN", "Sent mailbox identity changed after APPEND.")
                uids = [mapping[1]] if mapping else self.candidates(client, cp["message_id"])
                verification = self.match_sent(client, uids, raw, cp["message_id"])
                require(verification is not None, "MAIL_UNCERTAIN", "APPEND was accepted but Sent MIME failed the exact-or-single-trailing-CRLF rule; do not APPEND again.")
            uid = verification["uid"]
            ref = self.mail.ids.issue("message", folder=folder, uidvalidity=uv, uid=uid)
            self.save(op, cp, sent_status="saved", sent_ref=ref, sent_verification=verification)
            return self.sent_result(cp, verification, ref)

    def verify_destination(self, client, cp):
        _, uv = self.mail.select(client, cp["destination"])
        require(uv == cp["destination_uv"], "MAIL_UNCERTAIN", "Destination UIDVALIDITY changed; source removal is prohibited.")
        candidates = ([cp["destination_uid"]] if cp.get("destination_uid") else
                      self.candidates(client, cp.get("message_id"), cp["destination_uidnext"]))
        flags = tuple(x.encode("ascii") for x in cp["flags"])
        uid = self.match(client, candidates, cp["raw_hash"], flags=flags, internal_date=cp["internal_date"])
        require(uid is not None, "MAIL_UNCERTAIN", "A verified destination copy cannot be established; source will not be removed or copied again.")
        return uid

    def move(self, op, cp, args, end):
        self.mail.prevalidate(args["message_ref"])
        self.mail.permissions.folder(args["destination_folder"])
        with self.mail.connection() as client:
            # Require UIDPLUS even if MOVE is advertised: this workflow verifies
            # the destination BEFORE source removal, which atomic MOVE cannot do.
            require(client.has_capability("UIDPLUS"), "UNSUPPORTED", "A verified true move requires UIDPLUS for targeted source removal; no broad EXPUNGE or duplicate-only fallback.")
            if not cp:
                obj, source, uv, uid = self.mail.reference(client, args["message_ref"])
                raw, flags = self.mail.read_raw(client, uid)
                flags = persistent_flags(flags)
                require(b"\\Deleted" not in flags, "INVALID_INPUT", "Do not move a source already marked Deleted.")
                date = client.fetch([uid], ["INTERNALDATE"])[uid].get(b"INTERNALDATE")
                require(date is not None, "IMAP_PROTOCOL", "Source INTERNALDATE is unavailable.")
                destination, dest_uv, next_uid = self.identity(client, args["destination_folder"])
                require(destination != source, "INVALID_INPUT", "Source and destination folders are the same.")
                self.save(op, cp, source=source, source_uv=uv, source_uid=uid, destination=destination,
                          destination_uv=dest_uv, destination_uidnext=next_uid, raw_hash=digest(raw),
                          flags=[f.decode("ascii") for f in flags], internal_date=date.isoformat(),
                          message_id=str(BytesParser(policy=policy.default).parsebytes(raw).get("Message-ID", "")),
                          copy_status="not_started", source_status="present")
            if cp["copy_status"] in ("not_started", "failed"):
                _, current_uv, next_uid = self.identity(client, cp["destination"])
                require(current_uv == cp["destination_uv"], "MAIL_UNCERTAIN", "Destination UIDVALIDITY changed; no COPY performed.")
                _, _, _, uid = self.mail.reference(client, args["message_ref"])
                raw, flags = self.mail.read_raw(client, uid)
                require(digest(raw) == cp["raw_hash"] and persistent_flags(flags) == tuple(f.encode("ascii") for f in cp["flags"]),
                        "MAIL_CONFLICT", "Source changed before COPY; no write was performed.")
                self.deadline(end)
                self.save(op, cp, copy_status="started", destination_uidnext=next_uid)
                try:
                    response = client.copy([uid], cp["destination"])
                except BaseException as error:
                    self.save(op, cp, copy_status="failed" if negative_response(error) else "uncertain")
                    raise ConnectorError("MOVE_INCOMPLETE" if negative_response(error) else "MAIL_UNCERTAIN",
                                         "COPY did not complete definitively; source was not removed. No automatic retry.") from None
                mapping = response_identity(response, "COPYUID", uid)
                if mapping:
                    require(mapping[0] == cp["destination_uv"] and mapping[1] >= cp["destination_uidnext"],
                            "MAIL_UNCERTAIN", "COPYUID destination identity is inconsistent; source remains.")
                self.save(op, cp, copy_status="accepted", destination_uid=mapping[1] if mapping else None)
            dest_uid = self.verify_destination(client, cp)
            self.save(op, cp, copy_status="verified", destination_uid=dest_uid)
            _, uv = self.mail.select(client, cp["source"], readonly=False)
            require(uv == cp["source_uv"], "MAIL_UNCERTAIN", "Source UIDVALIDITY changed; no source mutation is safe.")
            uid = cp["source_uid"]
            exists = bool(client.fetch([uid], ["UID"]))
            if exists:
                raw, current = self.mail.read_raw(client, uid)
                original = tuple(f.encode("ascii") for f in cp["flags"])
                current = persistent_flags(current)
                allowed = original if cp["source_status"] == "present" else tuple(sorted(original+(b"\\Deleted",)))
                require(digest(raw) == cp["raw_hash"] and current in (original, allowed),
                        "MAIL_CONFLICT", "Source content or flags changed; verified destination is retained without source removal.")
                require(cp["source_status"] != "expunge_started", "MAIL_UNCERTAIN",
                        "Source removal was attempted but its outcome remains uncertain. No repeated expunge.")
                if b"\\Deleted" not in current:
                    self.deadline(end)
                    self.save(op, cp, source_status="delete_started")
                    try:
                        client.add_flags([uid], [b"\\Deleted"], silent=True)
                    except BaseException as error:
                        raise ConnectorError("MOVE_INCOMPLETE" if negative_response(error) else "MAIL_UNCERTAIN",
                                             "Source flag operation did not complete definitively; destination copy is retained.") from None
                require(persistent_flags(self.mail.flags(client, uid)) == tuple(sorted(original+(b"\\Deleted",))),
                        "MAIL_UNCERTAIN", "Source flags changed before targeted removal; no expunge performed.")
                self.save(op, cp, source_status="marked")
                self.deadline(end)
                self.save(op, cp, source_status="expunge_started")
                try:
                    client.uid_expunge([uid])
                except BaseException as error:
                    if negative_response(error):
                        self.save(op, cp, source_status="marked")
                    raise ConnectorError("MOVE_INCOMPLETE" if negative_response(error) else "MAIL_UNCERTAIN",
                                         "Targeted source removal did not complete definitively; inspect both folders before recovery.") from None
                require(not client.fetch([uid], ["UID"]), "MAIL_UNCERTAIN", "Targeted source removal could not be verified; no repeated expunge.")
            else:
                require(cp["source_status"] in ("expunge_started", "removed"), "MAIL_UNCERTAIN", "Source disappeared outside the verified removal phase; destination is retained.")
            self.save(op, cp, source_status="removed")
            self.verify_destination(client, cp)
            ref = self.mail.ids.issue("message", folder=cp["destination"], uidvalidity=cp["destination_uv"], uid=dest_uid)
            return {"moved": True, "method": "UID COPY + verified copy + UID STORE + targeted UID EXPUNGE",
                    "destination_folder": cp["destination"], "message_ref": ref, "old_reference_invalid": True,
                    "flags_preserved": True, "internal_date_preserved": True, "source_removed": True,
                    "broad_expunge": False}
