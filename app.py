import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="MTG Meta & Spicy Tracker", layout="wide")

# --- SCRAPER ENGINE ---
def get_scraper():
    # Chrome 120+ profile to bypass modern Cloudflare checks
    return cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )

# --- CONFIGURATION ---
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
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Method 1: Target Archetype Tiles
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({
                    "Deck Name": name.text.strip(),
                    "Meta %": meta.text.strip()
                })
        
        # Method 2: Table Fallback
        if not decks:
            table = soup.find("table", class_=re.compile(r'metagame-table'))
            if table:
                for row in table.select("tr")[1:]:
                    cols = row.select("td")
                    if len(cols) >= 4:
                        decks.append({
                            "Deck Name": cols[1].text.strip(),
                            "Meta %": cols[3].text.strip()
                        })
        return pd.DataFrame(decks)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
    # cp=2 pulls last 2 months of data
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        for row in soup.select("tr.hover_tr"):
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
                    ev_date = datetime.strptime(date_str, "%d/%m/%y")
                    if (datetime.now() - ev_date).days > days_limit:
                        continue
                except:
                    continue
                
                link = cols[1].find("a")
                if link:
                    events.append({
                        "Date": date_str,
                        "Place": cols[2].text.strip(),
                        "Deck Title": link.text.strip(),
                        "Link": "https://www.mtgtop8.com/" + link['href']
                    })
        return pd.DataFrame(events)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        # MTGTop8 lines contain quantity + card name
        lines = [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    # Regex to extract 'Fable of the Mirror-Breaker' from '4 Fable of the Mirror-Breaker'
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LOGIC ---

st.title("🧙‍♂️ MTG Metagame & Unique Tech Tracker")

# Session state to handle drill-down filtering
if "filter_archetype" not in st.session_state:
    st.session_state.filter_archetype = None

with st.sidebar:
    st.header("Settings")
    selected_format = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days_choice = st.radio("Timeframe", ["3 Days", "7 Days", "30 Days"], index=1)
    days_val = int(days_choice.split()[0])
    
    st.divider()
    if st.button("Reset Archetype Filter"):
        st.session_state.filter_archetype = None
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[selected_format]
col1, col2 = st.colum
