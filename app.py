import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import urllib.parse
import time

# --- INITIALIZE SCRAPER WITH BROWSER EMULATION ---
# This mimics a real user to help bypass 2025 Cloudflare blocks
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

st.set_page_config(page_title="MTG Meta Analyzer 2025", layout="wide")

# --- DATA MAPPING ---
FORMAT_MAP = {"Standard": "ST", "Modern": "MO", "Pioneer": "PI", "Legacy": "LE", "Pauper": "PAU"}
GOLDFISH_MAP = {"Standard": "standard", "Modern": "modern", "Pioneer": "pioneer", "Legacy": "legacy", "Pauper": "pauper"}

# --- SCRAPING FUNCTIONS ---

@st.cache_data(ttl="1d")
def fetch_metagame(format_name):
    url = f"https://www.mtggoldfish.com/metagame/{format_name}"
    try:
        response = scraper.get(url, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame(), f"Error {response.status_code}: Cloudflare Blocked"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Updated 2025 Selectors for Goldfish
        for tile in soup.select(".archetype-tile"):
            name_tag = tile.select_one(".archetype-tile-description .deck-price-paper a")
            perc_tag = tile.select_one(".metagame-percentage-column")
            
            if name_tag and perc_tag:
                decks.append({
                    "Deck": name_tag.text.strip(),
                    "Meta %": perc_tag.text.strip()
                })
        
        if not decks: # Fallback for different layout
            for row in soup.select("table.metagame-table tr")[1:]:
                cols = row.find_all("td")
                if len(cols) > 2:
                    decks.append({"Deck": cols[1].text.strip(), "Meta %": cols[3].text.strip()})

        return pd.DataFrame(decks), "Success"
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl="1d")
def fetch_top8_events(format_code):
    url = f"https://www.mtgtop8.com/format?f={format_code}"
    try:
        response = scraper.get(url, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame(), f"Error {response.status_code}"

        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        # MTGTop8 uses hover_tr for result rows
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 4:
                # Column mapping: 1=Title/Link, 2=Player, 3=Place, 4=Date
                link_tag = cols[1].find('a')
                if link_tag:
                    events.append({
                        "Date": cols[4].text.strip(),
                        "Place": cols[2].text.strip(),
                        "Title": link_tag.text.strip(),
                        "Link": "https://www.mtgtop8.com/" + link_tag['href']
                    })
        return pd.DataFrame(events), "Success"
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl="1d")
def get_deck_details(url):
    response = scraper.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    decklist = []
    # Cards are usually in divs with class 'deck_line'
    for line in soup.select(".deck_line"):
        # Remove common non-deck text
        text = line.text.strip()
        if text and not text.startswith("Sideboard"):
            decklist.append(text)
    return decklist

# --- UI LAYOUT ---
st.title("🎴 MTG Daily Meta & Spicy Tech")

with st.sidebar:
    fmt = st.selectbox("Select Format", list(FORMAT_MAP.keys()))
    st.write("---")
    if st.button("Clear Cache / Force Refresh"):
        st.cache_data.clear()
        st.rerun()

col1, col2 = st.columns([1, 2])

# META BREAKDOWN
with col1:
    st.subheader("Metagame Share")
    df_meta, status_m = fetch_metagame(GOLDFISH_MAP[fmt])
    if not df_meta.empty:
        st.dataframe(df_meta, hide_index=True, use_container_width=True)
    else:
        st.error(f"Goldfish Error: {status_m}")
        st.info("Try refreshing or checking the site manually.")

# RECENT TOP 8s
with col2:
    st.subheader(f"Recent {fmt} Top 8s")
    df_events, status_e = fetch_top8_events(FORMAT_MAP[fmt])
    
    if not df_events.empty:
        event_selection = st.dataframe(
            df_events[['Date', 'Place', 'Title']], 
            on_select="rerun", 
            selection_mode="single-row",
            use_container_width=True,
            hide_index=True
        )

        if len(event_selection['selection']['rows']) > 0:
            idx = event_selection['selection']['rows'][0]
            url = df_events.iloc[idx]['Link']
            
            raw_deck = get_deck_details(url)
            
            st.divider()
            st.subheader(f"Decklist: {df_events.iloc[idx]['Title']}")
            
            # Display Decklist
            clean_list = "\n".join(raw_deck)
            st.text_area("Full Decklist", clean_list, height=300)
            
            c1, c2 = st.columns(2)
            with c1:
                st.copy_button("📋 Copy for Arena/MTGO", clean_list)
            with c2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_list)}"
                st.link_button("↗️ Import to Moxfield", mox_url)
    else:
        st.error(f"MTGTop8 Error: {status_e}")

# --- DIAGNOSTICS SECTION ---
with st.expander("🛠️ Debugging & Diagnostics"):
    st.write("If the tables are empty, check the status below:")
    st.write(f"**MTGGoldfish URL:** https://www.mtggoldfish.com/metagame/{GOLDFISH_MAP[fmt]}")
    st.write(f"**MTGTop8 URL:** https://www.mtgtop8.com/format?f={FORMAT_MAP[fmt]}")
    st.write(f"**Current Scraper Status:** {'Active' if scraper else 'Inactive'}")
