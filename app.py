import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

st.set_page_config(page_title="MTG Meta Drill-Down Tool", layout="wide")

# --- SCRAPER ENGINE ---
def get_scraper():
    s = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.mtgtop8.com/index",
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
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta_text = tile.get_text()
            pct_match = re.search(r'(\d+\.\d+%)', meta_text)
            if name and pct_match:
                decks.append({"Deck Name": name.text.strip(), "Meta %": pct_match.group(1)})
        return pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"])
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, search_query="", days_limit=30):
    scraper = get_scraper()
    # If search_query exists, we use the MTGTop8 search page
    if search_query:
        # We clean the query (e.g. "Grixis Midrange" -> "Grixis")
        q = search_query.split()[0]
        url = f"https://www.mtgtop8.com/search?format={format_code}&deck={q}"
    else:
        url = f"https://www.mtgtop8.com/format?f={format_code}&cp=1"
    
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        events = []
        
        # MTGTop8 uses 'hover_tr' for deck rows
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                # Column 1: Title/Link, Column 2: Player, Column 3: Result, Column 4: Event, Column 5: Date
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
def fetch_full_decklist(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        # MTGTop8 specific card container classes
        lines = []
        for div in soup.select(".deck_line"):
            lines.append(div.text.strip())
        return lines
    except:
        return []

# --- UI LOGIC ---

st.title("🛡️ MTG Meta Drill-Down Tool")

# Sidebar
with st.sidebar:
    st.header("Global Settings")
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Search Window", [3, 7, 30], index=2)
    st.divider()
    if st.button("🔄 Clear Cache & Restart"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt]
col1, col2 = st.columns([1, 2])

# --- COLUMN 1: GOLDFISH META BREAKDOWN ---
with col1:
    st.subheader("1. Select an Archetype")
    meta_df = fetch_goldfish_meta(codes['gold'])
    
    if not meta_df.empty:
        # The key is to capture the selection in a variable
        meta_selection = st.dataframe(
            meta_df, 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True,
            key="meta_table"
        )
        
        selected_archetype = ""
        # Check if a row is selected
        if meta_selection.selection.rows:
            idx = meta_selection.selection.rows[0]
            selected_archetype = meta_df.iloc[idx]['Deck Name']
            st.success(f"Filtering for: {selected_archetype}")
    else:
        st.warning("Waiting for Goldfish data...")

# --- COLUMN 2: TOP 8 SEARCH & DRILL DOWN ---
with col2:
    st.subheader("2. Recent Winning Lists")
    
    # We pass the selected archetype into the search
    search_query = selected_archetype if 'selected_archetype' in locals() and selected_archetype else ""
    t8_df = fetch_top8_events(codes['top8'], search_query=search_query, days_limit=days)
    
    if not t8_df.empty:
        # Event selection table
        event_selection = st.dataframe(
            t8_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True, 
            use_container_width=True,
            key="event_table"
        )

        # --- DRILL DOWN: FULL DECKLIST ---
        if event_selection.selection.rows:
            row_idx = event_selection.selection.rows[0]
            deck_url = t8_df.iloc[row_idx]['Link']
            
            # Fetch and process decklist
            full_deck = fetch_full_decklist(deck_url)
            
            st.divider()
            st.subheader(f"3. Decklist: {t8_df.iloc[row_idx]['Deck Title']}")
            
            # Display & Export
            clean_text = "\n".join(full_deck)
            st.text_area("Deck Cards", clean_text, height=300)
            
            c1, c2 = st.columns(2)
            with c1:
                st.copy_button("📋 Copy to Clipboard", clean_text)
            with c2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_text)}"
                st.link_button("↗️ Export to Moxfield", mox_url)
    else:
        st.info("No matches found on MTGTop8 for this filter/timeframe.")
