#!/usr/bin/env python3
"""
FIS Ski Jumping World Cup - Season updater
Downloads final standings from FIS PDF and updates CSV files in the repo.

Usage:
    python update_season.py                      # auto-detect season
    python update_season.py --season 2025_2026   # specific season
    python update_season.py --season 2025_2026 --dry-run
    python update_season.py --season 2025_2026 --repo /path/to/repo

Requires: pip install requests pdfplumber
"""

import argparse
import csv
import re
import sys
import time
from datetime import date
from pathlib import Path

import pdfplumber
import requests

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; fis-ski-history-updater/1.0)"
})


# ---------------------------------------------------------------------------
# Season logic
# ---------------------------------------------------------------------------

def get_current_season() -> tuple[int, int]:
    """Returns (start_year, end_year) of the most recently completed season.

    Season X/X+1 ends ~late March of year X+1.
    When run on April 1st of year Y -> season (Y-1)/Y.
    """
    today = date.today()
    y = today.year
    if today.month < 6:
        return y - 1, y
    else:
        return y, y + 1


def season_str(y1: int, y2: int) -> str:
    return f"{y1}_{y2}"


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------

# Map of known URLs for final standings (end of season).
KNOWN_WC_PDF_URLS = {
    # format: (season_end_year, gender) -> url
    (2025, "M"): "https://medias3.fis-ski.com/pdf/2025/JP/3190/2025JP3190WC.pdf",
    (2025, "W"): "https://medias1.fis-ski.com/pdf/2025/JP/3179/2025JP3179WC.pdf",
    (2026, "M"): "https://medias1.fis-ski.com/pdf/2026/JP/3185/2026JP3185WC.pdf",
    (2026, "W"): "https://medias1.fis-ski.com/pdf/2026/JP/3184/2026JP3184WC.pdf",
}


def find_pdf_via_fis_page(season_end: int, gender: str) -> str | None:
    """Searches for the final WC standings PDF URL via the FIS standings page."""
    url = (
        f"https://www.fis-ski.com/DB/ski-jumping/cup-standings.html"
        f"?sectorcode=JP&seasoncode={season_end}&cupcode=WC"
        f"&disciplinecode=ALL&gendercode={gender}&nationcode="
    )
    print(f"  Searching FIS page: {url}")
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        pdfs = re.findall(r'https://medias\d*\.fis-ski\.com/pdf/[^\s"\'<>]+WC\.pdf', r.text)
        if pdfs:
            return pdfs[-1]
        pdfs2 = re.findall(r'https://medias\d*\.fis-ski\.com/pdf/[^\s"\'<>]+\.pdf', r.text)
        wc = [p for p in pdfs2 if "WC" in p]
        return wc[-1] if wc else None
    except Exception as e:
        print(f"  Failed to fetch FIS page: {e}")
        return None


def find_pdf_via_event_page(season_end: int, gender: str) -> str | None:
    """Searches for the final WC standings PDF URL via the last event page."""
    cal_url = (
        f"https://www.fis-ski.com/DB/ski-jumping/calendar-results.html"
        f"?noselection=false&sectorcode=JP&seasoncode={season_end}"
        f"&categorycode=WC&gendercode={gender}"
    )
    try:
        r = SESSION.get(cal_url, timeout=30)
        r.raise_for_status()
        race_ids = re.findall(r'raceid=(\d+)', r.text)
        if race_ids:
            last_id = race_ids[-1]
            result_url = f"https://www.fis-ski.com/DB/general/results.html?sectorcode=JP&raceid={last_id}"
            r2 = SESSION.get(result_url, timeout=30)
            r2.raise_for_status()
            wc_pdfs = re.findall(r'https://medias\d*\.fis-ski\.com/pdf/[^\s"\'<>]+WC\.pdf', r2.text)
            if wc_pdfs:
                return wc_pdfs[-1]
    except Exception as e:
        print(f"  Failed via calendar: {e}")
    return None


def guess_pdf_url(season_end: int, gender: str) -> list[str]:
    """Generates a list of candidate URLs based on known patterns."""
    # Pattern: medias{1-4}.fis-ski.com/pdf/{year}/JP/{codex}/{year}JP{codex}WC.pdf
    year = season_end
    codex_guesses_m = [3185, 3186, 3187, 3188, 3189, 3190, 3191, 3192]
    codex_guesses_w = [3184, 3183, 3182, 3181, 3180, 3179, 3186, 3187]
    codex_list = codex_guesses_m if gender == "M" else codex_guesses_w
    candidates = []
    for codex in codex_list:
        for media_n in [1, 2, 3, 4]:
            candidates.append(
                f"https://medias{media_n}.fis-ski.com/pdf/{year}/JP/{codex}/{year}JP{codex}WC.pdf"
            )
    return candidates


