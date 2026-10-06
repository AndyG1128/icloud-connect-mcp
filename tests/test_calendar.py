from datetime import datetime, timezone
from icalendar import Calendar,Event
import pytest
from icloud_mcp.recurrence import expand, window
from icloud_mcp.calendars import allowed_url
from icloud_mcp.errors import ConnectorError
from .conftest import calendar_ref,event_ref


async def events(c,start='2026-03-07',end='2026-03-12'):
    ref=await calendar_ref(c)
    r=await c.execute('get_events',dict(calendar_ref=ref,start=start,end=end))
    assert r['ok'],r
    return ref,r['result']['events']


async def test_six_resources_preserved_and_components_identified(make_connector):
    c=make_connector();r=await c.execute('list_calendars',{})
    assert r['ok'] and r['result']['total']==6
    assert len({x['calendar_id'] for x in r['result']['calendars']})==6
    assert sum(x['supported_components']==['VEVENT'] for x in r['result']['calendars'])==5
    todo=await calendar_ref(c,5)
    assert (await c.execute('get_events',dict(calendar_ref=todo,start='2026-03-07',end='2026-03-12')))['error']['code']=='UNSUPPORTED_COMPONENT'


async def test_recurrence_exception_exdate_and_dst(make_connector):
    c=make_connector();_,rows=await events(c)
    assert len(rows)==4
    assert rows[0]['start']=='2026-03-07T15:00:00+00:00'
    assert rows[1]['start']=='2026-03-08T16:00:00+00:00'
    assert rows[1]['recurrence_id']=='T:2026-03-08T14:00:00+00:00'
    assert rows[2]['start']=='2026-03-10T14:00:00+00:00'
    assert len({r['event_ref'] for r in rows})==4


async def test_precise_half_open_overlap_and_full_fetch(make_connector):
    c=make_connector();_,rows=await events(c,'2026-03-08T11:30:00-05:00','2026-03-08T12:00:00-05:00')
    assert len(rows)==1
    _,empty=await events(c,'2026-03-08T12:00:00-05:00','2026-03-08T13:00:00-05:00');assert empty==[]
    data='';offset=0
    while True:
        r=await c.execute('fetch_event',dict(event_ref=rows[0]['event_ref'],offset=offset,limit=100))
        assert r['ok'],r
        data+=r['result']['untrusted_data'];offset=r['result']['next_offset']
        if offset is None:break
    assert len(Calendar.from_ical(data).walk('VEVENT'))==2


@pytest.mark.parametrize('zone,date_value,utc_start,utc_end',[
 ('America/Chicago','2026-03-08','2026-03-08T06:00:00+00:00','2026-03-09T05:00:00+00:00'),
 ('America/Chicago','2026-11-01','2026-11-01T05:00:00+00:00','2026-11-02T06:00:00+00:00'),
 ('Asia/Tokyo','2026-03-08','2026-03-07T15:00:00+00:00','2026-03-08T15:00:00+00:00')])
def test_all_day_boundaries_use_configured_zone(make_connector,zone,date_value,utc_start,utc_end):
    c=make_connector(timezone=zone)
    from datetime import date,timedelta
    start=date.fromisoformat(date_value);end=start+timedelta(days=1)
    cal=Calendar();e=Event();e.add('UID','all-day');e.add('DTSTART',start);e.add('DTEND',end);cal.add_component(e)
    a,b=window(str(start),str(end),c.config);rows=expand(cal,a,b,c.config)
    assert len(rows)==1
    from icloud_mcp.recurrence import bounds
    from zoneinfo import ZoneInfo
    s,t,all_day=bounds(rows[0],ZoneInfo(zone));assert all_day
    assert s.isoformat()==utc_start and t.isoformat()==utc_end
    assert expand(cal,b,b+timedelta(days=1),c.config)==[]


@pytest.mark.parametrize('start,code',[('2026-03-08T02:30:00','INVALID_LOCAL_TIME'),('2026-11-01T01:30:00','AMBIGUOUS_LOCAL_TIME')])
async def test_dst_gap_and_ambiguous_input_rejected(make_connector,start,code):
    c=make_connector();ref=await calendar_ref(c)
    r=await c.execute('get_events',dict(calendar_ref=ref,start=start,end='2026-11-02T00:00:00Z'))
    assert r['error']['code']==code


