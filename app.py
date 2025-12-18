import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

st.set_page_config(page_title="MTG Ultimate Meta Tool", layout="wide")

# --- SCRAPER ---
@st.cache_resource
def get_scraper():
    return cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})

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
        
        # Greedy search: Find every table row and look for a percentage
        for row in soup.find_all("tr"):
            text = row.get_text(separator=" ")
            pct_match = re.search(r'(\d+\.\d+%)', text)
            if pct_match:
                link = row.find("a")
                if link and len(link.text.strip()) > 2:
                    decks.append({
                        "Deck Name": link.text.strip(),
                        "Meta %": pct_match.group(1)
                    })
        
        # Cleanup: Remove duplicates and common non-deck items
        df = pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"])
        return df[~df["Deck Name"].str.contains("Price|Decks|Metagame", na=False)]
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
    # cp=2 = last 2 months
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        res = scraper.get(url, timeout=20)
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
        return pd.DataFrame(events)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        res = scraper.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')
        # Standard MTGTop8 card line structure
        lines = [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    # Regex to pull 'Sheoldred' out of '4 Sheoldred'
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LAYOUT ---

st.title("🛡️ MTG Meta & Spicy Tracker")

# Initialize selected archetype in session state if not there
if "selected_archetype" not in st.session_state:
    st.session_state.selected_archetype = None

with st.sidebar:
    st.header("Global Filters")
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Search Window", [3, 7, 30], index=1)
    
    st.divider()
    if st.button("Reset Archetype Filter"):
        st.session_state.selected_archetype = None
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt]
col1, col2 = st.columns([1, 2])

# --- COLUMN 1: METAGAME PERCENTAGES ---
with col1:
    st.subheader("Meta % Breakdown")
    meta_df = fetch_goldfish_meta(codes['gold'])
    
    if not meta_df.empty:
        st.info("Click a row to filter the Top 8 list below.")
        # Selection logic
        selection = st.dataframe(
            meta_df, 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )
        
        if len(selection['selection']['rows']) > 0:
            idx = selection['selection']['rows'][0]
            st.session_state.selected_archetype = meta_df.iloc[idx]['Deck Name']
    else:
        st.error("Could not find meta table. Trying fallback...")

# --- COLUMN 2: TOP 8 EVENTS ---
with col2:
    filter_txt = st.session_state.selected_archetype
    st.subheader(f"Recent {fmt} Results " + (f"[{filter_txt}]" if filter_txt else ""))
    
    t8_df = fetch_top8_events(codes['top8'], days)
    
    if not t8_df.empty:
        # Filter if a meta deck was clicked
        display_df = t8_df.copy()
        if filter_txt:
            # We use string matching because Goldfish and Top8 names differ slightly
            # e.g. "Grixis Midrange" vs "Grixis"
            keyword = filter_txt.split()[0] # Take first word
            display_df = t8_df[t8_df['Deck Title'].str.contains(keyword, case=False, na=False)]

        if display_df.empty:
            st.warning(f"No exact Top 8 matches for '{filter_txt}' in {days} days.")
            display_df = t8_df # Show all if filter fails

        event_select = st.dataframe(
            display_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )

        # --- DECKLIST DRILL-DOWN ---
        if len(event_select['selection']['rows']) > 0:
            row_idx = event_select['selection']['rows'][0]
            deck_url = display_df.iloc[row_idx]['Link']
            
            # Fetch data
            raw_deck = fetch_decklist(deck_url)
            
            # SPICY LOGIC: Compare against 5 other decks of same archetype
            baseline_urls = display_df['Link'].iloc[0:6].tolist()
            other_decks = [fetch_decklist(u) for u in baseline_urls if u != deck_url]
            
            all_known_cards = set()
            for d in other_decks:
                for line in d:
                    all_known_cards.add(get_card_name(line))

            st.divider()
            st.subheader(f"Decklist: {display_df.iloc[row_idx]['Deck Title']}")
            st.caption("Blue cards = Unique to this list vs others in this table.")

            # Display with spicy highlighting
            for line in raw_deck:
                name = get_card_name(line)
                is_header = any(h in line for h in ["Sideboard", "Mainboard", "Deck"])
                
                if not is_header and name not in all_known_cards:
                    st.markdown(f":blue[{line}]")
                else:
                    st.text(line)

            # EXPORT
            st.divider()
            clean_txt = "\n".join(raw_deck)
            c1, c2 = st.columns(2)
            with c1:
                st.copy_button("📋 Copy Decklist", clean_txt)
            with c2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_txt)}"
                st.link_button("↗️ Export to Moxfield", mox_url)
    else:
        st.info("No event results found for this timeframe.")
