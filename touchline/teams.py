"""Team identity: a curated alias table (never fuzzy-match) and name normalisation."""

import re
import sqlite3
import unicodedata

# Provider spelling -> canonical display name. Add entries here when a new spelling
# shows up in the quarantine table on the Engine page.
ALIASES = {
    "Manchester United": "Man United",
    "Manchester City": "Man City",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham",
    "Brighton & Hove Albion": "Brighton",
    "Wolverhampton Wanderers": "Wolves",
    "West Ham United": "West Ham",
    "Leicester City": "Leicester",
    "Leeds United": "Leeds",
    "Ipswich Town": "Ipswich",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Sheffield United": "Sheffield United",
    "West Bromwich Albion": "West Brom",
    "Paris Saint-Germain": "Paris SG",
    "Olympique Lyonnais": "Lyon",
    "Olympique de Marseille": "Marseille",
    "AS Monaco": "Monaco",
    "Stade Rennais": "Rennes",
    "Stade Brestois 29": "Brest",
    "Stade de Reims": "Reims",
    "RC Strasbourg Alsace": "Strasbourg",
    "RC Lens": "Lens",
    "LOSC Lille": "Lille",
    "OGC Nice": "Nice",
    "AJ Auxerre": "Auxerre",
    "Le Havre": "Le Havre",
    "Hellas Verona": "Verona",
    "Internazionale Milano": "Inter",
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "SSC Napoli": "Napoli",
    "SS Lazio": "Lazio",
    "ACF Fiorentina": "Fiorentina",
    "US Lecce": "Lecce",
    "Atalanta BC": "Atalanta",
    "Parma Calcio 1913": "Parma",
    "Como 1907": "Como",
    "Udinese Calcio": "Udinese",
    "Real Betis Balompié": "Betis",
    "Atlético de Madrid": "Ath Madrid",
    "Atletico Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "Athletic Club Bilbao": "Ath Bilbao",
    "Deportivo Alavés": "Alaves",
    "RCD Espanyol": "Espanol",
    "RCD Mallorca": "Mallorca",
    "CA Osasuna": "Osasuna",
    "RC Celta de Vigo": "Celta",
    "Celta Vigo": "Celta",
    "Real Sociedad de Fútbol": "Sociedad",
    "Real Sociedad": "Sociedad",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Rayo Vallecano": "Vallecano",
    "Bayern München": "Bayern Munich",
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Bayer Leverkusen": "Leverkusen",
    "Borussia Mönchengladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "VfB Stuttgart": "Stuttgart",
    "VfL Wolfsburg": "Wolfsburg",
    "SC Freiburg": "Freiburg",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    "1899 Hoffenheim": "Hoffenheim",
    "RB Leipzig": "RB Leipzig",
    "1. FSV Mainz 05": "Mainz",
    "FSV Mainz 05": "Mainz",
    "1. FC Union Berlin": "Union Berlin",
    "Union Berlin": "Union Berlin",
    "1. FC Köln": "Koln",
    "Hamburger SV": "Hamburg",
    "SV Werder Bremen": "Werder Bremen",
    "Werder Bremen": "Werder Bremen",
    "FC St. Pauli": "St Pauli",
    "FC Augsburg": "Augsburg",
    "1. FC Heidenheim 1846": "Heidenheim",
    "AC Monza": "Monza",
    "Angers SCO": "Angers",
    "Bologna FC 1909": "Bologna",
    "Cagliari Calcio": "Cagliari",
    "Club Atlético de Madrid": "Ath Madrid",
    "ES Troyes AC": "Troyes",
    "Frosinone Calcio": "Frosinone",
    "Genoa CFC": "Genoa",
    "Le Havre AC": "Le Havre",
    "Levante UD": "Levante",
    "Lille OSC": "Lille",
    "RC Deportivo La Coruña": "La Coruna",
    "RCD Espanyol de Barcelona": "Espanol",
    "Racing Club de Lens": "Lens",
    "Real Racing Club de Santander": "Santander",
    "SC Paderborn 07": "Paderborn",
    "SV 07 Elversberg": "Elversberg",
    "Stade Rennais FC 1901": "Rennes",
    "US Sassuolo Calcio": "Sassuolo",
}

_SUFFIX = re.compile(r"^(?:FC |AFC )|(?: FC| AFC| CF)$")


def norm(name: str) -> str:
    """Lowercase ASCII letters/digits only: the stable team or player key."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def display_name(name: str) -> str:
    name = name.strip()
    clean = ALIASES.get(name)
    if clean:
        return clean
    stripped = _SUFFIX.sub("", name).strip()
    return ALIASES.get(stripped, stripped)


def canonical(conn: sqlite3.Connection, source: str, name: str) -> str:
    """Resolve a provider team name to a team id, creating the team on first sight."""
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Invalid team name")
    row = conn.execute(
        "SELECT team_id FROM team_aliases WHERE source=? AND name=?", (source, name)
    ).fetchone()
    if row:
        return row[0]
    clean = display_name(name)
    team_id = norm(clean)
    if not team_id:
        raise ValueError("Invalid team identity")
    conn.execute("INSERT OR IGNORE INTO teams(id, name) VALUES(?, ?)", (team_id, clean))
    conn.execute(
        "INSERT INTO team_aliases(source, name, team_id) VALUES(?, ?, ?)", (source, name, team_id)
    )
    return team_id
