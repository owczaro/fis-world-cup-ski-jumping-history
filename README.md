FIS SKI JUMPING WORLD CUP RANKINGS
===============================================

Historical FIS Ski Jumping World Cup rankings data, automatically updated each season.

DATA SOURCE:
-----------
Data downloaded from official FIS PDF standings: https://data.fis-ski.com/
Official FIS (International Ski Federation) ski jumping results database.

FILE STRUCTURE:
--------------
Each season is saved in a separate CSV file with gender prefix:

MEN'S FILES:
- File naming format: men_YYYY_YYYY.csv
- Example: men_1979_1980.csv represents the 1979/1980 men's season
- Coverage: 1979/1980 season onwards

WOMEN'S FILES:
- File naming format: women_YYYY_YYYY.csv
- Example: women_2004_2005.csv represents the 2004/2005 women's season
- Note: Women's World Cup started in the 2004/2005 season

DEBUTANTS RANK FILES:
- men_debutants_rank.csv — all male athletes who appeared in World Cup standings for the first time, across all seasons
- women_debutants_rank.csv — same for female athletes

CSV COLUMN STRUCTURE (season files):
--------------------
Each season CSV file contains the following columns:
1. Rank - Final ranking position in the World Cup overall standings
2. Last Name and First Name - Athlete's name (LASTNAME Firstname format)
3. Points - Total World Cup points earned during the season
4. Debut - Whether this was the athlete's first appearance in World Cup rankings (true/false)

CSV COLUMN STRUCTURE (debutants rank files):
--------------------------------------------
1. Season - Season in YYYY_YYYY format (e.g. 2024_2025)
2. Rank - Athlete's rank in their debut season
3. Last Name and First Name - Athlete's name (LASTNAME Firstname format)
4. Points - Points earned in their debut season

DEBUT TRACKING:
--------------
- For the first season of each category, all athletes are marked as "true" for debut
  * Men: 1979/1980 season
  * Women: 2004/2005 season
- For subsequent seasons, an athlete is marked as "true" for debut if they did not appear in any previous season's rankings
- Once an athlete appears in any season, they are marked as "false" in all future appearances

AUTOMATION:
-----------
The `.github/` directory contains a GitHub Actions workflow that automatically updates
the data each year:

- **Schedule**: runs every year on April 1st at 06:00 UTC
- **Manual trigger**: can also be run manually via GitHub Actions UI → "Run workflow"
- **Script**: `.github/scripts/update_season.py`

To run the updater manually:

    pip install requests pdfplumber
    python .github/scripts/update_season.py --repo .

Options:
    --season 2025_2026   # update a specific season (default: auto-detect)
    --dry-run            # preview without writing files
    --repo /path         # path to repo root (default: current directory)
