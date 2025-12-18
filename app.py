import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

st.set_page_config(page_title="MTG Ultimate Meta Tool", layout="wide")

# --- SCRAPER ---
def get_scraper():
    # Mimic a real Chrome browser session
    s = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
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
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code == 403:
            return pd.DataFrame(), "BLOCKED: Cloudflare denied access. Run this locally!"
        
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        
        # 2025 Tile Selector
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            # Goldfish now often displays meta % as text inside a specific div or span
            meta_text = tile.get_text()
            pct_match = re.search(r'(\d+\.\d+%)', meta_text)
            
            if name and pct_match:
                decks.append({
                    "Deck Name": name.text.strip(),
                    "Meta %": pct_match.group(1)
                })
        
        if not decks:
            return pd.DataFrame(), "EMPTY: Scraper reached the site but found no decks. Layout might have changed."
            
        return pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"]), "Success"
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
    # cp=1 is last 2 weeks, cp=2 is last 2 months
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code == 403:
            return pd.DataFrame(), "BLOCKED"
            
        soup = BeautifulSoup(res.text, 'html.parser')
        events = []
        
        rows = soup.select("tr.hover_tr")
        for row in rows:
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
        return pd.DataFrame(events), "Success"
    except:
        return pd.DataFrame(), "Error"

@st.cache_data(ttl=86400)
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url)
        return [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
    except:
        return []

def get_card_name(line):
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LAYOUT ---

st.title("🛡️ MTG Meta & Spicy Tracker")

with st.sidebar:
    st.header("Global Filters")
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Search Window", [3, 7, 30], index=1)
    
    st.divider()
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt]
col1, col2 = st.columns([1, 2])

# --- COLUMN 1: GOLDFISH ---
with col1:
    st.subheader("Meta % Breakdown")
    meta_df, status = fetch_goldfish_meta(codes['gold'])
    
    if status == "Success":
        selection = st.dataframe(
            meta_df, on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )
        if len(selection['selection']['rows']) > 0:
            st.session_state.filter_archetype = meta_df.iloc[selection['selection']['rows'][0]]['Deck Name']
    else:
        st.error(f"Status: {status}")

# --- COLUMN 2: TOP 8 ---
with col2:
    st.subheader(f"Recent {fmt} Results")
    t8_df, t_status = fetch_top8_events(codes['top8'], days)
    
    if t_status == "Success" and not t8_df.empty:
        # Filter logic
        display_df = t8_df
        if "filter_archetype" in st.session_state and st.session_state.filter_archetype:
            kw = st.session_state.filter_archetype.split()[0]
            display_df = t8_df[t8_df['Deck Title'].str.contains(kw, case=False, na=False)]

        event_select = st.dataframe(
            display_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )

        if len(event_select['selection']['rows']) > 0:
            deck_url = display_df.iloc[event_select['selection']['rows'][0]]['Link']
            # (Rest of decklist logic here...)
            st.write(f"Deck link selected: {deck_url}")
    else:
        st.info("No recent Top 8 data available.")
