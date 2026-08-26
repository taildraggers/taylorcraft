"""Scraper for Taylorcraft listings on barnstormers.com.

Barnstormers' single-manufacturer category pages (the same pattern seen in
the companion Aviat, CubCrafters, de Havilland, Maule, Van's RV, RANS,
Luscombe, Just Aircraft, Kitfox, Bellanca, Stearman, Waco, and Pitts
repos) can mix in off-brand or off-topic listings with no distinguishing
HTML markup from the genuine ones. So results are filtered by title
against a small allowlist of Taylorcraft-specific terms before being
published.

Taylorcraft model codes (BC-12D, BC-65, DCO-65, DC-65, L-2, F-19, F-21,
F-21A, F-21B, F-22, F-22A) are short and generic-looking enough that,
unlike RANS's S-numbers or Luscombe's 8-series codes, they are NOT
trusted standalone - every model match here requires the title to also
say "Taylorcraft" explicitly (the same lesson learned the hard way in the
companion Piper repo, where a bare "Cub" mislabeled non-Piper homebuilts
as genuine Pipers). A bare mention of "Taylorcraft" with no specific
model code stated is enough on its own to publish too, the same policy
used in the companion Stearman/Waco/Pitts repos, since plenty of genuine
listings don't state an exact variant.

Titles that read as parts, accessories, services, or raffles are still
dropped regardless. Surviving titles are rewritten to a canonical "YEAR
TAYLORCRAFT MODEL" form when the ad states a model year and a specific
model, "YEAR Taylorcraft" when only the model is missing, "TAYLORCRAFT
MODEL" when only the year is missing, or plain "Taylorcraft" when neither
is stated.

Gear note: most Taylorcraft models are conventional tailwheel-only, but
the F-22 is a genuine exception - some sources describe "F-22A"
specifically as the tricycle-gear version, while others describe the
whole F-22 line as offering a buyer's choice of tailwheel or tricycle
gear (unlike Van's RV, where the "A" suffix unambiguously always means
tricycle). Given that ambiguity, no categorical model-based exclusion is
applied here - the standard text-based tricycle/nosewheel safety net used
in the RANS, Luscombe, Just Aircraft, Kitfox, Bellanca, and Van's RV
repos is relied on instead to catch specific tricycle-gear F-22 ads via
their own ad text.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .common import (
    Listing,
    extract_date,
    extract_location,
    extract_price,
    fetch,
    format_aircraft_title,
)

SITE_NAME = "Barnstormers.com"
BASE = "https://www.barnstormers.com"
MAKE = "Taylorcraft"

# Category page for Taylorcraft taildragger listings on Barnstormers.
CATEGORY_URLS = [
    f"{BASE}/category-22538-Taildragger--Taylorcraft.html",
]

MAX_PAGES = 10
LISTING_LINK_RE = re.compile(r"^/classified-(\d+)-(.+)\.html$")
GENERIC_SITE_TITLE_SNIPPET = "barnstormers.com find aircraft"


def _compact(text: str) -> str:
    return re.sub(r"[\s-]", "", text.lower())


# "Taylorcraft" is the only coarse-gate phrase used - the short model
# codes below carry too much substring-collision risk to use safely as a
# coarse filter. The fine-grained _extract_model has its own
# word-boundary-safe checks and, more importantly, requires "taylorcraft"
# too.
TARGET_MODEL_PHRASES = ["taylorcraft"]


def _matches_target_models(title: str) -> bool:
    compact = _compact(title)
    return any(phrase in compact for phrase in TARGET_MODEL_PHRASES)


_BRAND_RE = re.compile(r"\btaylorcraft\b", re.IGNORECASE)

_BC_RE = re.compile(r"\bbc[\s-]?12[\s-]?(d)?\b", re.IGNORECASE)
_BC65_RE = re.compile(r"\bbc[\s-]?65\b", re.IGNORECASE)
_DCO_RE = re.compile(r"\bdco[\s-]?65\b", re.IGNORECASE)
_DC_RE = re.compile(r"\bdc[\s-]?65\b", re.IGNORECASE)
_L2_RE = re.compile(r"\bl[\s-]?2\b", re.IGNORECASE)
_F_RE = re.compile(r"\bf[\s-]?(19|21|22)[\s-]?([ab])?\b", re.IGNORECASE)
_NUMERIC_MODEL_RE = re.compile(r"\btaylorcraft\s+(\d{2})\b", re.IGNORECASE)


def _extract_model(title: str) -> tuple[str, str] | None:
    if not _BRAND_RE.search(title):
        return None

    match = _BC_RE.search(title)
    if match:
        suffix = match.group(1)
        return MAKE, f"BC-12{suffix.upper()}" if suffix else "BC-12"

    if _BC65_RE.search(title):
        return MAKE, "BC-65"
    if _DCO_RE.search(title):
        return MAKE, "DCO-65"
    if _DC_RE.search(title):
        return MAKE, "DC-65"
    if _L2_RE.search(title):
        return MAKE, "L-2"

    match = _F_RE.search(title)
    if match:
        number, suffix = match.groups()
        return MAKE, f"F-{number}{suffix.upper()}" if suffix else f"F-{number}"

    match = _NUMERIC_MODEL_RE.search(title)
    if match:
        return MAKE, match.group(1)

    return MAKE, ""


# Ads whose title or body text explicitly calls out tricycle/nosewheel gear
# are dropped, regardless of which model they are - see module docstring.
_NON_TAILWHEEL_KEYWORDS = (
    "tricycle gear",
    "tricycle landing gear",
    "trike gear",
    "tri-gear",
    "tri gear",
    "nosewheel",
    "nose wheel",
    "nose-wheel",
)


def _is_non_tailwheel(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _NON_TAILWHEEL_KEYWORDS)


def _page_url(category_url: str, page: int) -> str:
    """Build a category page's URL directly.

    Barnstormers' category pager renders as page-number buttons with no
    "Next" text or rel="next" attribute for a link-following heuristic to
    find (confirmed on the companion Van's RV, Stearman, Waco, and Pitts
    repos, where that approach silently stopped after page 1) - so each
    page's URL is built from the known
    ?seocategory=<url-encoded-path>&page=<n> pattern instead.
    """
    if page <= 1:
        return category_url
    path = urlparse(category_url).path
    return f"{category_url}?seocategory={quote(path, safe='')}&page={page}"


def _title_from_url(url: str) -> str:
    """Listing pages share a generic <title>/<h1>, but the URL slug is the ad's own title."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    match = LISTING_LINK_RE.match("/" + slug)
    if not match:
        return unquote(slug)
    return unquote(match.group(2)).replace("-", " ").strip()


