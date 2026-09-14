#!/usr/bin/env python
"""Cache ACM Fellow profile pages and report parsed profile fields.

For the recommended macOS transport, run cache_acm_fellow_profiles_safari.py.
This module retains the shared parser/cache helpers and the HTTP alternative.

The script is intentionally conservative:

- cached URLs, including cached HTML pages, are never fetched again unless --refresh is passed
- each uncached request waits --delay seconds before the next one
- every --batch-size uncached requests, the script pauses for --batch-pause seconds plus/minus --batch-pause-jitter
- cache and report files are written after every request so runs can be resumed

The script does not modify the app data files. It only writes validation output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


CRAWLER_ROOT = Path(__file__).resolve().parents[1]
AWARD_PREFIXES = {"fellows": "acm-fellow-profile", "turing": "acm-turing-profile"}
AWARD_HEADINGS = {"fellows": "ACM Fellows", "turing": "ACM A. M. Turing Award"}


def parse_crawl_date(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("crawl date must be a valid YYYY-MM-DD date") from None
    return value


def crawl_path(kind: str, crawl_date: str, award: str = "fellows") -> Path:
    return CRAWLER_ROOT / ".cache" / f"{AWARD_PREFIXES[award]}-{kind}-{crawl_date}.json"


def manifest_path(cache: Path, crawl_date: str, award: str = "fellows") -> Path:
    # Derive identity from the cache, never from the requested date/award.
    cache = cache.resolve()
    for prefix in AWARD_PREFIXES.values():
        match = re.fullmatch(re.escape(prefix) + r"-cache-(\d{4}-\d{2}-\d{2})\.json", cache.name)
        if match:
            return cache.with_name(f"{prefix}-manifest-{match[1]}.json")
    return cache.with_suffix(".manifest.json")


def validate_artifact_paths(args, manifest_file: Path, artifacts: dict[str, str]) -> None:
    """Reject collisions with dated artifacts and locally registered custom runs."""
    award = getattr(args, "award", "fellows")
    outputs = {**artifacts, "manifest": str(manifest_file.resolve())}
    for role, value in outputs.items():
        for owner, prefix in AWARD_PREFIXES.items():
            match = re.fullmatch(re.escape(prefix) + r"-(cache|report|state|manifest|input|log)-(\d{4}-\d{2}-\d{2})\.(json|csv|txt)", Path(value).name)
            if match and (owner != award or match[1] != role or match[2] != args.crawl_date):
                raise ValueError("Output path belongs to another award, crawl date, or artifact role.")
    # Custom manifests can live beside any selected output. Default artifacts
    # (including nested application directories) all live under the shared cache.
    candidates = set((CRAWLER_ROOT / ".cache").rglob("*manifest*.json"))
    for parent in {Path(p).parent for p in outputs.values()}:
        candidates.update(parent.glob("*manifest*.json"))
    for candidate in candidates:
        if candidate.resolve() == manifest_file.resolve():
            continue
        registered = load_json(candidate, {})
        if "artifacts" not in registered or "input" not in registered:
            continue
        protected = {candidate.resolve(), Path(registered["input"]["path"]).resolve()}
        protected.update(Path(p).resolve() for p in registered["artifacts"].values())
        if protected.intersection(Path(p) for p in outputs.values()):
            raise ValueError(f"Output path is already registered to another crawl: {candidate}")


def ensure_manifest(args) -> dict[str, Any]:
    """Bind a crawl to an input snapshot; comparisons may use a different input."""
    award = getattr(args, "award", "fellows")
    path = manifest_path(args.cache, args.crawl_date, award)
    artifacts = {key: str(getattr(args, key).resolve()) for key in ("cache", "report", "state") if hasattr(args, key)}
    if path.resolve() in {args.data.resolve(), *(Path(p) for p in artifacts.values())}:
        raise ValueError("manifest, input, and output paths must be distinct")
    validate_artifact_paths(args, path, artifacts)
    digest = hashlib.sha256(args.data.read_bytes()).hexdigest()
    if path.exists():
        manifest = load_json(path, {})
        if (manifest.get("award", "fellows") != award
                or manifest.get("crawl_date") != args.crawl_date
                or manifest.get("input", {}).get("sha256") != digest
                or manifest.get("artifacts", {}).get("cache") != artifacts["cache"]):
            raise ValueError("Crawl manifest does not match the award, date, input checksum, or cache path. Resume with the original input snapshot, use a new crawl, or use compare_acm_fellow_profiles.py for another input.")
        if any(manifest["artifacts"].get(key) != value for key, value in artifacts.items()):
            raise ValueError("Resume with the registered artifact paths; use a separate crawl for different outputs.")
        if Path(manifest["input"]["path"]).resolve() in {Path(p) for p in artifacts.values()}:
            raise ValueError("Crawl outputs must not overwrite the registered input snapshot.")
        return manifest
    manifest = {
        "schema_version": 1, "crawl_date": args.crawl_date, "award": award,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": {"path": str(args.data.resolve()), "sha256": digest},
        "artifacts": artifacts,
    }
    if args.cache.exists():
        manifest["initial_cache_sha256"] = hashlib.sha256(args.cache.read_bytes()).hexdigest()
    atomic_write_json(path, manifest)
    return manifest


def latest_attempt(entry: dict[str, Any]) -> dict[str, Any]:
    return entry.get("last_attempt") or entry


def record_attempt(cache: dict[str, Any], url: str, entry: dict[str, Any]) -> None:
    previous = cache.get(url, {})
    if previous.get("status") == "ok" and previous.get("html") and entry.get("status") != "ok":
        cache[url] = {**previous, "last_attempt": entry}
    else:
        cache[url] = entry

SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
PARTICLES = {"al", "bin", "da", "de", "del", "den", "der", "di", "du", "la", "le", "van", "von"}


@dataclass(frozen=True)
class AcmProfile:
    index: int
    name: str
    url: str
    year: str | None = None
    location: str | None = None
    citation: str | None = None


class AcmProfileParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.h1_parts: list[str] = []
        self.title_parts: list[str] = []
        self.sections: list[dict[str, str]] = []
        self._in_title = False
        self._h1_depth: int | None = None
        self._section_depth: int | None = None
        self._current_section: dict[str, list[str]] | None = None
        self._current_field: str | None = None
        self._field_depth: int | None = None
        self._citation_link: list[str] | None = None
        self._citation_link_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID_TAGS:
            if tag in {"br", "hr", "wbr"}:
                self.handle_data(" ")
            return
        attr_dict = {key: value or "" for key, value in attrs}
        self.stack.append((tag, attr_dict))
        if tag == "a" and self._current_field == "citation":
            self._citation_link = []
            self._citation_link_depth = len(self.stack)

        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._h1_depth = len(self.stack)
        elif tag == "section" and "awards-winners__citation" in attr_dict.get("class", ""):
            self._section_depth = len(self.stack)
            self._current_section = {"heading": [], "location_year": [], "citation": []}
        elif self._current_section is not None and tag in {"h2", "h3", "p"}:
            classes = attr_dict.get("class", "")
            if tag == "h2":
                self._current_field = "heading"
                self._field_depth = len(self.stack)
            elif tag == "h3" and "awards-winners__location" in classes:
                self._current_field = "location_year"
                self._field_depth = len(self.stack)
            elif tag == "p" and "awards-winners__citation-short" in classes:
                self._current_field = "citation"
                self._field_depth = len(self.stack)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID_TAGS:
            return
        # Ignore stray closing tags; unwind to the matching open element.
        position = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if position is None:
            return
        del self.stack[position + 1:]
        if self._citation_link_depth is not None and len(self.stack) <= self._citation_link_depth:
            label = clean_text(" ".join(self._citation_link or []))
            if label.casefold() != "press release" and self._current_section is not None:
                self._current_section["citation"].extend(self._citation_link or [])
            self._citation_link = None
            self._citation_link_depth = None
        if tag == "title":
            self._in_title = False

        if self._h1_depth is not None and len(self.stack) == self._h1_depth and tag == "h1":
            self._h1_depth = None

        if self._field_depth is not None and len(self.stack) == self._field_depth and self.stack[-1][0] == tag:
            self._current_field = None
            self._field_depth = None

        if self._section_depth is not None and len(self.stack) == self._section_depth and tag == "section":
            if self._current_section is not None:
                self.sections.append({key: clean_text(" ".join(value)) for key, value in self._current_section.items()})
            self._section_depth = None
            self._current_section = None
            self._current_field = None
            self._field_depth = None

        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._h1_depth is not None:
            self.h1_parts.append(data)
        if self._current_section is not None and self._current_field is not None:
            if self._citation_link is not None:
                self._citation_link.append(data)
            else:
                self._current_section[self._current_field].append(data)

    def parsed(self, award: str = "fellows") -> dict[str, str]:
        section = next(
            (item for item in self.sections if normalize_space(item.get("heading", "")).casefold() == AWARD_HEADINGS[award].casefold()),
            {},
        )
        location, year = split_location_year(section.get("location_year", ""))
        return {
            "title": clean_title(" ".join(self.title_parts)),
            "page_name": clean_text(" ".join(self.h1_parts)),
            "award_heading": section.get("heading", ""),
            "location": location,
            "year": year,
            "citation": section.get("citation", ""),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Input CSV containing name and acm_fellow_profile.")
    parser.add_argument("--crawl-date", type=parse_crawl_date, required=True, help="Crawl start date (YYYY-MM-DD); keep the same date when resuming.")
    parser.add_argument("--cache", type=Path, help="Override the dated JSON cache path.")
    parser.add_argument("--report", type=Path, help="Override the dated JSON report path.")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between uncached requests.")
    parser.add_argument("--batch-size", type=int, default=25, help="Uncached requests per batch.")
    parser.add_argument("--batch-pause", type=float, default=75.0, help="Seconds to pause after each batch.")
    parser.add_argument("--batch-pause-jitter", type=float, default=15.0, help="Random +/- seconds around --batch-pause. Sleep is clamped at zero.")
    parser.add_argument("--limit-new", type=int, default=None, help="Optional cap on uncached requests this run.")
    parser.add_argument("--refresh", action="store_true", help="Refetch URLs even when cached.")
    args = parser.parse_args()
    args.cache = args.cache or crawl_path("cache", args.crawl_date)
    args.report = args.report or crawl_path("report", args.crawl_date)
    if len({path.resolve() for path in (args.data, args.cache, args.report)}) != 3:
        parser.error("input, cache, and report paths must be distinct")
    return args


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(data_path: Path) -> list[dict[str, str]]:
    with data_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        if "name" not in fields or not fields.intersection({"acm_fellow_profile", "ACM Fellow Profile"}):
            raise ValueError("Input CSV requires name and acm_fellow_profile columns.")
        return list(reader)


def row_name(row: dict[str, str]) -> str:
    return str(row.get("name") or "").strip()


def row_value(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""


def optional_row_value(row: dict[str, str], *keys: str) -> str | None:
    """An absent column is unrequested; an explicit blank remains comparable."""
    return row_value(row, *keys) if any(key in row for key in keys) else None


def unique_profiles(rows: list[dict[str, str]]) -> list[AcmProfile]:
    seen: set[str] = set()
    profiles: list[AcmProfile] = []
    for row_number, row in enumerate(rows, start=1):
        url = row_value(row, "ACM Fellow Profile", "acm_fellow_profile")
        if not url or url in seen:
            continue
        seen.add(url)
        profiles.append(
            AcmProfile(
                index=row_number,
                name=row_name(row),
                url=url,
                year=optional_row_value(row, "Year", "year"),
                location=optional_row_value(row, "Location", "location"),
                citation=optional_row_value(row, "Citation", "citation"),
            )
        )
    return profiles


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def clean_text(value: str) -> str:
    return normalize_space(value)


def clean_person_name(value: str) -> str:
    name = normalize_space(value)
    name = re.sub(
        r"^(?:prof\.dr\.ir\.|prof\.\s*dr\.-ing\.?|prof\.\s*dr\.?|professor|prof\.?|dr\.?|mr\.?|ms\.?|mrs\.?)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"^(?:dame|sir)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(?:ph\.?\s*d\.?|phd|dphil|ccp)\.?$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\d{4,}$", "", name)
    return normalize_space(name)


def clean_title(value: str) -> str:
    title = normalize_space(value)
    return re.sub(r"\s*-\s*ACM Award Winner\s*$", "", title).strip()


def split_location_year(value: str) -> tuple[str, str]:
    text = clean_text(value)
    if " - " not in text:
        return "", ""
    location, year = text.rsplit(" - ", 1)
    return location.strip(), year.strip()


def normalize_tokens(value: str) -> list[str]:
    text = clean_person_name(value).casefold().translate(str.maketrans({"ø": "o", "ł": "l", "đ": "d", "æ": "ae", "œ": "oe"}))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s.-]|_", " ", text)
    tokens = []
    for token in re.split(r"\s+", text):
        token = token.strip(".-")
        if token and token not in SUFFIXES:
            tokens.append(token)
    return tokens


def last_name(tokens: list[str]) -> str:
    useful = [token for token in tokens if len(token) > 1 and token not in PARTICLES]
    if useful:
        return useful[-1]
    return tokens[-1] if tokens else ""


def compatible_name(expected: str, observed: str) -> bool:
    expected_tokens = normalize_tokens(expected)
    observed_tokens = normalize_tokens(observed)
    if not expected_tokens or not observed_tokens:
        return False

    if "".join(expected_tokens) == "".join(observed_tokens):
        return True
    if sorted(expected_tokens) == sorted(observed_tokens):
        return True
    if last_name(expected_tokens) == last_name(observed_tokens):
        expected_first = expected_tokens[0]
        observed_first = observed_tokens[0]
        return (
            expected_first == observed_first
            or ((len(expected_first) == 1 or len(observed_first) == 1)
                and expected_first[:1] == observed_first[:1])
        )
    return False


def decode_body(body: bytes, headers: Any) -> str:
    charset = headers.get_content_charset() if headers else None
    return body.decode(charset or "utf-8", errors="replace")


def looks_blocked(body: str) -> bool:
    text = body.lower()
    markers = [
        "sorry, you have been blocked",
        "cf-browser-verification",
        "cf-chl-",
        "cloudflare ray id",
        "enable_cookies",
        "our systems have detected unusual traffic",
        "too many requests",
    ]
    if any(marker in text for marker in markers):
        return True
    if "cloudflareapps" in text and "awards-winners__citation" not in text:
        # The generic Cloudflare integration is also present on legitimate
        # pages. Recognize the legacy recipient layout before rejecting it.
        from acm_turing_legacy import parse_legacy_turing
        return parse_legacy_turing(body) is None
    return False


def parse_profile_html(body: str, award: str = "fellows") -> dict[str, str]:
    parser = AcmProfileParser()
    parser.feed(body)
    parsed = parser.parsed(award)
    if award == "turing" and not parsed["award_heading"]:
        from acm_turing_legacy import parse_legacy_turing
        legacy = parse_legacy_turing(body)
        if legacy:
            parsed.update(legacy)
    parsed["page_name"] = clean_person_name(parsed.get("page_name", ""))
    parsed["title"] = clean_person_name(parsed.get("title", ""))
    return parsed


def classify_profile_html(body: str, award: str = "fellows") -> dict[str, str]:
    """Classify captured HTML identically during fetching and later audits."""
    parsed = parse_profile_html(body, award)
    if not body:
        status = "missing_html"
    elif looks_blocked(body):
        status = "blocked"
    elif "404 - your page could not be found" in body.lower():
        status = "http_error"
    elif not parsed["page_name"]:
        status = "no_name"
    elif not parsed["award_heading"]:
        status = "no_turing_award" if award == "turing" else "no_fellow_award"
    else:
        status = "ok"
    return {**parsed, "status": status}


def fetch_profile(url: str) -> dict[str, Any]:
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return {
            "status": "invalid_url",
            "status_code": None,
            "html": "",
            "error": f"Not an HTTP URL: {url}",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = decode_body(response.read(), response.headers)
            status_code = response.status
    except urllib.error.HTTPError as error:
        body = decode_body(error.read(), error.headers)
        return {
            "status": "blocked" if looks_blocked(body) else "http_error",
            "status_code": error.code,
            "html": body,
            "fetched_at": fetched_at,
        }
    except urllib.error.URLError as error:
        return {"status": "url_error", "error": str(error.reason), "html": "", "fetched_at": fetched_at}
    except TimeoutError:
        return {"status": "timeout", "html": "", "fetched_at": fetched_at}

    return {"status_code": status_code, "html": body, "fetched_at": fetched_at, **classify_profile_html(body)}


def build_report(profiles: list[AcmProfile], cache: dict[str, Any]) -> dict[str, Any]:
    entries = []
    status_counts: dict[str, int] = {}
    for profile in profiles:
        cached = cache.get(profile.url)
        if not cached:
            entries.append(
                {
                    "index": profile.index,
                    "name": profile.name,
                    "url": profile.url,
                    "status": "missing",
                    "page_name": "",
                    "name_match": None,
                    "year_match": None,
                    "location_match": None,
                    "citation_match": None,
                }
            )
            status_counts["missing"] = status_counts.get("missing", 0) + 1
            continue

        status = cached.get("status", "unknown")
        if status == "http_error" and looks_blocked(str(cached.get("html") or "")):
            status = "blocked"
        page_name = clean_person_name(str(cached.get("page_name") or ""))
        parsed_year = str(cached.get("year") or "").strip()
        parsed_location = str(cached.get("location") or "").strip()
        parsed_citation = str(cached.get("citation") or "").strip()
        entry = {
            "index": profile.index,
            "name": profile.name,
            "url": profile.url,
            "status": status,
            "page_name": page_name,
            "title": cached.get("title", ""),
            "award_heading": cached.get("award_heading", ""),
            "year": parsed_year,
            "location": parsed_location,
            "citation": parsed_citation,
            "name_match": compatible_name(profile.name, page_name) if status == "ok" else None,
            "year_match": parsed_year == profile.year if status == "ok" and profile.year is not None else None,
            "location_match": parsed_location == profile.location if status == "ok" and profile.location is not None else None,
            "citation_match": normalize_space(parsed_citation) == normalize_space(profile.citation) if status == "ok" and profile.citation is not None else None,
            "fetched_at": cached.get("fetched_at"),
            "last_attempt_status": latest_attempt(cached).get("status"),
        }
        entries.append(entry)
        status_counts[status] = status_counts.get(status, 0) + 1

    review_candidates = [
        entry
        for entry in entries
        if entry["status"] != "missing"
        and (
            entry["status"] != "ok"
            or entry.get("last_attempt_status") != "ok"
            or entry["name_match"] is False
            or entry["year_match"] is False
            or entry["location_match"] is False
            or entry["citation_match"] is False
        )
    ]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_profiles": len(profiles),
        "cached_profiles": sum(1 for profile in profiles if profile.url in cache),
        "status_counts": status_counts,
        "review_candidate_count": len(review_candidates),
        "review_candidates": review_candidates,
        "entries": entries,
    }


def main() -> int:
    args = parse_args()
    rows = load_rows(args.data)
    profiles = unique_profiles(rows)
    cache: dict[str, Any] = load_json(args.cache, {})
    try:
        ensure_manifest(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    new_requests = 0
    batch_requests = 0

    for position, profile in enumerate(profiles, start=1):
        if not args.refresh and profile.url in cache:
            continue

        if args.limit_new is not None and new_requests >= args.limit_new:
            break

        if batch_requests >= args.batch_size:
            jitter = max(0.0, args.batch_pause_jitter)
            pause = (
                max(0.0, args.batch_pause + random.uniform(-jitter, jitter))
                if args.batch_pause > 0 else 0.0
            )
            print(f"Pausing {pause:.1f}s after {batch_requests} uncached requests.", flush=True)
            time.sleep(pause)
            batch_requests = 0

        print(f"[{position}/{len(profiles)}] fetching {profile.name}: {profile.url}", flush=True)
        record_attempt(cache, profile.url, fetch_profile(profile.url))
        new_requests += 1
        batch_requests += 1

        atomic_write_json(args.cache, cache)
        atomic_write_json(args.report, build_report(profiles, cache))

        if args.delay > 0:
            time.sleep(args.delay)

    atomic_write_json(args.cache, cache)
    report = build_report(profiles, cache)
    atomic_write_json(args.report, report)

    print(
        f"Done. profiles={report['total_profiles']} cached={report['cached_profiles']} "
        f"review_candidates={report['review_candidate_count']} report={args.report}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
