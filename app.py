import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="MTG Meta & Spicy Tracker", layout="wide")

# Initialize Scraper
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# --- CONFIGURATION ---
FORMAT_MAP = {
    "Standard": {"gold": "standard", "top8": "ST"},
    "Modern": {"gold": "modern", "top8": "MO"},
    "Pioneer": {"gold": "pioneer", "top8": "PI"},
    "Legacy": {"gold": "legacy", "top8": "LE"},
    "Pauper": {"gold": "pauper", "top8": "PAU"},
    "Vintage": {"gold": "vintage", "top8": "VI"},
    "Commander": {"gold": "commander", "top8": "EDH"}
}

# --- FUNCTIONS ---

@st.cache_data(ttl="1d")
def get_goldfish_meta(format_name):
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Method 1: Archetype tiles
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name_tag = tile.select_one(".deck-price-paper a")
            meta_tag = tile.select_one(".metagame-percentage-column")
            if name_tag and meta_tag:
                decks.append({
                    "Deck Name": name_tag.text.strip(),
                    "Meta %": meta_tag.text.strip()
                })
        
        # Method 2: Table fallback
        if not decks:
            table = soup.find('table', class_='metagame-table')
            if table:
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        decks.append({
                            "Deck Name": cols[1].text.strip(),
                            "Meta %": cols[3].text.strip()
                        })
        return pd.DataFrame(decks)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def get_top8_events(format_code, days_limit):
    # Fetch enough data to cover the timeframe (cp=2 covers roughly 2 months)
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
