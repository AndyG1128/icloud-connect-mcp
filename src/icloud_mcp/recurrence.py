"""RFC 5545 parsing and expansion via maintained iCalendar libraries."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event, vRecur
import recurring_ical_events
from .errors import require

UTC = timezone.utc


def localize(dt, zone):
    if dt.tzinfo:
        return dt
    candidate = dt.replace(tzinfo=zone)
    require(candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == dt,
            "INVALID_LOCAL_TIME", "Local time falls inside a daylight-saving gap; provide a valid timestamp.")
    require(candidate.utcoffset() == dt.replace(tzinfo=zone, fold=1).utcoffset(),
            "AMBIGUOUS_LOCAL_TIME", "Repeated local time requires an explicit UTC offset.")
    return candidate


def parse_time(value, zone, all_day=False):
    try:
        parsed = date.fromisoformat(value) if all_day else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        require(False, "INVALID_DATE", "Use ISO dates for all-day events and ISO timestamps otherwise.")
    return parsed if all_day else localize(parsed, zone)


def instant(value, zone):
    if isinstance(value, datetime):
        return localize(value, zone).astimezone(UTC)
    return datetime.combine(value, time.min, zone).astimezone(UTC)


def identity(value, zone=None):
    if isinstance(value, datetime):
        return "T:" + localize(value, zone or UTC).astimezone(UTC).isoformat()
    return "D:" + value.isoformat()


def window(start, end, config):
    zone = ZoneInfo(config.timezone)
    def endpoint(s):
        return instant(parse_time(s, zone, all_day=len(s) == 10), zone)
    a, b = endpoint(start), endpoint(end)
    require(a < b and b-a <= timedelta(days=config.max_date_days), "INVALID_WINDOW",
            "Provide a positive date window within the configured maximum range.")
    return a, b


def normalized(calendar, zone):
    result = deepcopy(calendar)
    for event in result.walk("VEVENT"):
        for key in ("DTSTART", "DTEND", "RECURRENCE-ID"):
            if key in event:
                value = event.decoded(key)
                if isinstance(value, datetime) and value.tzinfo is None:
                    event[key].dt = localize(value, zone)
        # EXDATE/RDATE inherit the configured timezone for floating datetimes.
        for key in ("EXDATE", "RDATE"):
            values = event.get(key, [])
            for group in values if isinstance(values, list) else [values]:
                for item in group.dts:
                    if isinstance(item.dt, datetime) and item.dt.tzinfo is None:
                        item.dt = localize(item.dt, zone)
                    elif isinstance(item.dt, tuple):
                        item.dt = tuple(localize(v, zone) if isinstance(v, datetime) and v.tzinfo is None else v for v in item.dt)
    return result


def bounds(event, zone):
    require("DTSTART" in event, "INVALID_EVENT", "Event has no DTSTART.")
    start = event.decoded("DTSTART")
    end = event.decoded("DTEND") if "DTEND" in event else start + event.decoded("DURATION") if "DURATION" in event else start + (timedelta(days=1) if not isinstance(start, datetime) else timedelta())
    return instant(start, zone), instant(end, zone), not isinstance(start, datetime)


def expansion_cost(calendar, a, b):
    estimate = 0
    periods = {"SECONDLY": 1, "MINUTELY": 60, "HOURLY": 3600, "DAILY": 86400,
               "WEEKLY": 604800, "MONTHLY": 2419200, "YEARLY": 31536000}
    for e in calendar.walk("VEVENT"):
        rule = e.get("RRULE")
        if not rule:
            estimate += 1; continue
        freq = str(rule.get("FREQ", [""])[0])
        require(freq in periods, "INVALID_RECURRENCE", "Unsupported or malformed recurrence frequency.")
        multiplier = 1
        for key in ("BYHOUR", "BYMINUTE", "BYSECOND", "BYMONTHDAY", "BYDAY", "BYMONTH"):
            if key in rule:
                multiplier *= len(rule[key])
        cost = max(1, int((b-a).total_seconds()/periods[freq])+2)*multiplier
        if rule.get("COUNT"):
            cost = min(cost, int(rule["COUNT"][0]))
        estimate += cost
    return estimate


def exists(value):
    """RFC 5545 ignores generated nonexistent wall times (spring-forward gaps)."""
    return not isinstance(value, datetime) or value.tzinfo is None or value.astimezone(UTC).astimezone(value.tzinfo).replace(tzinfo=None) == value.replace(tzinfo=None)


def correct_gap_counts(calendar, end, config):
    """The library counts imaginary dateutil slots. Adjust a private expansion copy
    so COUNT counts valid instances; never rewrite the stored iCalendar resource.
    EXDATE/RDATE/overrides do not change the count of the underlying RRULE slots.
    Maintained library expansion remains the only recurrence generator.
    """
    zone = ZoneInfo(config.timezone)
    for master in calendar.walk("VEVENT"):
        rule = master.get("RRULE")
        if "RECURRENCE-ID" in master or not rule or not rule.get("COUNT"):
            continue
        original = int(rule["COUNT"][0])
        require(1 <= original <= 20_000, "EXPANSION_LIMIT", "COUNT exceeds the safe recurrence prefix budget.")
        start = instant(master.decoded("DTSTART"), zone)
        if start >= end:
            continue
        require(exists(master.decoded("DTSTART")), "INVALID_LOCAL_TIME", "Series DTSTART is a nonexistent local time.")
        bare = copy_rule_calendar(calendar, master)
        adjusted = original
        for _ in range(8):
            component = bare.walk("VEVENT")[0]
            component["RRULE"]["COUNT"] = [adjusted]
            require(expansion_cost(bare, start, end) <= 20_000, "EXPANSION_LIMIT", "Recurrence prefix exceeds its budget.")
            slots = recurring_ical_events.of(bare).between(start, end)
            require(len(slots) <= 20_000, "EXPANSION_LIMIT", "Too many recurrence prefix instances.")
            needed = original + sum(not exists(e.decoded("DTSTART")) for e in slots)
            if needed == adjusted:
                rule["COUNT"] = [adjusted]
                break
            adjusted = needed
        else:
            require(False, "EXPANSION_LIMIT", "Recurrence gap correction did not converge within its budget.")


def copy_rule_calendar(calendar, master):
    bare = Calendar()
    bare.add("VERSION", "2.0")
    for component in calendar.subcomponents:
        if component.name == "VTIMEZONE":
            bare.add_component(deepcopy(component))
    single = deepcopy(master)
    for prop in ("EXDATE", "EXRULE", "RDATE"):
        single.pop(prop, None)
    bare.add_component(single)
    return bare


def expand(calendar, a, b, config):
    require(expansion_cost(calendar, a, b) <= 20_000, "EXPANSION_LIMIT",
            "Recurrence expansion would exceed its budget; use a narrower date window.")
    zone = ZoneInfo(config.timezone)
    cal = normalized(calendar, zone)
    correct_gap_counts(cal, b, config)
    candidates = recurring_ical_events.of(cal, keep_recurrence_attributes=True).between(a, b)
    out = []
    for event in candidates:
        if not exists(event.decoded("DTSTART")):
            continue
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start, end, all_day = bounds(event, zone)
        if (start < b and end > a) or (start == end and a <= start < b):
            out.append(event)
    require(len(out) <= 20_000, "EXPANSION_LIMIT", "Too many occurrences; use a narrower date window.")
    return out


def occurrence(calendar, uid, rid, instance_start, config):
    events = [e for e in calendar.walk("VEVENT") if str(e.get("UID", "")) == uid]
    require(bool(events), "EVENT_NOT_FOUND", "UID no longer exists in this calendar resource.")
    for e in events:
        if "RECURRENCE-ID" in e and identity(e.decoded("RECURRENCE-ID"), ZoneInfo(config.timezone)) == rid:
            return e
    a = datetime.fromisoformat(instance_start)
    candidates = expand(calendar, a-timedelta(days=1), a+timedelta(days=2), config)
    for e in candidates:
        value = e.decoded("RECURRENCE-ID") if "RECURRENCE-ID" in e else e.decoded("DTSTART")
        if str(e.get("UID", "")) == uid and identity(value, ZoneInfo(config.timezone)) == rid:
            return e
    require(False, "OCCURRENCE_NOT_FOUND", "Occurrence no longer exists; retrieve events again.")


def apply_changes(event, changes, config):
    zone = ZoneInfo(changes.get("timezone", config.timezone))
    for k, prop in {"summary": "SUMMARY", "description": "DESCRIPTION", "location": "LOCATION", "status": "STATUS"}.items():
        if k in changes:
            event.pop(prop, None); event.add(prop, changes[k])
    if any(k in changes for k in ("start", "end", "all_day", "timezone")):
        require("start" in changes and "end" in changes, "INVALID_EVENT", "Time changes require both start and end.")
        all_day = changes.get("all_day", False)
        start, end = parse_time(changes["start"], zone, all_day), parse_time(changes["end"], zone, all_day)
        require(end > start, "INVALID_EVENT", "Event end must follow start; all-day end is exclusive.")
        if isinstance(start, datetime):
            start, end = start.astimezone(zone), end.astimezone(zone)
        for prop in ("DTSTART", "DTEND", "DURATION"):
            event.pop(prop, None)
        event.add("DTSTART", start); event.add("DTEND", end)
    if "rrule" in changes:
        event.pop("RRULE", None)
        if changes["rrule"]:
            rule = vRecur.from_ical(changes["rrule"])
            require(str(rule.get("FREQ", [""])[0]) in ("SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"),
                    "INVALID_RECURRENCE", "Invalid RRULE frequency.")
            event.add("RRULE", rule)
    all_day = not isinstance(event.decoded("DTSTART"), datetime)
    for k, prop in (("exdates", "EXDATE"), ("rdates", "RDATE")):
        if k in changes:
            event.pop(prop, None)
            values = [parse_time(s, zone, all_day) for s in changes[k]]
            if values:
                event.add(prop, values)
    if "attendees" in changes:
        event.pop("ATTENDEE", None)
        from .smtp import address
        for email in changes["attendees"]:
            event.add("ATTENDEE", "mailto:" + address(email))
    # Existing unsupported properties, VALARMs, TZIDs and exceptions remain in the resource.
    start, end, _ = bounds(event, ZoneInfo(config.timezone))
    require(end >= start, "INVALID_EVENT", "Invalid event interval.")
    event.pop("DTSTAMP", None); event.add("DTSTAMP", datetime.now(UTC))
    event["SEQUENCE"] = int(event.get("SEQUENCE", 0)) + 1
