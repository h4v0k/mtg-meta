import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re  # Fixed: Import is now at the top

# --- PAGE CONFIG ---
st.set_page_config(page_title="MTG Meta & Spicy Tracker", layout="wide")

# Initialize Scraper with a specific browser profile to avoid 2025 Cloudflare blocks
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# --- CONFIGURATION & MAPPINGS ---
FORMAT_MAP = {
    "Standard": {"gold": "standard", "top8": "ST"},
    "Modern": {"gold": "modern", "top8": "MO"},
    "Pioneer": {"gold": "pioneer", "top8": "PI"},
    "Legacy": {"gold": "legacy", "top8": "LE"},
    "Pauper": {"gold": "pauper", "top8": "PAU"}
}

# --- DATA FETCHING FUNCTIONS ---

@st.cache_data(ttl="1d")
def get_goldfish_meta(format_name):
    """Pulls the metagame percentage breakdown from MTGGoldfish"""
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Look for the archetypes
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({
                    "Deck Name": name.text.strip(),
                    "Meta %": meta.text.strip()
                })
        
        # Fallback for table layout
        if not decks:
            table = soup.find('table', class_='metagame-table')
            if table:
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) > 3:
                        decks.append({"Deck Name": cols[1].text.strip(), "Meta %": cols[3].text.strip()})

        return pd.DataFrame(decks)
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def get_top8_events(format_code, days_limit):
    """Pulls recent Top 8 results from MTGTop8"""
    # cp=1 is last 2 weeks, cp=2 is last 2 months
    cp_val = "2" if days_limit > 14 else "1"
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp={cp_val}"
    
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                # Date filtering
                try:
                    ev_date = datetime.strptime(date_str, "%d/%m/%y")
                    if ev_date < (datetime.now() - timedelta(days=days_limit)):
                        continue
                except: pass

                link_tag = cols[1].find("a")
                if link_tag:
                    events.append({
                        "Date": date_str,
                        "Place": cols[2].text.strip(),
                        "Deck Title": link_tag.text.strip(),
                        "Link": "https://www.mtgtop8.com/" + link_tag['href']
                    })
        return pd.DataFrame(events)
    except:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def get_decklist(url):
    """Pulls the actual card list from an MTGTop8 deck link"""
    try:
        response = scraper.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        # MTGTop8 cards are usually in divs with class 'deck_line'
        cards = [line.text.strip() for line in soup.select(".deck_line") if line.text.strip()]
        return cards
    except
