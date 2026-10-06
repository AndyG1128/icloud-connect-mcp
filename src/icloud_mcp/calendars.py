"""CalDAV discovery and conditional resource writes, independent of Jarvis."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit, unquote
from zoneinfo import ZoneInfo
from icalendar import Calendar as ICalendar, Event
import caldav
from caldav.elements import dav, cdav
from caldav.elements.base import BaseElement
from .errors import ConnectorError, require
from .recurrence import UTC, window, expand, bounds, identity, occurrence, apply_changes, normalized


def allowed_url(value):
    p = urlsplit(str(value))
    host = p.hostname or ""
    provider_host = host == "caldav.icloud.com" or host.endswith(".caldav.icloud.com") or bool(re.fullmatch(r"p[0-9]+-caldav\.icloud\.com", host))
    require(p.scheme == "https" and provider_host
            and p.port in (None, 443) and not p.username and not p.password and not p.query and not p.fragment,
            "INVALID_RESOURCE", "CalDAV URL must be an HTTPS iCloud calendar resource.")
    require(not any(x in unquote(p.path).split("/") for x in (".", "..")) and "\\" not in unquote(p.path),
            "INVALID_RESOURCE", "Invalid resource path.")
    return str(value)


def guarded(client, deadline, max_event_bytes=2_000_000):
    """Disable unrestricted redirects and implicit retries on this client's own session."""
    original = client.session.request
    def request(method, url, **kwargs):
        for _ in range(6):
            allowed_url(url)
            remaining = deadline-time.monotonic()
            require(remaining > 0, "TIMEOUT", "CalDAV operation exceeded its deadline.")
            kwargs["timeout"] = min(client.timeout, remaining)
            kwargs["allow_redirects"] = False
            kwargs["stream"] = True
            response = original(method, url, **kwargs)
            if response.status_code not in (301, 302, 303, 307, 308):
                if method.upper() in ("PUT", "DELETE"):
                    response._content = b""
                    response._content_consumed = True
                    response.close()
                else:
                    maximum = max_event_bytes if method.upper() == "GET" else max_event_bytes*4
                    chunks = []; size = 0
                    try:
                        for chunk in response.iter_content(chunk_size=65536):
                            size += len(chunk)
                            require(size <= maximum, "RESPONSE_TOO_LARGE", "CalDAV response exceeds its bounded transport budget; narrow the query.")
                            require(time.monotonic() < deadline, "TIMEOUT", "CalDAV response exceeded its deadline.")
                            chunks.append(chunk)
                        response._content = b"".join(chunks)
                        response._content_consumed = True
                    finally:
                        response.close()
                return response
            if hasattr(response, "close"):
                response.close()
            require(method.upper() not in ("PUT", "DELETE", "POST"), "WRITE_REDIRECT",
                    "CalDAV mutation redirects are not followed.")
            url = allowed_url(urljoin(str(url), response.headers.get("Location", "")))
        raise ConnectorError("REDIRECT_LIMIT", "Too many CalDAV redirects.")
    client.session.request = request
    return client


