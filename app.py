import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re
import json

st.set_page_config(page_title="MTG Ultimate Meta Tool 2025", layout="wide")

# --- SCRAPER ENGINE ---
@st.cache_resource
def get_scraper():
    s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/"
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
    # Using the /full URL often contains cleaner table data
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        
        # METHOD 1: Look for the specific 'archetype-tile' pattern
        for tile in soup.select(".archetype-tile"):
            name_tag = tile.select_one(".deck-price-paper a")
            meta_tag = tile.select_one(".metagame-percentage-column")
            if name_tag and meta_tag:
                decks.append({
                    "Deck Name": name_tag.text.strip(),
                    "Meta %": meta_tag.text.strip()
                })

        # METHOD 2: Generic Table Search
        if not decks:
            table = soup.find("table", class_=re.compile(r'metagame-table|table-condensed'))
            if table:
                for row in table.select("tr"):
                    cols = row.select("td")
                    if len(cols) >= 4:
                        link = cols[1].find("a")
                        pct = cols[3].text.strip()
                        if link and "%" in pct:
                            decks.append({"Deck Name": link.text.strip(), "Meta %": pct})

        # Final check: If decks list is empty, return empty DF to avoid KeyError
        if not decks:
            return pd.DataFrame()
            
        df = pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"])
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
    # Get enough data to cover the timeframe
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        events = []
        
        # MTGTop8 structure is stable but uses specific row classes
        for row in soup.select("tr.hover_tr"):
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
                    ev_date = datetime.strptime(date_str, "%d/%m/%y")
                    if (datetime.now() - ev_date).days > days_limit:
                        continue
                except: continue

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
        res = scraper.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')
        # MTGTop8 card lines
        lines = [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    # Extracts 'Grief' from '4 Grief'
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LAYOUT ---

st.title("🛡️ MTG Ultimate Meta Tool (Dec 2025)")

if "selected_archetype" not in st.session_state:
    st.session_state.selected_archetype = None

with st.sidebar:
    st.header("Global Filters")
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days_choice = st.radio("Search Window", ["3 Days", "7 Days", "30 Days"], index=1)
    days = int(days_choice.split()[0])
    
    st.divider()
    if st.button("Reset Archetype Filter"):
        st.session_state.selected_archetype = None
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt]
col1, col2 = st.columns([1, 2])

# --- COLUMN 1: GOLDFISH META ---
with col1:
    st.subheader("Meta % Breakdown")
    meta_df = fetch_goldfish_meta(codes['gold'])
    
    if not meta_df.empty:
        st.info("Click a row to filter results.")
        selection = st.dataframe(
            meta_df, 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True
        )
        
        if selection and selection.get('selection') and len(selection['selection']['rows']) > 0:
            idx = selection['selection']['rows'][0]
            st.session_state.selected_archetype = meta_df.iloc[idx]['Deck Name']
    else:
        st.warning("Goldfish meta currently unavailable. Check your internet or 'Force Refresh'.")

# --- COLUMN 2: TOP 8 RESULTS ---
with col2:
    filter_txt = st.session_state.selected_archetype
    st.subhea
