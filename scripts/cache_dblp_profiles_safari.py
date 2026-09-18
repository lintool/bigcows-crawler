#!/usr/bin/env python
"""Capture DBLP profiles through regular Safari into a resumable run directory."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

import cache_dblp_profiles as dblp
from cache_acm_fellow_profiles_safari import (
    close_window, jittered, run_applescript, timestamp,
)

FETCH_SCRIPT = Path(__file__).with_name('dblp_safari_fetch.applescript')


def open_window():
    # Safari can expose the previous front-window ID briefly after make-document.
    script = '''tell application "Safari"
set previousIds to id of every window
make new document with properties {URL:"about:blank"}
repeat 100 times
    repeat with candidate in every window
        if id of candidate is not in previousIds then return id of candidate
    end repeat
    delay 0.1
end repeat
error "New dedicated Safari window did not appear"
end tell'''
    return int(run_applescript('-e', script, timeout=30).strip())


def profile_key(url):
    parsed = urlparse(url)
    if (parsed.scheme not in {'http', 'https'} or parsed.hostname != 'dblp.org'
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
            or not parsed.path.startswith('/pid/')):
        return None
    return parsed.path.removesuffix('.html').rstrip('/')


def classify(requested, final_url, html):
    entry = {'html': html, 'status_code': None, 'fetched_at': timestamp(),
             'fetch_method': 'safari-applescript', 'final_url': final_url,
             **dblp.parse_profile_html(html)}
    if dblp.looks_blocked(html):
        entry['status'] = 'blocked'
    elif '</html>' not in html.lower():
        entry.update(status='url_error', error='Incomplete HTML.')
    elif not profile_key(requested):
        entry.update(status='invalid_url', error='Expected a dblp.org/pid/ profile URL.')
    elif profile_key(final_url) != profile_key(requested):
        entry.update(status='redirect_review', requested_url=requested,
                     review_reason='Redirected to a different URL; retained for later identity review.')
    elif 'itemprop="name"' not in html or not entry['title']:
        entry.update(status='no_profile', error='No DBLP author name markup; review this page.')
    else:
        entry['status'] = 'ok'
    return entry


def fetch_profile(window_id, url, timeout):
    failure = {'html': '', 'title': '', 'status_code': None,
               'fetched_at': timestamp(), 'fetch_method': 'safari-applescript'}
    if not profile_key(url):
        return {**failure, 'status': 'invalid_url', 'error': 'Expected a dblp.org/pid/ profile URL.'}
    try:
        output = run_applescript(FETCH_SCRIPT, window_id, url, timeout, timeout=timeout + 20)
        final_url, html = output.split('\n', 1)
        return classify(url, final_url, html)
    except subprocess.TimeoutExpired as error:
        return {**failure, 'status': 'timeout', 'error': str(error)}
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        message = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        return {**failure, 'status': 'url_error', 'error': message}


def store_capture(run, url, entry):
    entry = dict(entry)
    html = entry.pop('html')
    if html:
        relative = Path('captures') / f'{hashlib.sha256(url.encode()).hexdigest()}-{time.time_ns()}.html'
        (run / relative).write_text(html, encoding='utf-8')
        entry.update(html_path=str(relative), html_sha256=hashlib.sha256(html.encode()).hexdigest(),
                     html_bytes=len(html.encode()))
    with (run / 'attempts.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(url=url, **entry), ensure_ascii=False) + '\n')
    return entry


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--limit-new', type=int)
    parser.add_argument('--pilot-size', type=int, default=5)
    parser.add_argument('--retry-status', action='append', default=[])
    parser.add_argument('--delay', type=float, default=6)
    parser.add_argument('--delay-jitter', type=float, default=1)
    parser.add_argument('--batch-size', type=int, default=25)
    parser.add_argument('--batch-pause', type=float, default=75)
    parser.add_argument('--batch-pause-jitter', type=float, default=15)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    if (args.batch_size < 1 or args.timeout <= 0 or args.pilot_size < 0
            or (args.limit_new is not None and args.limit_new < 0)
            or min(args.delay, args.delay_jitter, args.batch_pause, args.batch_pause_jitter) < 0):
        parser.error('Invalid negative delay/limit, or nonpositive batch size/timeout.')
    return args


def crawl(args):
    run = args.run_dir
    data = args.data.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    manifest_path = run / 'manifest.json'
    manifest = dblp.load_json(manifest_path, {})
    if manifest and manifest['input_sha256'] != digest:
        raise ValueError('Input changed; resume with the original snapshot or use a new run directory.')
    if not manifest:
        if (run / 'cache.json').exists() or (run / 'input.csv').exists():
            raise ValueError('Unregistered artifacts exist; use a new run directory.')
        (run / 'input.csv').write_bytes(data)
        dblp.atomic_write_json(manifest_path, {
            'created_at': timestamp(), 'input_sha256': digest, 'source_input': str(args.data.resolve()),
            'transport': 'safari-applescript', 'cache_format': 'dblp-safari-html-files-v1',
            'pacing': {k: getattr(args, k) for k in ('delay', 'delay_jitter', 'batch_size', 'batch_pause', 'batch_pause_jitter')},
        })
    if hashlib.sha256((run / 'input.csv').read_bytes()).hexdigest() != digest:
        raise ValueError('Retained input snapshot changed.')
    (run / 'captures').mkdir(exist_ok=True)
    profiles = dblp.unique_profiles(dblp.load_rows(run / 'input.csv'))
    cache = dblp.load_json(run / 'cache.json', {})
    pending = [p for p in profiles if p.url not in cache or cache[p.url]['status'] in args.retry_status]
    if args.limit_new is not None:
        pending = pending[:args.limit_new]
    previous = dblp.load_json(run / 'state.json', {})
    batch_attempts = previous.get('batch_attempts', 0)
    cooldown_until = previous.get('cooldown_until', 0)
    next_request_at = previous.get('next_request_at', 0)
    window = None
    fetched = 0

    def save(status, detail=''):
        report = dblp.build_report(profiles, cache)
        dblp.atomic_write_json(run / 'cache.json', cache)
        dblp.atomic_write_json(run / 'report.json', report)
        dblp.atomic_write_json(run / 'state.json', {
            'status': status, 'detail': detail, 'updated_at': timestamp(),
            'safari_window_id': window, 'total_profiles': len(profiles),
            'fetched_this_run': fetched, 'cached_profiles': report['cached_profiles'],
            'status_counts': report['status_counts'], 'batch_attempts': batch_attempts,
            'cooldown_until': cooldown_until, 'next_request_at': next_request_at,
        })
        print(f'{status}: {detail}', flush=True)

    try:
        retry_urls = {p.url for p in pending}
        unresolved = [p for p in profiles if (cache.get(p.url, {}).get('status') in
                      {'blocked', 'url_error', 'timeout', 'validation_error'}
                      or cache.get(p.url, {}).get('pilot_validation_failed')) and p.url not in retry_urls]
        if unresolved:
            save('paused', f'Review saved failure for {unresolved[0].url}; explicit --retry-status required.')
            return 1
        if not pending:
            save('invocation_finished', 'No new fetches requested; inspect coverage in report.json.')
            return 0
        window = open_window()
        save('running', f'{len(pending)} profiles selected.')
        for profile in pending:
            if batch_attempts >= args.batch_size:
                if not cooldown_until:
                    cooldown_until = time.time() + jittered(args.batch_pause, args.batch_pause_jitter)
                save('cooldown', f'Batch pause until {cooldown_until:.0f}.')
                time.sleep(max(0, cooldown_until - time.time()))
                batch_attempts = 0
                cooldown_until = 0
            time.sleep(max(0, next_request_at - time.time()))
            print(f'[{fetched + 1}/{len(pending)}] {profile.name}: {profile.url}', flush=True)
            entry = fetch_profile(window, profile.url, args.timeout)
            if fetched < args.pilot_size and entry['status'] == 'ok' and not dblp.compatible_name(profile.name, entry['title']):
                entry.update(status='validation_error', error='Pilot name mismatch; review identity.')
            if fetched < args.pilot_size and entry['status'] not in {'ok', 'redirect_review'}:
                entry['pilot_validation_failed'] = True
            cache[profile.url] = store_capture(run, profile.url, entry)
            fetched += 1
            batch_attempts += 1
            next_request_at = time.time() + jittered(args.delay, args.delay_jitter)
            if batch_attempts >= args.batch_size:
                cooldown_until = time.time() + jittered(args.batch_pause, args.batch_pause_jitter)
            save('running', f'{profile.name}: {entry["status"]}')
            if entry['status'] in {'blocked', 'url_error', 'timeout', 'validation_error'} or (fetched <= args.pilot_size and entry['status'] not in {'ok', 'redirect_review'}):
                save('paused', f'{profile.name}: {entry["status"]}; inspect capture before retrying.')
                return 1
        save('invocation_finished', f'{fetched} profiles fetched; inspect report for missing/error/review entries.')
        return 0
    except KeyboardInterrupt:
        save('paused', 'Interrupted; resume with the original input and run directory.')
        return 130
    except Exception as error:
        save('failed', str(error))
        raise
    finally:
        if window is not None:
            try:
                close_window(window)
            except (subprocess.SubprocessError, OSError) as error:
                print(f'Window cleanup warning: {error}', flush=True)
            finally:
                state = dblp.load_json(run / 'state.json', {})
                state['safari_window_id'] = None
                dblp.atomic_write_json(run / 'state.json', state)


def main():
    args = parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return crawl(args)


if __name__ == '__main__':
    raise SystemExit(main())
