import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

# Initialize Scraper
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})

st.set_page_config(page_title="MTG Meta Analyzer", layout="wide")

# --- MAPPINGS ---
# MTGTop8 uses cp=1 for last 2 weeks, cp=2 for last 2 months. 
# We will pull cp=1 and then filter manually for 3/7/30 days.
FORMAT_MAP = {"Standard": "ST", "Modern": "MO", "Pioneer": "PI", "Legacy": "LE", "Pauper": "PAU"}
GOLDFISH_MAP = {"Standard": "standard", "Modern": "modern", "Pioneer": "pioneer", "Legacy": "legacy", "Pauper": "pauper"}

# --- HELPER: DATE PARSING ---
def is_within_days(date_str, days_limit):
    try:
        # MTGTop8 format is usually DD/MM/YY
        event_date = datetime.strptime(date_str, "%d/%m/%y")
        limit_date = datetime.now() - timedelta(days=days_limit)
        return event_date >= limit_date
    except:
        return True # If date fails, keep the record just in case

# --- SCRAPING FUNCTIONS ---

@st.cache_data(ttl="1d")
def fetch_goldfish(format_name):
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        resp = scraper.get(url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        decks = []
        
        # Look for the main metagame table or archetype tiles
        # Method 1: Archetype tiles
        tiles = soup.find_all('div', class_='archetype-tile')
        for tile in tiles:
            name = tile.find('span', class_='deck-price-paper')
            meta = tile.find('div', class_='metagame-percentage-column')
            if name and meta:
                decks.append({"Deck": name.text.strip(), "Meta %": meta.text.strip()})
        
        # Method 2: Fallback to table search
        if not decks:
            table = soup.find('table', class_='metagame-table')
            if table:
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) > 3:
                        decks.append({"Deck": cols[1].text.strip(), "Meta %": cols[3].text.strip()})
        
        return pd.DataFrame(decks)
    except:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def fetch_top8(format_code, days_limit):
    # Fetching with cp=1 (last 2 weeks) to cover 3 and 7 day requests
    # If 30 days, we use cp=2 (last 2 months)
    cp = "2" if days_limit > 14 else "1"
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp={cp}"
    
    try:
        resp = scraper.get(url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        events = []
        
        # Targeted search for result rows
        rows = soup.find_all('tr', class_='hover_tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 5: # Ensure it's a data row
                date_str = cols[4].text.strip()
                if is_within_days(date_str, days_limit):
                    link = cols[1].find('a')
                    events.append({
                        "Date": date_str,
                        "Place": cols[2].text.strip(),
                        "Title": link.text.strip() if link else "Unknown",
                        "Link": "https://www.mtgtop8.com/" + link['href'] if link else ""
                    })
        return pd.DataFrame(events)
    except Exception as e:
        st.error(f"Top8 Scrape Failed: {e}")
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def get_deck_details(url):
    try:
        resp = scraper.get(url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # MTGTop8 decklists are often in the 'deck_line' class or table cells
        lines = soup.find_all('div', class_='deck_line')
        deck = [line.text.strip() for line in lines if line.text.strip()]
        return deck
    except:
        return []

# --- UNIQUE CARD LOGIC ---
def process_spicy(current_deck, other_decks):
    # Extract only card names (remove numbers)
    def clean_name(line):
        parts = line.split(' ', 1)
        return parts[1] if len(parts) > 1 else line

    current_names = [clean_name(c) for c in current_deck]
    all_other_names = [clean_name(line) for d in other_decks for line in d]
    
    display_list = []
    for line in current_deck:
        name = clean_name(line)
        # If the card appears 0 or 1 times in the other 5 decks, it's spicy
        if all_other_names.count(name) < 1:
            display_list.append(f":blue[{line}]")
        else:
            display_list.append(line)
    return display_list

# --- UI ---
st.title("🛡️ MTG Meta & Spicy Tracker")

with st.sidebar:
    selected_format = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Timeframe", [3, 7, 30], index=1)
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

col1, col2 = st.columns([1, 2])

# LEFT: GOLDFISH META
with col1:
    st.subheader("Meta % (Goldfish)")
    meta_df = fetch_goldfish(GOLDFISH_MAP[selected_format])
    if not meta_df.empty:
        st.dataframe(meta_df, hide_index=True, use_container_width=True)
    else:
        st.warning("Could not find meta table. Site layout may have changed.")

# RIGHT: TOP 8 EVENTS
with col2:
    st.subheader(f"Top 8 Results (Last {days} Days)")
    events_df = fetch_top8(FORMAT_MAP[selected_format], days)
    
    if not events_df.empty:
        selection = st.dataframe(
            events_df[['Date', 'Place', 'Title']], 
            on_select="rerun", selection_mode="single-row",
            use_container_width=True, hide_index=True
        )

        if len(selection['selection']['rows']) > 0:
            idx = selection['selection']['rows'][0]
            deck_url = events_df.iloc[idx]['Link']
            
            # Fetch this deck
            this_deck = get_deck_details(deck_url)
            
            # Fetch a few others for "Spicy" comparison
            baseline_urls = events_df['Link'].iloc[0:6].tolist()
            other_decks = [get_deck_details(u) for u in baseline_urls if u != deck_url]
            
            # Process spicy (Blue)
            spicy_display = process_spicy(this_deck, other_decks)
            
            st.divider()
            st.subheader(f"Decklist: {events_df.iloc[idx]['Title']}")
            st.caption("Blue text indicates a 'Spicy' card (rare in other recent top decks).")
            
            # Show spicy list
            for line in spicy_display:
                st.markdown(line)
            
            # Action Buttons
            raw_text = "\n".join(this_deck)
            st.divider()
            b1, b2 = st.colu
