#!/usr/bin/env python3
"""Cache ACM profiles through regular Safari and AppleScript on macOS.

Uses a dedicated Safari window and the shared ACM cache/parser. No Playwright,
WebDriver, JavaScript injection, or CSV writes. --limit-new 0 is browser-free.
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from cache_acm_fellow_profiles import (
    crawl_path, parse_crawl_date, atomic_write_json, build_report, load_json,
    load_rows, looks_blocked, parse_profile_html, unique_profiles,
    ensure_manifest, latest_attempt, record_attempt,
)

FETCH_SCRIPT = Path(__file__).with_name('acm_safari_fetch.applescript')
TRANSIENT = {'blocked', 'url_error', 'timeout'}
STATUSES = TRANSIENT | {'http_error', 'no_name', 'no_fellow_award', 'invalid_url', 'validation_error'}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--crawl-date', type=parse_crawl_date, required=True, help='Crawl start date (YYYY-MM-DD); keep the same date when resuming.')
    p.add_argument('--cache', type=Path, help='Override the dated JSON cache path.')
    p.add_argument('--report', type=Path, help='Override the dated JSON report path.')
    p.add_argument('--state', type=Path, help='Override the dated progress JSON path.')
    p.add_argument('--refresh', action='store_true', help='Refetch every selected URL; use a new crawl date for a resumable fresh run.')
    p.add_argument('--retry-status', action='append', choices=sorted(STATUSES), default=[])
    p.add_argument('--accept-profile', action='append', default=[], metavar='URL', help='Accept a saved name/year validation mismatch for this exact URL after manual review.')
    p.add_argument('--limit-new', type=int, help='Maximum distinct profiles to fetch; 0 rebuilds reports without Safari.')
    p.add_argument('--pilot-size', type=int, default=5, help='Validate name/year for the first N fetched profiles; 0 disables the pilot gate.')
    p.add_argument('--delay', type=float, default=6.0)
    p.add_argument('--delay-jitter', type=float, default=1.0, help='Random +/- seconds around --delay.')
    p.add_argument('--batch-size', type=int, default=25, help='Fetch attempts per batch, including retries.')
    p.add_argument('--batch-pause', type=float, default=75.0)
    p.add_argument('--batch-pause-jitter', type=float, default=15.0, help='Random +/- seconds around --batch-pause.')
    p.add_argument('--max-retries', type=int, default=2)
    p.add_argument('--backoff', type=float, default=120.0, help='Exponential retry backoff base in seconds.')
    p.add_argument('--backoff-jitter', type=float, default=15.0, help='Random extra seconds per retry.')
    p.add_argument('--timeout', type=float, default=30.0, help='Page load timeout in seconds.')
    args = p.parse_args()
    for name in ('pilot_size', 'delay', 'delay_jitter', 'batch_pause', 'batch_pause_jitter', 'max_retries', 'backoff', 'backoff_jitter'):
        if getattr(args, name) < 0:
            p.error(f'--{name.replace("_", "-")} must be nonnegative')
    if args.batch_size < 1 or args.timeout <= 0 or (args.limit_new is not None and args.limit_new < 0):
        p.error('batch size and timeout must be positive; limit-new must be nonnegative')
    args.cache = args.cache or crawl_path('cache', args.crawl_date)
    args.report = args.report or crawl_path('report', args.crawl_date)
    args.state = args.state or crawl_path('state', args.crawl_date)
    if len({path.resolve() for path in (args.data, args.cache, args.report, args.state)}) != 4:
        p.error('input, cache, report, and state paths must be distinct')
    return args


def timestamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def jittered(base, jitter):
    return max(0.0, base + random.uniform(-jitter, jitter)) if base > 0 else 0.0


def should_fetch(entry, refresh, retry_statuses):
    if refresh or not entry:
        return True
    status = latest_attempt(entry).get('status')
    return status in TRANSIENT | set(retry_statuses) or (status == 'ok' and not entry.get('html'))


def run_applescript(*args, timeout):
    return subprocess.run(['/usr/bin/osascript', *map(str, args)], capture_output=True,
                          text=True, check=True, timeout=timeout).stdout


def open_window():
    if sys.platform != 'darwin':
        raise RuntimeError('Live fetching requires macOS and Safari; --limit-new 0 works without them.')
    return int(run_applescript('-e', 'tell application "Safari"\nmake new document with properties {URL:"about:blank"}\nreturn id of front window\nend tell', timeout=30).strip())


def close_window(window_id):
    run_applescript('-e', f'tell application "Safari" to close window id {int(window_id)}', timeout=15)


def entry_from_html(url, html):
    entry = {'html': html, 'status_code': None, 'fetched_at': timestamp(),
             'fetch_method': 'safari-applescript', 'final_url': url}
    if looks_blocked(html) or 'too many requests' in html.lower():
        return {**entry, 'status': 'blocked'}
    if '404 - Your Page Could Not Be Found' in html:
        return {**entry, 'status': 'http_error', 'error': 'ACM 404 page detected in HTML; HTTP status unavailable.'}
    parsed = parse_profile_html(html)
    status = 'ok' if parsed.get('award_heading') else 'no_fellow_award'
    if not parsed.get('page_name'):
        status = 'no_name'
    return {**entry, **parsed, 'status': status}


def fetch_profile(window_id, url, timeout):
    parsed = urlparse(url)
    failure = {'html': '', 'status_code': None, 'fetched_at': timestamp(), 'fetch_method': 'safari-applescript'}
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return {**failure, 'status': 'invalid_url', 'error': 'Expected an HTTP(S) URL.'}
    try:
        output = run_applescript(FETCH_SCRIPT, window_id, url, timeout, timeout=timeout + 15)
        final_url, html = output.split('\n', 1)
        if final_url != url or '</html>' not in html.lower():
            raise ValueError('Loaded URL differs from the requested URL, or HTML is incomplete.')
        return entry_from_html(final_url, html)
    except subprocess.TimeoutExpired as error:
        return {**failure, 'status': 'timeout', 'error': str(error)}
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        status = 'timeout' if 'Timed out waiting' in message else 'url_error'
        return {**failure, 'status': status, 'error': message}


def main():
    args = parse_args()
    profiles = unique_profiles(load_rows(args.data))
    cache = load_json(args.cache, {})
    try:
        ensure_manifest(args)
        profile_urls = {p.url for p in profiles}
        for url in args.accept_profile:
            if url not in profile_urls or latest_attempt(cache.get(url, {})).get('status') != 'validation_error':
                raise ValueError('--accept-profile requires an input URL with a saved validation_error.')
        for url in args.accept_profile:
            accepted = dict(latest_attempt(cache[url]))
            accepted['status'] = 'ok'
            accepted['accepted_validation_error'] = accepted.pop('validation_error')
            accepted.pop('pilot_validation_failed', None)
            cache[url] = accepted
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    pending = [p for p in profiles if should_fetch(cache.get(p.url), args.refresh, args.retry_status)]
    if args.limit_new is not None:
        pending = pending[:args.limit_new]
    window_id = None
    fetched = attempts = batch_attempts = 0

    def save(state, detail=''):
        report = build_report(profiles, cache)
        atomic_write_json(args.cache, cache)
        atomic_write_json(args.report, report)
        atomic_write_json(args.state, {
            'state': state, 'detail': detail, 'updated_at': timestamp(), 'crawl_date': args.crawl_date,
            'browser_mode': 'regular Safari via AppleScript', 'safari_window_id': window_id,
            'total_profiles': len(profiles), 'fetched_this_run': fetched, 'attempts_this_run': attempts,
            'cached_profiles': report['cached_profiles'], 'status_counts': report['status_counts'],
            'review_candidate_count': report['review_candidate_count'],
        })
        print(f'{state}: {detail}', flush=True)

    try:
        retry_urls = {p.url for p in pending}
        unresolved = [p for p in profiles if (latest_attempt(cache.get(p.url, {})).get('status') == 'validation_error' or latest_attempt(cache.get(p.url, {})).get('pilot_validation_failed')) and p.url not in retry_urls]
        if unresolved:
            save('paused', f'Unresolved pilot validation: {unresolved[0].url}. Review, then retry its saved status or use --accept-profile URL for a name/year mismatch.')
            return 1
        if not pending:
            save('complete', 'No fetches requested; report rebuilt from cache.')
            return 0
        window_id = open_window()
        save('running', f'{len(pending)} profiles selected.')
        for profile in pending:
            previous_attempt = latest_attempt(cache.get(profile.url, {}))
            validate_profile = (fetched < args.pilot_size or previous_attempt.get('pilot_validation_failed')
                                or previous_attempt.get('status') == 'validation_error')
            for attempt in range(args.max_retries + 1):
                if batch_attempts >= args.batch_size:
                    pause = jittered(args.batch_pause, args.batch_pause_jitter)
                    save('cooldown', f'Batch pause {pause:.1f}s.')
                    time.sleep(pause)
                    batch_attempts = 0
                print(f'[{fetched + 1}/{len(pending)}] {profile.name}; attempt {attempt + 1}', flush=True)
                entry = fetch_profile(window_id, profile.url, args.timeout)
                if validate_profile and entry['status'] == 'ok':
                    check = build_report([profile], {profile.url: entry})['entries'][0]
                    if not check['name_match'] or (profile.year and not check['year_match']):
                        entry = {**entry, 'status': 'validation_error', 'validation_error': 'Pilot name/year mismatch.'}
                if validate_profile and entry['status'] != 'ok':
                    entry = {**entry, 'pilot_validation_failed': True}
                record_attempt(cache, profile.url, entry)
                attempts += 1
                batch_attempts += 1
                save('running', f'{profile.name}: {entry["status"]}')
                if entry['status'] not in TRANSIENT:
                    break
                fatal = any(token in entry.get('error', '') for token in ('Not authorized', '-1743', "Can't get window", '-1728'))
                if attempt == args.max_retries or fatal:
                    save('paused', f'{profile.name}: {entry["status"]}; {entry.get("error", "Persistent blocking.")}')
                    return 1
                pause = args.backoff * (2 ** attempt) + random.uniform(0, args.backoff_jitter)
                save('backoff', f'Retry in {pause:.1f}s.')
                time.sleep(pause)
            fetched += 1
            if validate_profile:
                check = build_report([profile], cache)['entries'][0]
                if entry['status'] != 'ok' or not check['name_match'] or (profile.year and not check['year_match']):
                    save('paused', f'Pilot validation needs review: {profile.name}.')
                    return 1
                if fetched == args.pilot_size:
                    print('Pilot passed; continuing.', flush=True)
            if fetched < len(pending):
                time.sleep(jittered(args.delay, args.delay_jitter))
        save('complete', f'{fetched} profiles fetched; review report for differences and failures.')
        return 0
    except KeyboardInterrupt:
        save('paused', 'Interrupted; resume with the same paths without --refresh.')
        return 130
    except Exception as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        save('failed', message)
        return 1
    finally:
        if window_id is not None:
            try:
                close_window(window_id)
            except Exception as error:
                print(f'Could not close crawler window {window_id}: {error}', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
