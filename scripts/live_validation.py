"""Bounded read-only checks. Content stays in memory; reports contain counts only."""
import asyncio
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import unicodedata
from zoneinfo import ZoneInfo
from icalendar import Calendar
from icloud_mcp.permissions import READ
from icloud_mcp.recurrence import bounds, expand, identity, window


class CheckError(Exception):
    def __init__(self, code):
        self.code = code if re.fullmatch(r'[A-Z0-9_]{1,80}', code) else 'REMOTE_ERROR'


def insist(value, code='ASSERTION_FAILED'):
    if not value:
        raise CheckError(code)


def read_plan(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as file:
        info = os.fstat(file.fileno())
        insist(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
               and not info.st_mode & 0o077 and info.st_nlink == 1 and info.st_size <= 64_000, 'PLAN_PERMISSIONS')
        plan = json.load(file)
    insist(isinstance(plan, dict), 'INVALID_PLAN')
    insist(set(plan) <= {'folder', 'ascii_query', 'unicode_query', 'calendar_ids',
                        'start', 'end', 'ios_visible_calendar_ids', 'additional_windows'}, 'INVALID_PLAN')
    insist(isinstance(plan.get('calendar_ids', []), list) and len(plan.get('calendar_ids', [])) <= 10, 'INVALID_PLAN')
    insist(len(plan.get('additional_windows', [])) <= 3, 'INVALID_PLAN')
    return plan


class Validator:
    def __init__(self, call, config, plan, *, max_calls=160):
        self.remote, self.config, self.plan = call, config, plan
        self.calls, self.max_calls = 0, max_calls
        self.deadline = time.monotonic() + 600
        self.report = {'ok': True, 'checks': {}, 'errors': [], 'unverified': []}
        self.inventory = []

    async def call(self, tool, **arguments):
        insist(tool in READ, 'WRITE_PROHIBITED')
        insist(self.calls < self.max_calls and time.monotonic() < self.deadline, 'VALIDATION_BUDGET')
        self.calls += 1
        response = await asyncio.wait_for(self.remote(tool, arguments), min(40, self.deadline-time.monotonic()))
        if not response.get('ok'):
            raise CheckError(response.get('error', {}).get('code', 'REMOTE_ERROR'))
        return response['result']

    async def attempt(self, label, fn):
        try:
            self.report['checks'][label] = await fn()
        except CheckError as error:
            self.report['ok'] = False
            self.report['errors'].append({'check': label, 'code': error.code})
        except Exception:
            self.report['ok'] = False
            self.report['errors'].append({'check': label, 'code': 'CHECK_FAILED_REDACTED'})

    async def pages(self, tool, key, value, *, section=None, expected_flags=None, source_hash=None):
        offset, chunks, digest, total, pages = 0, [], source_hash, None, 0
        while True:
            args = {key: value, 'offset': offset, 'limit': min(self.config.max_page_chars, 16000)}
            if section is not None:
                args['section'] = section
            page = await self.call(tool, **args)
            insist(page['offset'] == offset, 'PAGE_OFFSET')
            insist(0 <= page['total_chars'] <= 2_000_000, 'VALIDATION_CONTENT_LIMIT')
            total = page['total_chars'] if total is None else total
            insist(page['total_chars'] == total, 'PAGE_TOTAL_CHANGED')
            digest = page['source_sha256'] if digest is None else digest
            insist(page['source_sha256'] == digest, 'PAGE_SOURCE_CHANGED')
            if tool == 'fetch_message':
                insist(page['flags_verified_unchanged'] and page['flags'] == expected_flags, 'FLAGS_CHANGED')
            chunk = page['untrusted_data']
            insist(isinstance(chunk, str) and len(chunk) <= args['limit'], 'PAGE_SIZE')
            chunks.append(chunk)
            pages += 1
            following = page['next_offset']
            if following is None:
                insist(offset + len(chunk) == total, 'INCOMPLETE_CONTENT')
                break
            insist(following == offset + len(chunk) and following > offset, 'PAGE_PROGRESS')
            offset = following
        data = ''.join(chunks)
        insist(len(data) == total, 'INCOMPLETE_CONTENT')
        if tool == 'fetch_event':
            insist(hashlib.sha256(data.encode()).hexdigest() == digest, 'RESOURCE_HASH')
        return data, digest, pages

    async def discover(self):
        async def all_rows(tool, key):
            offset, rows, total = 0, [], None
            while True:
                page = await self.call(tool, offset=offset, limit=min(self.config.max_results, 100))
                total = page['total'] if total is None else total
                insist(total == page['total'] and total <= (10000 if key == 'folders' else 200), 'DISCOVERY_LIMIT_OR_CHANGED')
                rows.extend(page[key])
                if page['next_offset'] is None:
                    break
                insist(page['next_offset'] == len(rows) and page['next_offset'] > offset, 'PAGE_PROGRESS')
                offset = page['next_offset']
            insist(len(rows) == total, 'INCOMPLETE_DISCOVERY')
            return rows
        self.folders = await all_rows('list_mail_folders', 'folders')
        self.calendars = await all_rows('list_calendars', 'calendars')
        insist(len({row['calendar_id'] for row in self.calendars}) == len(self.calendars), 'COLLECTION_IDENTITIES')
        visible = self.plan.get('ios_visible_calendar_ids')
        if visible is not None:
            insist(isinstance(visible, list) and set(visible) <= {x['calendar_id'] for x in self.calendars}, 'IOS_MAPPING_INVALID')
        for index, row in enumerate(self.calendars, 1):
            self.inventory.append({'collection': f'C{index}', **row})
            comps = row.get('declared_components') or row['supported_components']
            kind = ('event_and_task_collection' if 'VEVENT' in comps and 'VTODO' in comps
                    else 'event_collection' if 'VEVENT' in comps
                    else 'task_collection' if 'VTODO' in comps else 'other_component_collection')
            self.report.setdefault('collections', []).append({
                'collection': f'C{index}', 'supported_components': comps, 'classification': kind,
                'component_evidence': row.get('component_evidence', 'unknown'),
                'resource_types': row.get('resource_types', []),
                'discovery_origin': row.get('discovery_origin', 'unknown'),
                'owner_metadata_present': bool(row.get('untrusted_owner_href')),
                'timezone_metadata_present': bool(row.get('untrusted_timezone_ids')),
                'ios_visible': row['calendar_id'] in visible if visible is not None else 'unverified'})
        if visible is None:
            self.report['unverified'].append('iOS visibility needs operator comparison using the private inventory; no name-based explanation inferred.')
        return {'folders': len(self.folders), 'collections': len(self.calendars), 'all_pages_retrieved': True}

    async def search(self, kind):
        query = self.plan.get(kind + '_query')
        if not query:
            self.report['unverified'].append(kind + '_search: configure a locally selected known keyword.')
            return {'status': 'unrun'}
        insist(query.isascii() if kind == 'ascii' else not query.isascii(), 'KEYWORD_KIND')
        page = await self.call('search_messages', folder=self.plan['folder'], query=query, limit=min(self.config.max_results, 5))
        if page['total'] == 0:
            self.report['unverified'].append(kind + '_search: request accepted but no match; matching correctness unverified.')
        matched = False
        sample = next((x for x in page['messages'] if 0 < (x.get('size_bytes') or 0) <= 262144), None)
        if sample:
            texts, digest = [], None
            for section in ('headers', 'text', 'html'):
                data, digest, _ = await self.pages('fetch_message', 'message_ref', sample['message_ref'],
                    section=section, expected_flags=sample['flags'], source_hash=digest)
                document = json.loads(data)
                if section == 'headers':
                    from email.header import decode_header, make_header
                    texts.extend(str(make_header(decode_header(value))) for _, value in document['headers'])
                else:
                    texts.extend(part['content'] for part in document)
            needle = unicodedata.normalize('NFC', query).casefold()
            matched = any(needle in unicodedata.normalize('NFC', text).casefold() for text in texts)
            if not matched:
                self.report['unverified'].append(kind + '_search: match not confirmed in decoded headers/text/HTML; attachment-only matches are not inspected here.')
        return {'request_accepted': True, 'matches': page['total'], 'positive_match_observed': page['total'] > 0,
                'keyword_verified_in_complete_decoded_sample': matched}

    async def message(self):
        page = await self.call('search_messages', folder=self.plan['folder'], limit=min(self.config.max_results, 10))
        samples = [x for x in page['messages'] if 0 < (x.get('size_bytes') or 0) <= 262144]
        if not samples:
            self.report['unverified'].append('Full message: no sample <=256 KiB among the first ten UIDs in the selected folder.')
            return {'status': 'no_bounded_sample'}
        chosen = samples[0]
        self.message_sample = chosen
        attachments, digest, totals, page_counts = [], None, {}, {}
        for section in ('headers', 'text', 'html', 'attachments'):
            data, digest, pages = await self.pages('fetch_message', 'message_ref', chosen['message_ref'],
                section=section, expected_flags=chosen['flags'], source_hash=digest)
            document = json.loads(data)
            totals[section], page_counts[section] = len(data), pages
            if section == 'headers':
                insist(isinstance(document['headers'], list) and bool(document['wire_headers_base64']), 'HEADERS_INCOMPLETE')
                base64.b64decode(document['wire_headers_base64'], validate=True)
            elif section in ('text', 'html'):
                for part in document:
                    base64.b64decode(part['raw_content_base64'], validate=True)
                    insist(isinstance(part['content'], str), 'BODY_INCOMPLETE')
            else:
                attachments = document
        self.attachments = attachments
        self.message_digest = digest
        return {'source_bytes': chosen['size_bytes'], 'section_chars': totals, 'section_pages': page_counts,
                'complete_sections': True, 'source_hash_consistent': True, 'attachments': len(attachments),
                'flags_unchanged_across_reads': True, 'non_inbox': page['folder'].upper() != 'INBOX'}

    async def attachment(self):
        selected = next((x for x in getattr(self, 'attachments', []) if 0 <= x['size_bytes'] <= 65536), None)
        if selected is None:
            self.report['unverified'].append('Attachment: selected message has no attachment <=64 KiB. Select another sample for coverage.')
            return {'status': 'no_bounded_sample'}
        data, offset, digest = b'', 0, None
        while True:
            page = await self.call('fetch_attachment', attachment_ref=selected['attachment_ref'],
                offset=offset, limit=min(self.config.max_attachment_chunk, 48000))
            insist(page['offset_bytes'] == offset and page['total_bytes'] == selected['size_bytes'], 'ATTACHMENT_SIZE')
            insist(page['flags_verified_unchanged'], 'FLAGS_CHANGED')
            digest = digest or page['sha256']
            insist(page['sha256'] == digest, 'ATTACHMENT_CHANGED')
            data += base64.b64decode(page['untrusted_data_base64'], validate=True)
            insist(len(data) <= 65536, 'VALIDATION_CONTENT_LIMIT')
            if page['next_offset'] is None:
                break
            insist(page['next_offset'] == len(data) and len(data) > offset, 'PAGE_PROGRESS')
            offset = page['next_offset']
        insist(len(data) == selected['size_bytes'] and hashlib.sha256(data).hexdigest() == digest, 'ATTACHMENT_HASH')
        await self.pages('fetch_message', 'message_ref', self.message_sample['message_ref'], section='headers',
                         expected_flags=self.message_sample['flags'], source_hash=self.message_digest)
        return {'complete_bytes': len(data), 'sha256_verified': True, 'flags_unchanged': True}

    async def events(self, row, start, end):
        a, b = window(start, end, self.config)
        page = await self.call('get_events', calendar_ref=row['calendar_ref'], start=start, end=end,
                               limit=min(self.config.max_results, 5))
        for event in page['events']:
            s, e = datetime.fromisoformat(event['start']), datetime.fromisoformat(event['end'])
            insist(s.tzinfo is not None and e.tzinfo is not None, 'TIMEZONE_MISSING')
            insist((s < b and e > a) if s != e else a <= s < b, 'WINDOW_OVERLAP')
            insist(event['calendar_ref'] == row['calendar_ref'] and bool(event['uid']) and bool(event['etag'])
                   and bool(event['recurrence_id']), 'EVENT_IDENTITY')
        answer = {'events_in_window': page['total'], 'sampled': len(page['events']),
                  'precise_overlap': True, 'offsets_present': True, 'half_open_window': True,
                  'all_day_samples': 0, 'recurring_resources': 0, 'exception_resources': 0,
                  'timezone_resources': 0, 'utc_offsets_observed_count': 0,
                  'series_expansion_matches_sample': True}
        offsets = set()
        for event in page['events'][:2]:
            data, _, _ = await self.pages('fetch_event', 'event_ref', event['event_ref'])
            parsed = Calendar.from_ical(data)
            source_events = [x for x in parsed.walk('VEVENT') if str(x.get('UID', '')) == event['uid']]
            answer['recurring_resources'] += any('RRULE' in x or 'RDATE' in x for x in source_events)
            answer['exception_resources'] += any('RECURRENCE-ID' in x or 'EXDATE' in x for x in source_events)
            answer['timezone_resources'] += bool(parsed.walk('VTIMEZONE') or any(
                x.get('DTSTART') and x['DTSTART'].params.get('TZID') for x in source_events))
            matches = []
            for occurrence in expand(parsed, a, b, self.config):
                s, e, all_day = bounds(occurrence, ZoneInfo(self.config.timezone))
                rid = occurrence.decoded('RECURRENCE-ID') if 'RECURRENCE-ID' in occurrence else occurrence.decoded('DTSTART')
                if (str(occurrence['UID']) == event['uid'] and
                        identity(rid, ZoneInfo(self.config.timezone)) == event['recurrence_id'] and s.isoformat() == event['start']):
                    matches.append(occurrence)
                    insist(e.isoformat() == event['end'] and all_day == event['all_day'], 'SERIES_SAMPLE_MISMATCH')
                    if all_day:
                        local_s, local_e = s.astimezone(ZoneInfo(self.config.timezone)), e.astimezone(ZoneInfo(self.config.timezone))
                        insist(local_s.hour == local_e.hour == 0 and local_s.minute == local_e.minute == 0, 'ALL_DAY_BOUNDARY')
                        answer['all_day_samples'] += 1
            insist(len(matches) == 1, 'SERIES_SAMPLE_MISMATCH')
            for component in source_events:
                for key in ('DTSTART', 'DTEND', 'RECURRENCE-ID'):
                    if key in component:
                        value = component.decoded(key)
                        if isinstance(value, datetime) and value.tzinfo:
                            offsets.add(value.utcoffset().total_seconds())
        answer['utc_offsets_observed_count'] = len(offsets)
        if not page['events']:
            self.report['unverified'].append('Empty live event window: timezone/identity/recurrence assertions had no sample.')
        for field in ('all_day_samples', 'recurring_resources', 'exception_resources', 'timezone_resources'):
            if not answer[field]:
                self.report['unverified'].append(field + ': absent from this live sample; synthetic coverage is separate.')
        return answer

    async def run(self):
        await self.attempt('discovery', self.discover)
        if self.plan.get('folder') and hasattr(self, 'folders'):
            await self.attempt('ascii_search', lambda: self.search('ascii'))
            await self.attempt('unicode_search', lambda: self.search('unicode'))
            await self.attempt('full_message', self.message)
            await self.attempt('attachment', self.attachment)
        else:
            self.report['unverified'].append('Mail samples not configured; discovery only.')
        selected = self.plan.get('calendar_ids', [])
        for index, row in enumerate(getattr(self, 'calendars', []), 1):
            if row['calendar_id'] not in selected:
                continue
            await self.attempt(f'C{index}_events', lambda r=row: self.events(r, self.plan['start'], self.plan['end']))
            for wi, win in enumerate(self.plan.get('additional_windows', []), 1):
                await self.attempt(f'C{index}_window_{wi}', lambda r=row, w=win: self.events(r, w['start'], w['end']))
        if not selected:
            self.report['unverified'].append('Calendar samples not configured; discovery only.')
        self.report['account_tool_calls'] = self.calls
        self.report['writes_attempted'] = 0
        return self.report


def save_inventory(state_dir, inventory, folders):
    # Server has already validated its state directory. Preserve existing mapping.
    path = Path(state_dir) / 'live-discovery.json'
    if os.path.lexists(path):
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'collections': inventory, 'folders': folders}, output, ensure_ascii=False, indent=2)