def download_wc_pdf(season_end: int, gender: str) -> Path | None:
    """Downloads the final WC standings PDF. Returns path to file or None."""
    tmp = Path(f"/tmp/fis_wc_{gender}_{season_end}.pdf")

    # 1. Try known URLs
    key = (season_end, gender)
    if key in KNOWN_WC_PDF_URLS:
        url = KNOWN_WC_PDF_URLS[key]
        print(f"  Known URL: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Downloaded {len(r.content)//1024} KB")
                return tmp
        except Exception as e:
            print(f"  Error: {e}")

    # 2. Search via FIS standings page
    url = find_pdf_via_fis_page(season_end, gender)
    if url:
        print(f"  URL from FIS page: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Downloaded {len(r.content)//1024} KB")
                return tmp
        except Exception as e:
            print(f"  Error: {e}")

    # 3. Search via event page
    url = find_pdf_via_event_page(season_end, gender)
    if url:
        print(f"  URL from event page: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                return tmp
        except Exception as e:
            print(f"  Error: {e}")

    # 4. Guess URLs
    print("  Trying to guess PDF URL...")
    for url in guess_pdf_url(season_end, gender):
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Found: {url} ({len(r.content)//1024} KB)")
                return tmp
            time.sleep(0.2)
        except Exception:
            pass

    print("  ERROR: could not find PDF", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def parse_wc_pdf(pdf_path: Path) -> list[dict]:
    """
    Parses FIS World Cup standings PDF. Handles two formats:

    Format A (2025 and earlier) - points on the line BEFORE the name:
        '1805 80 60 40 ...'
        '1. TSCHOFENIG Daniel AUT'

    Format B (2026+) - points on the same line after the country code:
        '► 1. PREVC Domen SLO 2148 50 80 20 ...'

    Returns list[{rank: int, name: str, points: int}]
    """
    # Format B: optional arrow symbol, rank, name, NAT, total_points
    fmt_b = re.compile(
        r"^[►▲▼]?\s*(\d+)\.\s+"
        r"([A-Za-z][A-Za-z\s\-\'\.]+?)\s+"
        r"([A-Z]{2,3})\s+"
        r"(\d+)"
    )
    # Format A: athlete line without points
    fmt_a_name = re.compile(
        r"^(\d+)\.\s+"
        r"([A-Za-z][A-Za-z\s\-\'\.]+?)\s+"
        r"([A-Z]{2,3})"
        r"(?:\s+[a-z]+)*\s*$"
    )
    # First number on a line (total points in format A)
    points_re = re.compile(r"^(\d+)\s")

    all_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.extend(text.split("\n"))

    results = []
    seen = set()

    for i, line in enumerate(all_lines):
        stripped = line.strip()

        # Try format B first
        m = fmt_b.match(stripped)
        if m:
            rank = int(m.group(1))
            name = m.group(2).strip()
            points = int(m.group(4))
            key = (rank, name)
            if key not in seen:
                seen.add(key)
                results.append({"rank": rank, "name": name, "points": points})
            continue

        # Try format A
        m = fmt_a_name.match(stripped)
        if m:
            rank = int(m.group(1))
            name = m.group(2).strip()
            points = None
            for j in range(i - 1, max(i - 4, -1), -1):
                pm = points_re.match(all_lines[j].strip())
                if pm:
                    candidate = int(pm.group(1))
                    if candidate > 0:
                        points = candidate
                        break
            if points is None:
                continue
            key = (rank, name)
            if key not in seen:
                seen.add(key)
                results.append({"rank": rank, "name": name, "points": points})

    results.sort(key=lambda x: x["rank"])
    return results


# ---------------------------------------------------------------------------
# CSV and debutants
# ---------------------------------------------------------------------------

def collect_previous_names(repo_root: Path, prefix: str, current_season_end: int) -> set[str]:
    """Collects all athlete names from seasons BEFORE current_season_end."""
    names: set[str] = set()
    for f in repo_root.glob(f"{prefix}_[0-9]*.csv"):
        if "debutants" in f.name:
            continue
        try:
            parts = f.stem.split("_")
            file_season_end = int(parts[-1])
        except (ValueError, IndexError):
            continue
        if file_season_end >= current_season_end:
            continue
        try:
            with open(f, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    names.add(row["Last Name and First Name"])
        except Exception as e:
            print(f"  Warning: could not read {f.name}: {e}", file=sys.stderr)
    return names


def write_season_csv(path: Path, standings: list[dict], previous_names: set[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Rank", "Last Name and First Name", "Points", "Debut"])
        for s in standings:
            debut = "false" if s["name"] in previous_names else "true"
            writer.writerow([s["rank"], s["name"], s["points"], debut])


def rebuild_debutants_rank(repo_root: Path, prefix: str) -> int:
    """
    Rebuilds {prefix}_debutants_rank.csv from all seasons.
    Contains only debutants (Debut=true/yes) with their first season.
    Returns the total number of debutants.
    """
    debut_map: dict[str, dict] = {}

    for f in sorted(repo_root.glob(f"{prefix}_[0-9]*.csv")):
        if "debutants" in f.name:
            continue
        season = f.stem[len(prefix) + 1:]  # e.g. "2024_2025"
        try:
            with open(f, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("Debut", "").lower() in ("true", "yes"):
                        name = row["Last Name and First Name"]
                        if name not in debut_map:
                            debut_map[name] = {
                                "season": season,
                                "rank": int(float(row["Rank"])),
                                "points": int(float(row["Points"])),
                                "name": name,
                            }
        except Exception as e:
            print(f"  Warning: {f.name}: {e}", file=sys.stderr)

    debutants = sorted(debut_map.values(), key=lambda x: (x["season"], x["rank"]))
    out = repo_root / f"{prefix}_debutants_rank.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Season", "Rank", "Last Name and First Name", "Points"])
        for d in debutants:
            writer.writerow([d["season"], d["rank"], d["name"], d["points"]])

    return len(debutants)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="FIS Ski Jumping standings updater")
    parser.add_argument("--season", help="Season e.g. 2025_2026 (default: auto-detect)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files")
    parser.add_argument("--repo", default=".", help="Path to repo (default: .)")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"ERROR: repo not found: {repo_root}", file=sys.stderr)
        return 1

    if args.season:
        try:
            y1, y2 = map(int, args.season.split("_"))
        except ValueError:
            print(f"ERROR: invalid season format: {args.season} (expected: YYYY_YYYY)", file=sys.stderr)
            return 1
    else:
        y1, y2 = get_current_season()

    print(f"=== FIS Ski Jumping updater | season {y1}/{y2} ===")
    if args.dry_run:
        print("  [DRY RUN - not writing files]")

    had_error = False

    for gender, prefix in [("M", "men"), ("W", "women")]:
        s_str = season_str(y1, y2)
        out_csv = repo_root / f"{prefix}_{s_str}.csv"
        print(f"\n[{prefix.upper()}] {out_csv.name}")

        # Download PDF
        pdf_path = download_wc_pdf(y2, gender)
        if pdf_path is None:
            print(f"  ERROR: no PDF found for {gender} {y2}", file=sys.stderr)
            had_error = True
            continue

        # Parse
        standings = parse_wc_pdf(pdf_path)
        if not standings:
            print(f"  ERROR: no data in PDF", file=sys.stderr)
            had_error = True
            continue

        print(f"  Athletes: {len(standings)}")
        print(f"  Top 3: {', '.join(s['name'] for s in standings[:3])}")

        # Debutants
        prev_names = collect_previous_names(repo_root, prefix, y2)
        debutants = [s for s in standings if s["name"] not in prev_names]
        print(f"  Debutants ({len(debutants)}): "
              + ", ".join(d["name"] for d in debutants[:5])
              + ("..." if len(debutants) > 5 else ""))

        if args.dry_run:
            print(f"  [DRY RUN] Skipping write of {out_csv.name}")
            continue

        # Save
        write_season_csv(out_csv, standings, prev_names)
        print(f"  Saved: {out_csv}")

        # Rebuild debutants rank
        n_deb = rebuild_debutants_rank(repo_root, prefix)
        print(f"  Updated {prefix}_debutants_rank.csv ({n_deb} debutants)")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
