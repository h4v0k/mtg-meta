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
    # Uses a Chrome browser profile to help bypass security blocks
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

# --- DATA FETCHING FUNCTIONS ---

@st.cache_data(ttl=86400)
def fetch_goldfish_meta(format_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Look for the archetype tiles used on MTGGoldfish
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({
                    "Deck Name": name.text.strip(),
                    "Meta %": meta.text.strip()
                })
        
        # Fallback to table search if tiles are not found
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
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
    # cp=2 pulls data from the last 2 months for filtering
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
                except Exception:
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
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        # MTGTop8 card lines typically contain quantity and name
        lines = [line.text.strip() for line in soup.select(".deck_line") if line.text.strip()]
        return lines
    except Exception:
        return []

def get_card_name(line):
    # Extracts the card name by stripping leading numbers (e.g., '4 Grief' -> 'Grief')
    return re.sub(r'^\d+\s+', '', line).strip()

# --- APP INTERFACE ---

st.title("🧙‍♂️ MTG Metagame & Spicy Tech Tracker")

# Use session state to manage filtering across reruns
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
main_col1, main_col2 = st.columns([1, 2])

# --- COLUMN 1: METAGAME BREAKDOWN ---
with main_col1:
    st.subheader("Meta Breakdown")
    meta_df = fetch_goldfish_meta(codes['gold'])
    
    if not meta_df.empty:
        st.info("Click a row to filter the Top 8 results list.")
        # Meta selection table
        meta_select = st.dataframe(
            meta_df, 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True
        )
        
        if len(meta_select['selection']['rows']) > 0:
            idx = meta_select['selection']['rows'][0]
            st.session_state.filter_archetype = meta_df.iloc[idx]['Deck Name']
    else:
        st.warning("Could not retrieve metagame data from MTGGoldfish.")

# --- COLUMN 2: TOP 8 EVENTS ---
with main_col2:
    current_filter = st.session_state.filter_archetype
    st.subheader(f"Recent {selected_format} Results" + (f" ({current_filter})" if current_filter else ""))
    
    t8_df = fetch_top8_events(codes['top8'], days_val)
    
    if not t8_df.empty:
        display_df = t8_df.copy()
        # Filter Top 8 results if an archetype was selected in Column 1
        if current_filter:
            keyword = current_filter.split()[0]
            display_df = t8_df[t8_df['Deck Title'].str.contains(keyword, case=False, na=False)]
        
        if display_df.empty and current_filter:
            st.warning(f"No results for '{current_filter}'. Showing all entries.")
            display_df = t8_df

        event_select = st.dataframe(
            display_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True
        )

        # --- DECKLIST DRILL-DOWN ---
        if len(event_select['select
