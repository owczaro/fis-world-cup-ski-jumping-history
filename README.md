FIS SKI JUMPING WORLD CUP RANKINGS
===============================================

This directory contains historical FIS Ski Jumping World Cup rankings data.

DATA SOURCE:
-----------
Data was downloaded from: https://data.fis-ski.com/
Official FIS (International Ski Federation) ski jumping results database

FILE STRUCTURE:
--------------
Each season is saved in a separate CSV file with gender prefix:

MEN'S FILES:
- File naming format: men_YYYY_YYYY.csv
- Example: men_1979_1980.csv represents the 1979/1980 men's season

WOMEN'S FILES:
- File naming format: women_YYYY_YYYY.csv
- Example: women_2004_2005.csv represents the 2004/2005 women's season
- Note: Women's World Cup started in the 2004/2005 season

CSV COLUMN STRUCTURE:
--------------------
Each CSV file contains the following columns:
1. Rank - Final ranking position in the World Cup overall standings
2. Last Name and First Name - Athlete's name (LASTNAME Firstname format)
3. Points - Total World Cup points earned during the season
4. Debut - Whether this was the athlete's first appearance in World Cup rankings (true/false)

DEBUT TRACKING:
--------------
- For the first season of each category, all athletes are marked as "true" for debut
  * Men: 1979/1980 season
  * Women: 2004/2005 season
- For subsequent seasons, an athlete is marked as "true" for debut if they did not appear in any previous season's rankings
- Once an athlete appears in any season, they are marked as "false" in all future appearances
