#!/usr/bin/env python3
"""
FIS Ski Jumping World Cup - Season updater
Pobiera finalne standings z FIS PDF i aktualizuje CSV w repo.

Uzycie:
    python update_season.py                      # auto-wykryj sezon
    python update_season.py --season 2025_2026   # konkretny sezon
    python update_season.py --season 2025_2026 --dry-run
    python update_season.py --season 2025_2026 --repo /sciezka/do/repo

Wymaga: pip install requests pdfplumber
"""

import argparse
import csv
import os
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
# Logika sezonu
# ---------------------------------------------------------------------------

def get_current_season() -> tuple[int, int]:
    """Zwraca (rok_start, rok_end) ostatnio zakonczeonego sezonu.

    Sezon X/X+1 konczy sie ~koniec marca roku X+1.
    Gdy odpalamy 1 kwietnia roku Y -> sezon (Y-1)/Y.
    """
    today = date.today()
    y = today.year
    # Przed czerwcem -> sezon konczy sie w tym roku
    if today.month < 6:
        return y - 1, y
    else:
        return y, y + 1


def season_str(y1: int, y2: int) -> str:
    return f"{y1}_{y2}"


# ---------------------------------------------------------------------------
# Pobieranie PDFow
# ---------------------------------------------------------------------------

# Mapa znanych URL-i do finalnych standings (koniec sezonu).
# Claude Code uzupelnia je recznie lub skrypt szuka automatycznie.
KNOWN_WC_PDF_URLS = {
    # format: (season_end_year, gender) -> url
    (2025, "M"): "https://medias3.fis-ski.com/pdf/2025/JP/3190/2025JP3190WC.pdf",
    (2025, "W"): "https://medias1.fis-ski.com/pdf/2025/JP/3179/2025JP3179WC.pdf",
    # 2026 - skrypt szuka automatycznie przez FIS strony
    # (2026, "M"): "https://medias?.fis-ski.com/pdf/2026/JP/3185/2026JP3185WC.pdf",
    # (2026, "W"): "https://medias?.fis-ski.com/pdf/2026/JP/3184/2026JP3184WC.pdf",
}


def find_pdf_via_fis_page(season_end: int, gender: str) -> str | None:
    """Szuka URL do finalnego WC PDF przez strone standings FIS."""
    url = (
        f"https://www.fis-ski.com/DB/ski-jumping/cup-standings.html"
        f"?sectorcode=JP&seasoncode={season_end}&cupcode=WC"
        f"&disciplinecode=ALL&gendercode={gender}&nationcode="
    )
    print(f"  Szukam PDF na stronie FIS: {url}")
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        # Szukaj linkow do PDFow ze standings
        pdfs = re.findall(r'https://medias\d*\.fis-ski\.com/pdf/[^\s"\'<>]+WC\.pdf', r.text)
        if pdfs:
            # Ostatni link = najnowszy (po finalnym zawodzie)
            return pdfs[-1]
        # Fallback: szukaj jakiegokolwiek linku do WC PDF
        pdfs2 = re.findall(r'https://medias\d*\.fis-ski\.com/pdf/[^\s"\'<>]+\.pdf', r.text)
        wc = [p for p in pdfs2 if "WC" in p]
        return wc[-1] if wc else None
    except Exception as e:
        print(f"  Nie udalo sie pobrac strony FIS: {e}")
        return None


def find_pdf_via_event_page(season_end: int, gender: str) -> str | None:
    """Szuka URL do finalnego WC PDF przez strone ostatniego eventu sezonu."""
    # Ostatnie eventy sezonu sa zawsze w Planica
    # Dla mezczyzn: race ID ostatniego zawodu w Planica
    # Dla kobiet: race ID ostatniego zawodu kobiet
    # Skrypt probuje odgadnac race ID (zwykle w okolicach 7580-7590 dla 2026)

    # Najpierw szukamy przez FIS calendar
    cal_url = (
        f"https://www.fis-ski.com/DB/ski-jumping/calendar-results.html"
        f"?noselection=false&sectorcode=JP&seasoncode={season_end}"
        f"&categorycode=WC&gendercode={gender}"
    )
    try:
        r = SESSION.get(cal_url, timeout=30)
        r.raise_for_status()
        # Szukaj linku do ostatniego wyniki (Planica)
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
        print(f"  Nie udalo sie przez calendar: {e}")
    return None


