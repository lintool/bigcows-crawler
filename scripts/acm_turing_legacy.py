"""Parse the older amturing.acm.org recipient layout using only the stdlib."""
from html.parser import HTMLParser
import re


class LegacyTuringParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.fields = {"name": [], "location_year": [], "citation": []}

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            if tag in {"br", "hr", "wbr"}:
                self.handle_data(" ")
            return
        self.stack.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        position = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if position is not None:
            del self.stack[position:]

    def handle_data(self, value):
        def inside(tag, css):
            return any(t == tag and css in (a.get("class") or "").split() for t, a in self.stack)
        if inside("h1", "country"):
            self.fields["name"].append(value)
        if inside("div", "description") and any(t == "span" for t, _ in self.stack):
            self.fields["location_year"].append(value)
        if inside("div", "citation") and any(t == "p" for t, _ in self.stack):
            self.fields["citation"].append(value)


def parse_legacy_turing(body):
    parser = LegacyTuringParser()
    parser.feed(body)
    values = {key: re.sub(r"\s+", " ", " ".join(parts)).strip() for key, parts in parser.fields.items()}
    match = re.fullmatch(r"(.+?)\s+[–—-]\s+(\d{4})", values["location_year"])
    # A keywords/bibliography page may have the same heading but no award citation.
    if not values["name"] or not match or not values["citation"]:
        return None
    return {"page_name": values["name"], "award_heading": "ACM A. M. Turing Award",
            "location": match[1], "year": match[2], "citation": values["citation"]}
