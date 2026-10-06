"""The live harness itself is exercised with synthetic, permission-enforced peers."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_bounded_harness_complete_message_attachment_and_recurrence(make_connector):
    c = make_connector(profile='read-only')
    calendar = next(x['calendar_id'] for x in (await c.execute('list_calendars', {}))['result']['calendars']
                    if x['resource_href'] == c.fake_dav.collections[0].url)
    plan = dict(folder='Archive/Quoted "Folder"', ascii_query='needle', unicode_query='café',
                calendar_ids=[calendar], start='2026-03-07', end='2026-03-12', ios_visible_calendar_ids=[calendar])
    validator = script('live_validation').Validator(c.execute, c.config, plan)
    result = await validator.run()
    assert result['ok'], result['errors']
    assert result['checks']['ascii_search']['keyword_verified_in_complete_decoded_sample']
    assert result['checks']['unicode_search']['request_accepted']
    assert not result['checks']['unicode_search']['positive_match_observed']
    assert result['checks']['full_message']['section_pages']['text'] > 1
    assert result['checks']['full_message']['complete_sections']
    assert result['checks']['attachment']['sha256_verified']
    assert any(v.get('exception_resources') for v in result['checks'].values())
    assert any(v.get('utc_offsets_observed_count') == 2 for v in result['checks'].values())
    assert len(result['collections']) == 6 and result['writes_attempted'] == 0
    assert len(validator.inventory) == 6
    assert 'Synthetic body' not in json.dumps(result) and 'calendar-0' not in json.dumps(result)
    assert all(x[2] for x in c.fake_imap.calls if x[0] == 'select')
    assert not any(x[0] in ('PUT','DELETE','move','uid_expunge') for x in c.fake_dav.calls+c.fake_imap.calls)


async def test_positive_unicode_and_all_day_live_harness_fixture(make_connector):
    from email import policy
    from email.parser import BytesParser
    c = make_connector(profile='read-only')
    folder = 'Archive/Quoted "Folder"'
    msg = BytesParser(policy=policy.default).parsebytes(c.fake_imap.boxes[folder][42])
    msg.get_body(preferencelist=('plain',)).set_content('Synthetic needle café', cte='8bit')
    c.fake_imap.boxes[folder][42] = msg.as_bytes()
    calendar = next(x['calendar_id'] for x in (await c.execute('list_calendars', {}))['result']['calendars']
                    if x['resource_href'] == c.fake_dav.collections[0].url)
    c.fake_dav.resources[c.fake_dav.collections[0].url+'all-day.ics'] = [
        b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-all-day\r\nDTSTART;VALUE=DATE:20260307\r\nDTEND;VALUE=DATE:20260308\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n', '"all-day-etag"']
    plan = dict(folder=folder, ascii_query='needle', unicode_query='café', calendar_ids=[calendar],
                start='2026-03-07', end='2026-03-12')
    result = await script('live_validation').Validator(c.execute, c.config, plan).run()
    assert result['ok'], result['errors']
    assert result['checks']['unicode_search']['keyword_verified_in_complete_decoded_sample']
    assert any(v.get('all_day_samples') for v in result['checks'].values())


def test_tunnel_doctor_diagnostics_do_not_expose_secret_or_private_context():
    s = script('run_tunnel')
    output = json.dumps({'checks':[{'status':'failed','message':'sk-synthetic-secret PRIVATE account details'}],
                         'api_key':'sk-synthetic-secret'})
    summary = s.doctor_summary(output, 1)
    assert summary['check_status_counts']['failed'] == 1
    assert 'secret' not in json.dumps(summary) and 'PRIVATE' not in json.dumps(summary)


async def test_unicode_search_reaches_real_library_normalizer(make_connector):
    from imapclient.imapclient import _normalise_search_criteria
    c = make_connector(profile='read-only')
    original = c.fake_imap.search
    def normalized(criteria, charset=None):
        wire = _normalise_search_criteria(criteria, charset)
        assert wire[1] == 'café "literal"'.encode('utf-8') or b'caf' in wire[1]
        return original(criteria, charset)
    c.fake_imap.search = normalized
    result = await c.execute('search_messages', {'folder':'INBOX', 'query':'café "literal"'})
    assert result['ok'], result
    assert next(x for x in c.fake_imap.calls if x[0]=='search')[2] == 'UTF-8'


async def test_unicode_rejection_is_redacted_not_empty_success(make_connector):
    import imaplib
    c = make_connector(profile='read-only')
    def fail(*args, **kwargs):
        raise imaplib.IMAP4.error('PRIVATE keyword and provider response')
    c.fake_imap.search = fail
    result = await c.execute('search_messages', {'folder':'INBOX', 'query':'café'})
    assert result['error']['code'] == 'SEARCH_ENCODING_UNSUPPORTED'
    assert 'PRIVATE' not in json.dumps(result)


async def test_harness_rejects_changed_pages_and_mail_flags(make_connector):
    c = make_connector(profile='read-only')
    v = script('live_validation')
    ref = c.ids.issue('message', folder='INBOX', uidvalidity=100, uid=1)
    validator = v.Validator(c.execute, c.config, {})
    with pytest.raises(v.CheckError) as error:
        await validator.pages('fetch_message', 'message_ref', ref, section='text', expected_flags=['\\Seen'])
    assert error.value.code == 'FLAGS_CHANGED'
    async def inconsistent(name, args):
        result = await c.execute(name, args)
        if args.get('offset'):
            result['result']['source_sha256'] = 'different'
        return result
    validator = v.Validator(inconsistent, c.config, {})
    with pytest.raises(v.CheckError) as error:
        await validator.pages('fetch_message', 'message_ref', ref, section='text', expected_flags=[])
    assert error.value.code == 'PAGE_SOURCE_CHANGED'


async def test_harness_budget_and_direct_write_rejection(make_connector):
    c = make_connector(profile='read-only')
    v = script('live_validation')
    validator = v.Validator(c.execute, c.config, {}, max_calls=0)
    with pytest.raises(v.CheckError) as error:
        await validator.call('list_calendars')
    assert error.value.code == 'VALIDATION_BUDGET'
    with pytest.raises(v.CheckError) as error:
        await validator.call('send_message')
    assert error.value.code == 'WRITE_PROHIBITED'
    assert not c.fake_imap.calls and not c.fake_dav.calls


def test_dedicated_credential_setup_private_independent_and_no_overwrite(tmp_path):
    s = script('setup_credentials')
    config = s.save_setup(tmp_path, 'owner@example.invalid', 'login@example.invalid', 'America/Chicago', 'synthetic-password')
    assert config.stat().st_mode & 0o777 == 0o600
    password = tmp_path/'.config/icloud_app_password'
    assert password.stat().st_mode & 0o777 == 0o600
    assert (tmp_path/'.state').stat().st_mode & 0o777 == 0o700
    assert 'synthetic-password' not in config.read_text()
    with pytest.raises(ValueError):
        s.save_setup(tmp_path, 'other@example.invalid', 'other@example.invalid', 'UTC', 'different')
    assert password.read_text().strip() == 'synthetic-password'


def test_credential_setup_rejects_bad_permissions_and_invalid_zone(tmp_path):
    s = script('setup_credentials')
    (tmp_path/'.config').mkdir(mode=0o755)
    with pytest.raises(ValueError):
        s.save_setup(tmp_path, 'owner@example.invalid', 'login', 'UTC', 'synthetic')
    (tmp_path/'.config').chmod(0o700)
    with pytest.raises(Exception):
        s.save_setup(tmp_path, 'owner@example.invalid', 'login', 'Invalid/Zone', 'synthetic')
    assert not (tmp_path/'.config/icloud_app_password').exists()


def test_private_plan_and_inventory_no_overwrite(tmp_path):
    v = script('live_validation')
    plan = tmp_path/'plan.json'
    plan.write_text('{"folder":"INBOX"}'); plan.chmod(0o600)
    assert v.read_plan(plan)['folder'] == 'INBOX'
    plan.chmod(0o644)
    with pytest.raises(v.CheckError):
        v.read_plan(plan)
    v.save_inventory(tmp_path, [{'collection':'C1'}], [{'folder':'INBOX'}])
    path = tmp_path/'live-discovery.json'
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    v.save_inventory(tmp_path, [], [])
    assert path.read_bytes() == before


async def test_metadata_keeps_same_named_collections_and_declared_task_type(make_connector):
    c = make_connector(profile='read-only')
    result = (await c.execute('list_calendars', {}))['result']
    assert result['total'] == 6
    assert all(x['component_evidence'] == 'server_property' for x in result['calendars'])
    assert sum(x['declared_components'] == ['VTODO'] for x in result['calendars']) == 1
    assert len({x['calendar_id'] for x in result['calendars']}) == 6
    assert all(x['ios_visibility'] == 'unknown_requires_device_comparison' for x in result['calendars'])
