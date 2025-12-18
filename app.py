import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

st.set_page_config(page_title="MTG Meta Analyzer 2025", layout="wide")

# --- SCRAPER SETUP ---
def get_scraper():
    # Using a specific browser fingerprint to look more 'human'
    return cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
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

# --- ROBUST SCRAPING LOGIC ---

@st.cache_data(ttl=86400)
def fetch_goldfish_data(format_name):
    scraper = get_scraper()
    # Using the /full URL often bypasses 'tile' layout issues
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        response = scraper.get(url, timeout=20)
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        decks = []

        # 1. Search for Archetype Tiles (Standard Layout)
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({"Deck Name": name.text.strip(), "Meta %": meta.text.strip()})

        # 2. Search for ANY Table (Fallback Layout)
        if not decks:
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cols = row.find_all("td")
                    # Metagame tables usually have the name in col 1 or 2 and % in col 3 or 4
                    if len(cols) >= 3:
                        text_content = row.text
                        if "%" in text_content:
                            # Try to find the deck name (usually the first link)
                            link = row.find("a")
                            pct = re.search(r'\d+\.\d+%', text_content)
                            if link and pct:
                                decks.append({"Deck Name": link.text.strip(), "Meta %": pct.group(0)})

        df = pd.DataFrame(decks).drop_duplicates()
        return df, "Success", html[:1000] # Return start of HTML for debugging
    except Exception as e:
        return pd.DataFrame(), str(e), ""

@st.cache_data(ttl=86400)
def fetch_top8_data(format_code, days_limit):
    scraper = get_scraper()
    # cp=2 pulls last 2 months of data
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []

        # MTGTop8 result rows
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip() # Format: DD/MM/YY
                try:
                    # Current year is 2025, strptime handles %y (2-digit year) correctly
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
        
        return pd.DataFrame(events), "Success"
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=86400)
def fetch_single_deck(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        # MTGTop8 specific card container
        lines = [line.text.strip() for line in soup.select(".deck_line") if line.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    # Strip quantity: '4 Fable of the Mirror-Breaker' -> 'Fable of the Mirror-Breaker'
    return re.sub(r'^\d+\s+', '', line).strip()

# --- STREAMLIT UI ---

st.title("🧙‍♂️ MTG Metagame & Unique Tech Tracker")

with st.sidebar:
    st.header("App Controls")
    selected_fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    time_window = st.radio("Timeframe", [3, 7, 30], index=1)
    
    st.divider()
    show_debug = st.checkbox("Debug Mode")
    if st.button("Clear Cache & Scrape Again"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[selected_fmt]
col1, col2 = st.columns([1, 2])

# --- GOLDFISH: METAGAME BREAKDOWN ---
with col1:
    st.subheader("Meta Breakdown")
    gold_df, g_status, g_html = fetch_goldfish_data(codes['gold'])
    
    if show_debug:
        st.text(f"Goldfish Status: {g_status}")
        with st.expander("HTML Snippet"):
            st.code(g_html)

    if not gold_df.empty:
        st.dataframe(gold_df, hide_index=True, use_container_width=True)
    else:
        st.warning("Could not parse Goldfish table. The site may be blocking cloud traffic.")

# --- TOP8: RECENT RESULTS ---
with col2:
    st.subheader(f"Recent {selected_fmt} Results")
    t8_df, t_status = fetch_top8_data(codes['top8'], time_window)

    if not t8_df.empty:
        selection = st.dataframe(
            t8_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )

        if len(selection['selection']['rows']) > 0:
            row_idx = selection['selection']['rows'][0]
            target_url = t8_df.iloc[row_idx]['Link']
            
            # Fetch target deck and some baseline decks for comparison
            target_list = fetch_single_deck(target_url)
            baseline_urls = t8_df['Link'].iloc[0:10].tolist()
            baselines = [fetch_single_deck(u) for u in baseline_urls if u != target_url]
            
            # Identify cards that don't appear in the other top decks
            other_names = set()
            for d in baselines:
                for line in d:
                    other_names.add(get_card_name(line))

            st.divider()
            st.subheader(f"Decklist: {t8_df.iloc[row_idx]['Deck Title']}")
            st.info("💡 Cards in :blue[blue] are 'Spicy' (Unique to this list compared to others).")

            for line in target_list:
                c_name = get_