def _find_listing_links(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        if LISTING_LINK_RE.match(href):
            links.add(urljoin(BASE, href))
    return links


def _debug_dump_hrefs(html: str, limit: int = 25) -> None:
    soup = BeautifulSoup(html, "lxml")
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    interesting = [h for h in hrefs if "classified" in h.lower() or "taylorcraft" in h.lower()]
    sample = interesting[:limit] or hrefs[:limit]
    print(f"  [debug] {len(hrefs)} total <a href> on page; sample: {sample}")


def _parse_detail_page(url: str, html: str) -> Listing | None:
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    if title:
        title = re.sub(r"\s*[\|\-]\s*Barnstormers.*$", "", title, flags=re.IGNORECASE).strip()
    if not title or GENERIC_SITE_TITLE_SNIPPET in title.lower():
        title = _title_from_url(url)
    if not title:
        return None

    if not _matches_target_models(title):
        return None

    text = soup.get_text(" ", strip=True)

    if _is_non_tailwheel(title) or _is_non_tailwheel(text):
        return None

    formatted_title = format_aircraft_title(title, text, _extract_model)
    if not formatted_title:
        return None
    # A bare-"Taylorcraft" match (no specific model code) leaves a
    # trailing space from format_aircraft_title's "{make} {model}" join,
    # since _extract_model returns an empty model string in that case.
    title = formatted_title.rstrip()

    price = extract_price(text)
    location = extract_location(text)
    date_posted = extract_date(text)

    return Listing(
        title=title,
        price=price,
        location=location,
        date_posted=date_posted,
        site=SITE_NAME,
        url=url,
    )


def scrape() -> list[Listing]:
    print(f"[{SITE_NAME}] starting scrape")
    all_links: set[str] = set()

    for category_url in CATEGORY_URLS:
        seen_this_category: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = _page_url(category_url, page)
            html = fetch(url)
            if not html:
                break
            links = _find_listing_links(html)
            new_links = links - seen_this_category
            print(f"  [{category_url}] page {page}: {len(links)} links ({len(new_links)} new)")
            if page == 1 and not links:
                _debug_dump_hrefs(html)
            seen_this_category |= links
            if not new_links:
                break
        all_links |= seen_this_category

    print(f"[{SITE_NAME}] {len(all_links)} unique listing URLs found")

    candidate_links = {url for url in all_links if _matches_target_models(_title_from_url(url))}
    print(f"[{SITE_NAME}] {len(candidate_links)} match Taylorcraft product names")

    listings: list[Listing] = []
    for url in sorted(candidate_links):
        html = fetch(url)
        if not html:
            continue
        listing = _parse_detail_page(url, html)
        if listing:
            listings.append(listing)

    print(f"[{SITE_NAME}] parsed {len(listings)} listings")
    return listings