def guess_pdf_url(season_end: int, gender: str) -> list[str]:
    """Generuje liste kandydujacych URL-i na podstawie wzorcow."""
    # Wzorzec: medias{1-4}.fis-ski.com/pdf/{year}/JP/{codex}/{year}JP{codex}WC.pdf
    # Codex dla kobiet jest zawsze o 1 nizszy niz dla mezczyzn (Planica women = dzien przed men)
    # Dla sezonu 2025: men=3190 (po ostatnim zawodzie Planica), women=3179 (Lahti)
    # Dla sezonu 2026: men~3185, women~3184
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
    """Pobiera finalny WC standings PDF. Zwraca sciezke do pliku lub None."""
    tmp = Path(f"/tmp/fis_wc_{gender}_{season_end}.pdf")

    # 1. Sprawdz znane URL-e
    key = (season_end, gender)
    if key in KNOWN_WC_PDF_URLS:
        url = KNOWN_WC_PDF_URLS[key]
        print(f"  Znany URL: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Pobrano {len(r.content)//1024} KB")
                return tmp
        except Exception as e:
            print(f"  Blad: {e}")

    # 2. Szukaj przez strone FIS
    url = find_pdf_via_fis_page(season_end, gender)
    if url:
        print(f"  URL ze strony FIS: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Pobrano {len(r.content)//1024} KB")
                return tmp
        except Exception as e:
            print(f"  Blad: {e}")

    # 3. Szukaj przez strone eventu
    url = find_pdf_via_event_page(season_end, gender)
    if url:
        print(f"  URL ze strony eventu: {url}")
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                return tmp
        except Exception as e:
            print(f"  Blad: {e}")

    # 4. Guess URL-e
    print("  Probuje odgadnac URL PDFa...")
    for url in guess_pdf_url(season_end, gender):
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 10000:
                tmp.write_bytes(r.content)
                print(f"  Znaleziono: {url} ({len(r.content)//1024} KB)")
                return tmp
            time.sleep(0.2)
        except Exception:
            pass

    print("  BLAD: nie udalo sie znalezc PDF", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Parsowanie PDF
# ---------------------------------------------------------------------------

def parse_wc_pdf(pdf_path: Path) -> list[dict]:
    """
    Parsuje FIS World Cup standings PDF. Obsluguje dwa formaty:

    Format A (2025 i wczesniej) - punkty na linii PRZED nazwiskiem:
        '1805 80 60 40 ...'
        '1. TSCHOFENIG Daniel AUT'

    Format B (2026+) - punkty na tej samej linii po kodzie kraju:
        '► 1. PREVC Domen SLO 2148 50 80 20 ...'

    Zwraca list[{rank: int, name: str, points: int}]
    """
    # Format B: opcjonalny symbol, rank, nazwa, NAT, total_points
    fmt_b = re.compile(
        r"^[►▲▼]?\s*(\d+)\.\s+"
        r"([A-Za-z][A-Za-z\s\-\'\.]+?)\s+"
        r"([A-Z]{2,3})\s+"
        r"(\d+)"
    )
    # Format A: linia zawodnika bez punktow
    fmt_a_name = re.compile(
        r"^(\d+)\.\s+"
        r"([A-Za-z][A-Za-z\s\-\'\.]+?)\s+"
        r"([A-Z]{2,3})"
        r"(?:\s+[a-z]+)*\s*$"
    )
    # Pierwsza liczba na linii (total points w formacie A)
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

        # Sprobuj format B najpierw
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

        # Sprobuj format A
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
# CSV i debiutanci
# ---------------------------------------------------------------------------

def collect_previous_names(repo_root: Path, prefix: str, current_season_end: int) -> set[str]:
    """Zbiera wszystkie nazwiska ze wszystkich sezonow PRZED current_season_end."""
    names: set[str] = set()
    for f in repo_root.glob(f"{prefix}_[0-9]*.csv"):
        if "debutants" in f.name:
            continue
        # Wyciagnij rok konca sezonu z nazwy pliku (np. men_2023_2024.csv -> 2024)
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
            print(f"  Ostrzezenie: nie udalo sie odczytac {f.name}: {e}", file=sys.stderr)
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
    Przebudowuje {prefix}_debutants_rank.csv z wszystkich sezonow.
    Zawiera tylko debiutantow (Debut=true) z ich pierwszym sezonem.
    Zwraca liczbe debiutantow.
    """
    debut_map: dict[str, dict] = {}

    for f in sorted(repo_root.glob(f"{prefix}_[0-9]*.csv")):
        if "debutants" in f.name:
            continue
        season = f.stem[len(prefix) + 1:]  # "2024_2025"
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
            print(f"  Ostrzezenie: {f.name}: {e}", file=sys.stderr)

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
    parser.add_argument("--season", help="Sezon np. 2025_2026 (domyslnie: auto)")
    parser.add_argument("--dry-run", action="store_true", help="Nie zapisuj plikow")
    parser.add_argument("--repo", default=".", help="Sciezka do repo (domyslnie: .)")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"BLAD: repo nie istnieje: {repo_root}", file=sys.stderr)
        return 1

    if args.season:
        try:
            y1, y2 = map(int, args.season.split("_"))
        except ValueError:
            print(f"BLAD: zly format sezonu: {args.season} (oczekiwany: YYYY_YYYY)", file=sys.stderr)
            return 1
    else:
        y1, y2 = get_current_season()

    print(f"=== FIS Ski Jumping updater | sezon {y1}/{y2} ===")
    if args.dry_run:
        print("  [DRY RUN - nie zapisuje plikow]")

    had_error = False

    for gender, prefix in [("M", "men"), ("W", "women")]:
        s_str = season_str(y1, y2)
        out_csv = repo_root / f"{prefix}_{s_str}.csv"
        print(f"\n[{prefix.upper()}] {out_csv.name}")

        # Pobierz PDF
        pdf_path = download_wc_pdf(y2, gender)
        if pdf_path is None:
            print(f"  BLAD: brak PDF dla {gender} {y2}", file=sys.stderr)
            had_error = True
            continue

        # Parsuj
        standings = parse_wc_pdf(pdf_path)
        if not standings:
            print(f"  BLAD: brak danych w PDF", file=sys.stderr)
            had_error = True
            continue

        print(f"  Zawodnikow: {len(standings)}")
        print(f"  Top 3: {', '.join(s['name'] for s in standings[:3])}")

        # Debiutanci
        prev_names = collect_previous_names(repo_root, prefix, y2)
        debutants = [s for s in standings if s["name"] not in prev_names]
        print(f"  Debiutanci ({len(debutants)}): "
              + ", ".join(d["name"] for d in debutants[:5])
              + ("..." if len(debutants) > 5 else ""))

        if args.dry_run:
            print(f"  [DRY RUN] Pomijam zapis {out_csv.name}")
            continue

        # Zapisz
        write_season_csv(out_csv, standings, prev_names)
        print(f"  Zapisano: {out_csv}")

        # Przebuduj debutants_rank
        n_deb = rebuild_debutants_rank(repo_root, prefix)
        print(f"  Zaktualizowano {prefix}_debutants_rank.csv ({n_deb} debiutantow)")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
