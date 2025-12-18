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
    "Vintage": {"gold": "vintage", "top8": "VI"}
}

# --- SCRAPING FUNCTIONS ---

@st.cache_data(ttl=86400)
def get_goldfish_meta(format_name):
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Method 1: Archetype tiles (Modern layout)
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name_tag = tile.select_one(".deck-price-paper a")
            meta_tag = tile.select_one(".metagame-percentage-column")
            if name_tag and meta_tag:
                decks.append({
                    "Deck Name": name_tag.text.strip(),
                    "Meta %": meta_tag.text.strip()
                })
        
        # Method 2: Table fallback (Legacy layout)
        if not decks:
            table = soup.find('table', class_='metagame-table')
            if table:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        decks.append({
                            "Deck Name": cols[1].text.strip(),
                            "Meta %": cols[3].text.strip()
                        })
        return pd.DataFrame(decks)
    except Exception as e:
        st.sidebar.error(f"Goldfish Error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_top8_events(format_code, days_limit):
    # Fetching enough events to filter (cp=2 covers 2 months)
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
                    ev_date = datetime.strptime(date_str, "%d/%m/%y")
                    delta = datetime.now() - ev_date
                    if delta.days > days_limit:
                        continue
                except Exception:
                    # If date parsing fails, skip this row
                    continue

                link_tag = cols[1].find("a")
                if link_tag:
                    events.append({
                        "Date": date_str,
                        "Place": cols[2].text.strip(),
                        "Deck Title": link_tag.text.strip(),
                        "Link": "https://www.mtgtop8.com/" + link_tag['href']
                    })
        return pd.DataFrame(events)
    except Exception as e:
        st.sidebar.error(f"Top8 Error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_decklist(url):
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        # MTGTop8 specific deck line class
        lines = [line.text.strip() for line in soup.select(".deck_line") if line.text.strip()]
        return lines
    except Exception:
        return []

def clean_card_name(line):
    # Remove leading quantity (e.g., '4 Lightning Bolt' -> 'Lightning Bolt')
    return re.sub(r'^\d+\s+', '', line).strip()

# --- APP UI ---

st.title("🛡️ MTG Meta Scraper & Spicy Tech")

with st.sidebar:
    st.header("Settings")
    fmt_choice = st.selectbox("Format", list(FORMAT_MAP.keys()))
    time_choice = st.radio("Timeframe", ["3 Days", "7 Days", "30 Days"], index=1)
    
    # Convert string choice to integer
    days_limit = int(time_choice.split()[0])
    
    st.divider()
    if st.button("🔄 Clear Cache & Refresh"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt_choice]
col1, col2 = st.columns([1, 2])

# --- LEFT: GOLDFISH BREAKDOWN ---
with col1:
    st.subheader("Meta % (Goldfish)")
    meta_df = get_goldfish_meta(codes['gold'])
    if not meta_df.empty:
        st.dataframe(meta_df, hide_index=True, use_container_width=True)
    else:
        st.info("No meta data currently available.")

# --- RIGHT: TOP 8 EVENTS ---
with col2:
    st.subheader(f"Recent {fmt_choice} Top 8s")
    top8_df = get_top8_events(codes['top8'], days_limit)
    
    if not top8_df.empty:
        # User clicks a row in the table
        event_selection = st.dataframe(
            top8_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True
        )

        # --- DECK DISPLAY LOGIC ---
        if len(event_selection['selection']['rows']) > 0:
            idx = event_selection['selection']['rows'][0]
            deck_url = top8_df.iloc[idx]['Link']
            deck_title = top8_df.iloc[idx]['Deck Title']
            
            # Fetch data for the selected deck
            current_decklist = get_decklist(deck_url)
            
            # SPICY LOGIC: Fetch other decks for comparis