async def test_create_conditional_update_and_delete_series(make_connector):
    c=make_connector();ref=await calendar_ref(c)
    r=await c.execute('create_event',dict(operation_id='create',calendar_ref=ref,event={'summary':'Synthetic new','start':'2026-03-08','end':'2026-03-09','all_day':True}))
    assert r['ok'],r
    assert c.fake_dav.calls[-1][2]['If-None-Match']=='*'
    _,rows=await events(c)
    new=next(x for x in rows if x['uid']==r['result']['uid'])
    u=await c.execute('update_event',dict(operation_id='update',event_ref=new['event_ref'],expected_etag=new['etag'],scope='series',changes={'summary':'Synthetic updated'}));assert u['ok'],u
    _,rows=await events(c);new=next(x for x in rows if x['uid']==r['result']['uid'])
    d=await c.execute('delete_event',dict(operation_id='delete',event_ref=new['event_ref'],expected_etag=new['etag'],scope='series'));assert d['ok'],d
    assert new['resource_href'] not in c.fake_dav.resources


async def test_occurrence_update_preserves_series_properties(make_connector):
    c=make_connector();_,rows=await events(c);row=rows[2]
    r=await c.execute('update_event',dict(operation_id='update-occ',event_ref=row['event_ref'],expected_etag=row['etag'],scope='occurrence',changes={'summary':'Synthetic override'}))
    assert r['ok'],r
    parsed=Calendar.from_ical(c.fake_dav.resources[row['resource_href']][0])
    assert len(parsed.walk('VEVENT'))==3
    master=parsed.walk('VEVENT')[0]
    assert master['X-SYNTHETIC-PRESERVE']=='yes' and len(master.walk('VALARM'))==1 and 'RRULE' in master
    assert all('RRULE' not in e for e in parsed.walk('VEVENT') if 'RECURRENCE-ID' in e)
    _,updated=await events(c);assert len(updated)==4


async def test_occurrence_delete_adds_exdate_and_removes_override(make_connector):
    c=make_connector();_,rows=await events(c);row=rows[1]
    r=await c.execute('delete_event',dict(operation_id='delete-occ',event_ref=row['event_ref'],expected_etag=row['etag'],scope='occurrence'))
    assert r['ok'],r
    _,updated=await events(c);assert len(updated)==3
    assert row['resource_href'] in c.fake_dav.resources


async def test_stale_etag_and_precondition_conflict(make_connector):
    c=make_connector();ref=await event_ref(c)
    href=next(iter(c.fake_dav.resources));c.fake_dav.resources[href][1]='"new-etag"'
    assert (await c.execute('fetch_event',{'event_ref':ref}))['error']['code']=='STALE_REFERENCE'
    r=await c.execute('update_event',dict(operation_id='stale',event_ref=ref,expected_etag='"etag-1"',scope='series',changes={'summary':'Synthetic'}))
    assert r['error']['code']=='CONFLICT'
    c.fake_dav.resources[href][1]='"etag-1"';c.fake_dav.force_conflict=True
    r=await c.execute('delete_event',dict(operation_id='race',event_ref=ref,expected_etag='"etag-1"',scope='series'))
    assert r['error']['code']=='CONFLICT' and href in c.fake_dav.resources


@pytest.mark.parametrize('url',['http://caldav.icloud.com/','https://evil.example.invalid/a','https://caldav.icloud.com.evil.invalid/a',
 'https://user:password@caldav.icloud.com/a','https://caldav.icloud.com:444/a','https://caldav.icloud.com/a/../b','https://caldav.icloud.com/a/%2e%2e/b'])
def test_foreign_and_escaping_urls_rejected(url):
    with pytest.raises(ConnectorError):allowed_url(url)


@pytest.mark.parametrize('host',['caldav.icloud.com','p01-caldav.icloud.com','p123-caldav.icloud.com'])
def test_icloud_partition_hosts_allowed(host):
    url=f'https://{host}/123/calendars/example/'
    assert allowed_url(url)==url


async def test_event_reference_cannot_select_foreign_collection(make_connector):
    c=make_connector();ref=await event_ref(c);obj=c.ids.decode(ref,'event')
    forged=c.ids.issue('event',**{k:v for k,v in obj.items() if k not in ('kind','account','v') and k!='href'},href='https://p01.caldav.icloud.com/foreign/secret.ics')
    assert (await c.execute('fetch_event',{'event_ref':forged}))['error']['code']=='INVALID_RESOURCE'


async def test_ambiguous_calendar_write_not_replayed(make_connector):
    c=make_connector();ref=await event_ref(c);c.fake_dav.ambiguous=True
    args=dict(operation_id='ambiguous-cal',event_ref=ref,expected_etag='"etag-1"',scope='series',changes={'summary':'Synthetic'})
    assert (await c.execute('update_event',args))['error']['code']=='CALDAV_AMBIGUOUS'
    assert c.ledger.status('ambiguous-cal')['state']=='ambiguous'
    assert (await c.execute('update_event',args))['error']['code']=='OPERATION_NOT_REPLAYABLE'


