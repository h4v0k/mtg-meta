import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

st.set_page_config(page_title="MTG Ultimate Meta Tool", layout="wide")

# --- SCRAPER ---
@st.cache_resource
def get_scraper():
    # Adding a referer to look more like a real user session
    s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    s.headers.update({
        "Referer": "https://www.google.com/",
        "Accept-Language": "en-US,en;q=0.9"
    })
    return s

# --- CONFIG ---
FORMAT_MAP = {
    "Standard": {"gold": "standard", "top8": "ST"},
    "Modern": {"gold": "modern", "top8": "MO"},
    "Pioneer": {"gold": "pioneer", "top8": "PI"},
    "Legacy": {"gold": "legacy", "top8": "LE"},
    "Pauper": {"gold": "pauper", "top8": "PAU"}
}

# --- DATA FETCHING ---

@st.cache_data(ttl=86400)
def fetch_goldfish_meta(format_name):
    scraper = get_scraper()
    # Path /full is generally more stable for scraping than the tile view
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        
        # Method 1: Target Archetype Tiles (if on main page)
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({"Deck Name": name.text.strip(), "Meta %": meta.text.strip()})

        # Method 2: Table Search (Standard on /full page)
        if not decks:
            table = soup.select_one("table.metagame-table")
            if table:
                for row in table.select("tr"):
                    cols = row.select("td")
                    if len(cols) >= 4:
                        name_link = cols[1].find("a")
                        pct_text = cols[3].text.strip()
                        if name_link and "%" in pct_text:
                            decks.append({"Deck Name": name_link.text.strip(), "Meta %": pct_text})

        # Method 3: The "Greedy" Parser (Search for ANY link with percentage nearby)
        if not decks:
            for link in soup.find_all("a", href=re.compile(r'/archetype/')):
                parent_row = link.find_parent("tr")
                if parent_row:
                    row_text = parent_row.get_text()
                    pct_match = re.search(r'(\d+\.\d+%)', row_text)
                    if pct_match:
                        decks.append({"Deck Name": link.text.strip(), "Meta %": pct_match.group(1)})
        
        df = pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"])
        # Remove navigation links that might be caught
        blacklist = ["Price", "Decks", "Metagame", "Standard", "Modern", "Pioneer", "Legacy", "Pauper"]
        df = df[~df["Deck Name"].isin(blacklist)]
