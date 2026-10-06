"""TTY-only local sample selection after discovery; never stores message contents."""
from datetime import date, timedelta
import getpass
import json
from pathlib import Path
import sys
import warnings
from live_validation import read_plan
from setup_credentials import create_private


def main():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('Use a private local terminal for sample selection.', file=sys.stderr)
        return 2
    warnings.simplefilter('error', getpass.GetPassWarning)
    root = Path(__file__).resolve().parents[1]
    # Contains folder/calendar labels for the operator only; no credentials or contents.
    try:
        with (root/'.state/live-discovery.json').open() as file:
            inventory = json.load(file)
    except Exception:
        print('Run approved discovery first to create the private inventory.', file=sys.stderr)
        return 1
    print('Private local resource labels (do not paste this inventory into chat):', file=sys.stderr)
    for row in inventory['collections']:
        print(f"{row['collection']}: {row['untrusted_name']!r}; components={row['supported_components']}", file=sys.stderr)
    folder = input('Exact canonical mail folder (see .state/live-discovery.json): ').strip()
    if folder not in {x['folder'] for x in inventory['folders']}:
        print('Folder is not in the discovery inventory.', file=sys.stderr)
        return 1
    ascii_query = getpass.getpass('Known matching ASCII keyword in that folder (hidden): ')
    unicode_query = getpass.getpass('Known matching non-ASCII keyword in that folder (hidden): ')
    if not ascii_query or not ascii_query.isascii() or not unicode_query or unicode_query.isascii():
        print('Select both a nonempty ASCII keyword and a keyword containing a non-ASCII character.', file=sys.stderr)
        return 1
    def select(prompt):
        labels = input(prompt).split()
        mapping = {x['collection']: x['calendar_id'] for x in inventory['collections']}
        if not set(labels) <= mapping.keys():
            raise ValueError('Unknown collection label')
        return [mapping[x] for x in labels]
    try:
        calendars = select('Event collections to test, e.g. C1 C3 (maximum 10): ')
        visible = select('Collections visible/enabled in iOS, e.g. C1 C3 C4 (Enter if unknown): ')
        start = input(f'Window start date/ISO timestamp [{date.today().isoformat()}]: ').strip() or date.today().isoformat()
        end = input(f'Exclusive end [{(date.today()+timedelta(days=7)).isoformat()}]: ').strip() or (date.today()+timedelta(days=7)).isoformat()
        windows = []
        for label in ('known recurrence/exception or all-day sample', 'DST transition sample'):
            a = input(f'Optional {label} start (Enter to skip): ').strip()
            if a:
                windows.append({'start': a, 'end': input('Exclusive end for that window: ').strip()})
        plan = dict(folder=folder, ascii_query=ascii_query, unicode_query=unicode_query,
                    calendar_ids=calendars, start=start, end=end, additional_windows=windows)
        if visible:
            plan['ios_visible_calendar_ids'] = visible
        path = root/'.config/live-plan.json'
        create_private(path, json.dumps(plan, ensure_ascii=False, indent=2)+'\n')
        read_plan(path)
    except Exception:
        print('PLAN_FAILED: check selections and whether a plan already exists; no values logged.', file=sys.stderr)
        return 1
    print('Prepared .config/live-plan.json (0600); no account requests made.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