class Calendars:
    def __init__(self, config, permissions, identities, key, factory=None):
        self.config, self.permissions, self.ids, self.key, self.factory = config, permissions, identities, key, factory

    @contextmanager
    def connection(self):
        deadline = time.monotonic()+self.config.timeout_seconds
        if self.factory:
            client = self.factory()
        else:
            client = caldav.DAVClient(url=self.config.caldav_url, username=self.config.username,
                password=self.config.password(), timeout=self.config.timeout_seconds, ssl_verify_cert=True,
                enable_rfc6764=False, require_tls=True, rate_limit_handle=False)
            from niquests.adapters import HTTPAdapter
            client.session.mount("https://", HTTPAdapter(max_retries=0))
            guarded(client, deadline, self.config.max_event_bytes)
        try:
            yield client
        finally:
            client.close()

    def discover(self, client):
        # Enumerate actual CalDAV collections, never merge/hide by display name.
        calendars = client.principal().calendars()
        require(len(calendars) <= self.config.max_calendar_resources, "LIMIT_EXCEEDED", "Too many calendar collections.")
        records = []
        for calendar in calendars:
            href = allowed_url(calendar.url).rstrip("/")+"/"
            cid = hashlib.sha256((self.ids.account+"\0"+href).encode()).hexdigest()[:32]
            components = [str(x).upper() for x in calendar.get_supported_components(with_fallback=True)]
            records.append((cid, href, calendar, components))
        return records

    def selected(self, client, calendar_ref):
        obj = self.ids.decode(calendar_ref, "calendar")
        self.permissions.calendar(obj["calendar_id"])
        match = [r for r in self.discover(client) if r[0] == obj["calendar_id"] and r[1] == obj["href"]]
        require(len(match) == 1, "CALENDAR_NOT_FOUND", "Calendar no longer belongs to this configured account.")
        require("VEVENT" in match[0][3], "UNSUPPORTED_COMPONENT", "This collection does not advertise VEVENT support.")
        return match[0]

    def prevalidate(self, calendar_ref):
        obj = self.ids.decode(calendar_ref, "calendar")
        self.permissions.calendar(obj["calendar_id"])
        allowed_url(obj["href"])
        return obj

    def resource(self, collection, href):
        href = allowed_url(href)
        root, resource = urlsplit(collection), urlsplit(href)
        # Require one direct child; encoded separators may not escape the collection.
        leaf = unquote(resource.path[len(root.path):]) if resource.path.startswith(root.path) else ""
        require(root.netloc == resource.netloc and leaf and "/" not in leaf and "\\" not in leaf,
                "INVALID_RESOURCE", "Event href is not a direct resource in the selected account calendar.")
        return href

    def parse(self, data):
        raw = data.encode() if isinstance(data, str) else data
        require(len(raw) <= self.config.max_event_bytes, "EVENT_TOO_LARGE", "Calendar resource exceeds its configured limit.")
        parsed = ICalendar.from_ical(raw)
        require(parsed.name == "VCALENDAR", "INVALID_EVENT", "Invalid calendar resource.")
        require(len(parsed.walk("VEVENT")) <= 2000, "LIMIT_EXCEEDED", "Too many exceptions in a calendar resource.")
        return parsed

    def get_resource(self, client, root, href):
        href = self.resource(root, href)
        response = client.request(href, "GET")
        require(response.status != 404, "EVENT_NOT_FOUND", "Event resource no longer exists.")
        require(response.status == 200, "CALDAV_READ_FAILED", "CalDAV did not return the event resource.")
        etag = response.headers.get("ETag") or response.headers.get("Etag") or response.headers.get("etag")
        require(bool(etag), "MISSING_ETAG", "Resource did not provide an ETag; conflict-safe identity is unavailable.")
        return self.parse(response.raw), etag, response.raw

    def list_calendars(self, offset=0, limit=25):
        with self.connection() as client:
            rows = [{"calendar_ref": self.ids.issue("calendar", calendar_id=cid, href=href),
                     "calendar_id": cid, "resource_href": href, "untrusted_name": str(cal.name or ""),
                     "supported_components": comps, **self.collection_metadata(cal)}
                    for cid, href, cal, comps in self.discover(client)
                    if self.config.calendars is None or cid in self.config.calendars]
        rows.sort(key=lambda x:x["calendar_id"])
        return {"calendars": rows[offset:offset+limit], "total": len(rows),
                "next_offset": offset+limit if offset+limit < len(rows) else None}

    def collection_metadata(self, calendar):
        """Read declared properties without guessing collection purpose from names."""
        class Privileges(BaseElement):
            tag = "{DAV:}current-user-privilege-set"
        props = calendar.get_properties([dav.ResourceType(), dav.Owner(),
            cdav.SupportedCalendarComponentSet(), cdav.CalendarTimeZone(), Privileges()], parse_props=False)
        def tags(key):
            value = props.get(key)
            return sorted({str(child.tag) for child in value.iter() if child is not value}) if value is not None else []
        owner = props.get(dav.Owner.tag)
        owner_href = owner.findtext("{DAV:}href") if owner is not None else None
        component_set = props.get(cdav.SupportedCalendarComponentSet.tag)
        declared = sorted({str(child.get("name")).upper() for child in component_set
                           if child.get("name")}) if component_set is not None else []
        timezone_value = props.get(cdav.CalendarTimeZone.tag)
        timezone_ids = []
        if timezone_value is not None and timezone_value.text:
            require(len(timezone_value.text.encode()) <= self.config.max_event_bytes, "RESPONSE_TOO_LARGE", "Calendar timezone metadata exceeds its limit.")
            try:
                tz_calendar = ICalendar.from_ical(timezone_value.text)
                timezone_ids = sorted({str(x.get("TZID")) for x in tz_calendar.walk("VTIMEZONE") if x.get("TZID")})
            except Exception:
                timezone_ids = []
        return {"discovery_origin": "authenticated_principal_calendar_home",
                "resource_types": tags(dav.ResourceType.tag),
                "declared_components": declared,
                "component_evidence": "server_property" if declared else "library_fallback_property_absent",
                "advertised_privileges": tags(Privileges.tag),
                "untrusted_owner_href": owner_href, "untrusted_timezone_ids": timezone_ids,
                "ios_visibility": "unknown_requires_device_comparison"}

    def event_ref(self, calendar_ref, href, etag, event):
        start, _, _ = bounds(event, ZoneInfo(self.config.timezone))
        rid = event.decoded("RECURRENCE-ID") if "RECURRENCE-ID" in event else event.decoded("DTSTART")
        return self.ids.issue("event", calendar_ref=calendar_ref, href=href, uid=str(event["UID"]),
                              etag=etag, occurrence=identity(rid, ZoneInfo(self.config.timezone)), instance_start=start.isoformat())

    def get_events(self, calendar_ref, start, end, offset=0, limit=25):
        self.prevalidate(calendar_ref)
        a, b = window(start, end, self.config)
        with self.connection() as client:
            _, root, calendar, _ = self.selected(client, calendar_ref)
            # Calendar-query supplies recurring resources; local expansion/filtering is authoritative.
            resources = calendar.search(start=a, end=b, event=True, expand=False,
                                        server_expand=False, split_expanded=False, post_filter=False)
            require(len(resources) <= self.config.max_calendar_resources, "LIMIT_EXCEEDED", "Too many resources; narrow the date window.")
            rows = []
            for resource in resources:
                href = self.resource(root, str(resource.url))
                parsed, etag, _ = self.get_resource(client, root, href)
                for event in expand(parsed, a, b, self.config):
                    s, e, all_day = bounds(event, ZoneInfo(self.config.timezone))
                    summary = str(event.get("SUMMARY", ""))
                    rid = event.decoded("RECURRENCE-ID") if "RECURRENCE-ID" in event else event.decoded("DTSTART")
                    rows.append({"event_ref": self.event_ref(calendar_ref, href, etag, event),
                        "calendar_ref": calendar_ref, "resource_href": href, "uid": str(event["UID"]), "etag": etag,
                        "recurrence_id": identity(rid, ZoneInfo(self.config.timezone)), "start": s.isoformat(), "end": e.isoformat(),
                        "all_day": all_day, "untrusted_summary": summary[:512], "summary_truncated": len(summary)>512})
                require(len(rows) <= 20_000, "EXPANSION_LIMIT", "Too many occurrences; narrow the date window.")
        rows.sort(key=lambda x:(x["start"],x["uid"],x["recurrence_id"],x["resource_href"]))
        return {"events": rows[offset:offset+limit], "total": len(rows), "window_start": a.isoformat(), "window_end": b.isoformat(),
                "window_end_exclusive": True, "next_offset": offset+limit if offset+limit < len(rows) else None}

    def fetch_event(self, event_ref, offset=0, limit=16000):
        obj = self.ids.decode(event_ref, "event")
        root = self.prevalidate(obj["calendar_ref"])["href"]
        self.resource(root, obj["href"])
        with self.connection() as client:
            _, root, _, _ = self.selected(client, obj["calendar_ref"])
            parsed, etag, raw = self.get_resource(client, root, obj["href"])
            require(etag == obj["etag"], "STALE_REFERENCE", "Resource ETag changed; retrieve events again.")
            occurrence(parsed, obj["uid"], obj["occurrence"], obj["instance_start"], self.config)
        data = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        require(offset <= len(data), "INVALID_OFFSET", "Offset exceeds resource length.")
        return {"event_ref": event_ref, "etag": etag, "uid": obj["uid"], "recurrence_id": obj["occurrence"],
                "format": "complete VCALENDAR resource; includes series and exceptions", "untrusted_data": data[offset:offset+limit],
                "offset": offset, "total_chars": len(data), "source_sha256": hashlib.sha256(data.encode()).hexdigest(),
                "next_offset": offset+limit if offset+limit < len(data) else None,
                "complete_in_this_page": offset == 0 and limit >= len(data)}

    def conditional(self, client, root, href, method, raw="", etag=None):
        self.resource(root, href)
        headers = {"Content-Type": "text/calendar; charset=utf-8", "If-Match": etag} if etag else {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"}
        require(etag is None or not etag.startswith("W/"), "WEAK_ETAG", "Mutations require a strong ETag.")
        try:
            response = client.request(href, method, raw, headers=headers)
        except ConnectorError:
            raise
        except Exception:
            raise ConnectorError("CALDAV_AMBIGUOUS", "CalDAV mutation ended without a definitive response; inspect the resource before another operation.") from None
        require(response.status != 412, "CONFLICT", "ETag precondition failed; retrieve the current resource before editing.")
        require(response.status in (200, 201, 204), "CALDAV_WRITE_FAILED", "CalDAV rejected the mutation.")
        return response.headers.get("ETag") or response.headers.get("etag")

    def create_event(self, calendar_ref, event, operation_id):
        self.prevalidate(calendar_ref)
        import hmac
        uid = hmac.new(self.key, (self.ids.account+operation_id).encode(), hashlib.sha256).hexdigest()+"@icloud-mcp.invalid"
        parsed = ICalendar(); parsed.add("VERSION", "2.0"); parsed.add("PRODID", "-//Independent iCloud MCP//EN")
        component = Event(); component.add("UID", uid)
        apply_changes(component, event, self.config); parsed.add_component(component)
        with self.connection() as client:
            _, root, _, _ = self.selected(client, calendar_ref)
            href = root+uid.split("@")[0]+".ics"
            etag = self.conditional(client, root, href, "PUT", parsed.to_ical().decode())
        return {"created": True, "calendar_ref": calendar_ref, "resource_href": href, "uid": uid, "etag": etag,
                "next_step": "Retrieve events to obtain an occurrence reference."}

    def mutation_source(self, client, event_ref, expected_etag):
        obj = self.ids.decode(event_ref, "event")
        _, root, _, _ = self.selected(client, obj["calendar_ref"])
        parsed, etag, _ = self.get_resource(client, root, obj["href"])
        require(etag == expected_etag == obj["etag"], "CONFLICT", "Expected ETag does not match this reference and current resource.")
        # RANGE=THISANDFUTURE needs separate scheduling semantics. Preserve on reads; reject
        # writes to such resources rather than misapplying an occurrence/series edit.
        require(not any(str(e.get("RECURRENCE-ID").params.get("RANGE", "")).upper() == "THISANDFUTURE"
                        for e in parsed.walk("VEVENT") if "RECURRENCE-ID" in e),
                "UNSUPPORTED_RANGE", "Resources using RANGE=THISANDFUTURE cannot be edited safely by this version.")
        require(len({str(e.get("UID")) for e in parsed.walk("VEVENT")}) == 1, "MULTI_UID_RESOURCE",
                "Resource contains multiple event UIDs; mutation is ambiguous.")
        return obj, root, parsed

    def update_event(self, event_ref, expected_etag, scope, changes):
        obj = self.ids.decode(event_ref, "event")
        self.resource(self.prevalidate(obj["calendar_ref"])["href"], obj["href"])
        with self.connection() as client:
            obj, root, parsed = self.mutation_source(client, event_ref, expected_etag)
            events = parsed.walk("VEVENT")
            master = next((e for e in events if "RECURRENCE-ID" not in e), None)
            require(master is not None, "INVALID_EVENT", "Resource has no series master.")
            if scope == "series":
                target = master
            else:
                require(not any(k in changes for k in ("rrule", "exdates", "rdates")), "INVALID_SCOPE", "Recurrence rule changes require series scope.")
                existing = next((e for e in events if "RECURRENCE-ID" in e and identity(e.decoded("RECURRENCE-ID"), ZoneInfo(self.config.timezone)) == obj["occurrence"]), None)
                selected = occurrence(parsed, obj["uid"], obj["occurrence"], obj["instance_start"], self.config)
                if not any(k in master for k in ("RRULE", "RDATE")) and existing is None:
                    target = master  # A non-recurring event has one occurrence.
                elif existing is not None:
                    target = existing
                else:
                    target = deepcopy(selected)
                    for k in ("RRULE", "RDATE", "EXDATE", "EXRULE"):
                        target.pop(k, None)
                    if "RECURRENCE-ID" not in target:
                        target.add("RECURRENCE-ID", selected.decoded("DTSTART"))
                    parsed.add_component(target)
            apply_changes(target, changes, self.config)
            etag = self.conditional(client, root, obj["href"], "PUT", parsed.to_ical().decode(), expected_etag)
        return {"updated": True, "scope": scope, "uid": obj["uid"], "resource_href": obj["href"], "etag": etag,
                "old_reference_invalid": True}

    def delete_event(self, event_ref, expected_etag, scope):
        obj = self.ids.decode(event_ref, "event")
        self.resource(self.prevalidate(obj["calendar_ref"])["href"], obj["href"])
        with self.connection() as client:
            obj, root, parsed = self.mutation_source(client, event_ref, expected_etag)
            master = next((e for e in parsed.walk("VEVENT") if "RECURRENCE-ID" not in e), None)
            require(master is not None, "INVALID_EVENT", "Resource has no series master.")
            if scope == "series" or not any(k in master for k in ("RRULE", "RDATE")):
                self.conditional(client, root, obj["href"], "DELETE", etag=expected_etag)
            else:
                selected = occurrence(parsed, obj["uid"], obj["occurrence"], obj["instance_start"], self.config)
                original = selected.decoded("RECURRENCE-ID") if "RECURRENCE-ID" in selected else selected.decoded("DTSTART")
                parsed.subcomponents = [e for e in parsed.subcomponents if not (e.name == "VEVENT" and "RECURRENCE-ID" in e and identity(e.decoded("RECURRENCE-ID"), ZoneInfo(self.config.timezone)) == obj["occurrence"])]
                master.add("EXDATE", original)
                self.conditional(client, root, obj["href"], "PUT", parsed.to_ical().decode(), expected_etag)
        return {"deleted": True, "scope": scope, "uid": obj["uid"], "old_reference_invalid": True}
