#!/usr/bin/env python3
"""Compare a CSV with captured ACM HTML without fetching or modifying crawl files."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from cache_acm_fellow_profiles import (
    compatible_name, crawl_path, latest_attempt, load_json, load_rows,
    looks_blocked, manifest_path, parse_crawl_date, parse_profile_html, row_value,
    AWARD_PREFIXES,
)


def compare_rows(rows, cache, award='fellows'):
    entries = []
    url_rows = {}
    for index, row in enumerate(rows, start=1):
        url = row_value(row, 'ACM Fellow Profile', 'acm_fellow_profile')
        result = {'index': index, 'name': row.get('name', ''), 'url': url}
        if not url:
            entries.append({**result, 'status': 'blank_url'})
            continue
        url_rows.setdefault(url, []).append(index)
        cached = cache.get(url)
        if not cached:
            entries.append({**result, 'status': 'missing'})
            continue
        body = cached.get('html') or ''
        parsed = parse_profile_html(body, award)
        status = 'ok'
        if not body:
            status = 'missing_html'
        elif looks_blocked(body) or 'too many requests' in body.lower():
            status = 'blocked'
        elif '404 - Your Page Could Not Be Found' in body:
            status = 'http_error'
        elif not parsed['page_name']:
            status = 'no_name'
        elif not parsed['award_heading']:
            status = 'no_turing_award' if award == 'turing' else 'no_fellow_award'
        differences = {}
        for column, key in (('name', 'page_name'), ('year', 'year'), ('location', 'location'), ('citation', 'citation')):
            expected = row.get('name', '') if column == 'name' else row_value(row, column.title(), column)
            if expected != parsed[key]:
                differences[column] = {'csv': expected, 'page': parsed[key]}
        entries.append({
            **result, 'status': status, 'cache_status': cached.get('status'),
            'last_attempt_status': latest_attempt(cached).get('status'),
            'fetched_at': cached.get('fetched_at'), 'parsed': parsed,
            'name_match': compatible_name(result['name'], parsed['page_name']) if status == 'ok' else None,
            'differences': differences,
            'accepted_validation_error': cached.get('accepted_validation_error'),
        })
    return {
        'input_rows': len(rows), 'unique_profile_urls': len(url_rows),
        'status_counts': dict(Counter(e['status'] for e in entries)),
        'difference_counts': dict(Counter(field for e in entries for field in e.get('differences', {}))),
        'name_mismatch_count': sum(e.get('name_match') is False for e in entries),
        'duplicate_urls': {url: indexes for url, indexes in url_rows.items() if len(indexes) > 1},
        'unreferenced_cache_urls': sorted(set(cache) - set(url_rows)),
        'entries': entries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--award', choices=sorted(AWARD_PREFIXES), default='fellows')
    parser.add_argument('--crawl-date', type=parse_crawl_date, required=True)
    parser.add_argument('--cache', type=Path, help='Override the dated cache path.')
    parser.add_argument('--output', type=Path, help='Write JSON to a new file; existing files are never overwritten. Default: stdout.')
    args = parser.parse_args()
    cache_path = args.cache or crawl_path('cache', args.crawl_date, args.award)
    try:
        if not cache_path.is_file():
            raise ValueError(f'Cache does not exist: {cache_path}')
        manifest_file = manifest_path(cache_path, args.crawl_date, args.award)
        manifest = load_json(manifest_file, None)
        if manifest and (manifest.get('crawl_date') != args.crawl_date
                         or manifest.get('artifacts', {}).get('cache') != str(cache_path.resolve())):
            raise ValueError('Crawl manifest does not match the selected date or cache path.')
        protected = {args.data.resolve(), cache_path.resolve(), manifest_file.resolve()}
        protected.update(crawl_path(kind, args.crawl_date, args.award).resolve() for kind in ('cache', 'report', 'state'))
        if manifest:
            protected.update(Path(p).resolve() for p in manifest['artifacts'].values())
            protected.add(Path(manifest['input']['path']).resolve())
        if args.output and args.output.resolve() in protected:
            raise ValueError('Comparison output must not overwrite input or crawl artifacts.')
        report = compare_rows(load_rows(args.data), load_json(cache_path, {}), args.award)
        report.update({
            'crawl_date': args.crawl_date, 'award': args.award, 'cache': str(cache_path.resolve()),
            'input': str(args.data.resolve()),
            'input_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
            'crawl_input_sha256': manifest['input']['sha256'] if manifest else None,
            'crawl_award': manifest.get('award', 'fellows') if manifest else None,
        })
        output = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(output)
        else:
            print(output, end='')
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