async def test_floating_exception_update_and_delete_preserve_identity(make_connector):
    c=make_connector();href=next(iter(c.fake_dav.resources))
    c.fake_dav.resources[href][0]=c.fake_dav.resources[href][0].replace(b';TZID=America/Chicago',b'')
    _,rows=await events(c);assert len(rows)==4
    row=rows[1]
    result=await c.execute('update_event',dict(operation_id='floating-update',event_ref=row['event_ref'],expected_etag=row['etag'],scope='occurrence',changes={'summary':'Synthetic floating update'}))
    assert result['ok'],result
    assert len(Calendar.from_ical(c.fake_dav.resources[href][0]).walk('VEVENT'))==2
    _,rows=await events(c);row=rows[1]
    result=await c.execute('delete_event',dict(operation_id='floating-delete',event_ref=row['event_ref'],expected_etag=row['etag'],scope='occurrence'))
    assert result['ok'],result
    _,rows=await events(c);assert len(rows)==3


async def test_series_edit_preserves_existing_exception_override(make_connector):
    c=make_connector();_,rows=await events(c);row=rows[0]
    r=await c.execute('update_event',dict(operation_id='series-edit',event_ref=row['event_ref'],expected_etag=row['etag'],scope='series',changes={'summary':'Synthetic master change'}))
    assert r['ok'],r
    parsed=Calendar.from_ical(c.fake_dav.resources[row['resource_href']][0])
    assert parsed.walk('VEVENT')[1]['SUMMARY']=='Synthetic shifted occurrence'
    assert parsed.walk('VEVENT')[0]['SUMMARY']=='Synthetic master change'


async def test_rdate_exdate_and_cancelled_occurrence(make_connector):
    c=make_connector();href=next(iter(c.fake_dav.resources))
    parsed=Calendar.from_ical(c.fake_dav.resources[href][0]);master=parsed.walk('VEVENT')[0]
    from datetime import datetime
    from zoneinfo import ZoneInfo
    master.add('RDATE',datetime(2026,3,12,9,tzinfo=ZoneInfo('America/Chicago')))
    parsed.walk('VEVENT')[1].add('STATUS','CANCELLED')
    c.fake_dav.resources[href][0]=parsed.to_ical()
    _,rows=await events(c,end='2026-03-13');assert len(rows)==4
    assert any(x['start'].startswith('2026-03-12') for x in rows)
    assert not any(x['start'].startswith('2026-03-08') for x in rows)


async def test_range_thisandfuture_write_rejected_without_modification(make_connector):
    c=make_connector();href=next(iter(c.fake_dav.resources))
    parsed=Calendar.from_ical(c.fake_dav.resources[href][0]);parsed.walk('VEVENT')[1]['RECURRENCE-ID'].params['RANGE']='THISANDFUTURE'
    c.fake_dav.resources[href][0]=parsed.to_ical();before=c.fake_dav.resources[href][0]
    ref=await event_ref(c)
    r=await c.execute('delete_event',dict(operation_id='range-unsupported',event_ref=ref,expected_etag='"etag-1"',scope='series'))
    assert r['error']['code']=='UNSUPPORTED_RANGE' and c.fake_dav.resources[href][0]==before


async def test_high_frequency_expansion_is_explicitly_bounded(make_connector):
    c=make_connector();href=next(iter(c.fake_dav.resources))
    parsed=Calendar.from_ical(c.fake_dav.resources[href][0]);master=parsed.walk('VEVENT')[0]
    master['RRULE']={'FREQ':['SECONDLY']}
    # Construct valid vRecur via the public parser.
    from icalendar import vRecur
    master['RRULE']=vRecur.from_ical('FREQ=SECONDLY')
    c.fake_dav.resources[href][0]=parsed.to_ical()
    ref=await calendar_ref(c)
    r=await c.execute('get_events',dict(calendar_ref=ref,start='2026-03-07',end='2026-03-12'))
    assert r['error']['code']=='EXPANSION_LIMIT'


def test_nonexistent_recurrence_slot_is_ignored_without_consuming_count(make_connector):
    c=make_connector()
    cal=Calendar.from_ical('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:gap-example\nDTSTART;TZID=America/Chicago:20260307T023000\nDTEND;TZID=America/Chicago:20260307T033000\nRRULE:FREQ=DAILY;COUNT=3\nEND:VEVENT\nEND:VCALENDAR')
    a,b=window('2026-03-07','2026-03-11',c.config)
    rows=expand(cal,a,b,c.config)
    assert [e.decoded('DTSTART').day for e in rows]==[7,9,10]
    assert cal.walk('VEVENT')[0]['RRULE']['COUNT']==[3]  # Original remains unchanged.
    # Query after the gap still gets the final valid instance.
    a,b=window('2026-03-10','2026-03-11',c.config)
    assert len(expand(cal,a,b,c.config))==1
