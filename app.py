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
    # Adding a referer to look more like a real user session
    s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
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
    # Path /full is generally more stable for scraping than the tile view
    url = f"https://www.mtggoldfish.com/metagame/{format_name}/full#paper"
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        
        # Method 1: Target Archetype Tiles (if on main page)
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({"Deck Name": name.text.strip(), "Meta %": meta.text.strip()})

        # Method 2: Table Search (Standard on /full page)
        if not decks:
            table = soup.select_one("table.metagame-table")
            if table:
                for row in table.select("tr"):
                    cols = row.select("td")
                    if len(cols) >= 4:
                        name_link = cols[1].find("a")
                        pct_text = cols[3].text.strip()
                        if name_link and "%" in pct_text:
                            decks.append({"Deck Name": name_link.text.strip(), "Meta %": pct_text})

        # Method 3: The "Greedy" Parser (Search for ANY link with percentage nearby)
        if not decks:
            for link in soup.find_all("a", href=re.compile(r'/archetype/')):
                parent_row = link.find_parent("tr")
                if parent_row:
                    row_text = parent_row.get_text()
                    pct_match = re.search(r'(\d+\.\d+%)', row_text)
                    if pct_match:
                        decks.append({"Deck Name": link.text.strip(), "Meta %": pct_match.group(1)})
        
        df = pd.DataFrame(decks).drop_duplicates(subset=["Deck Name"])
        # Remove navigation links that might be caught
        blacklist = ["Price", "Decks", "Metagame", "Standard", "Modern", "Pioneer", "Legacy", "Pauper"]
        df = df[~df["Deck Name"].isin(blacklist)]
        return df
    except Exception as e:
        st.error(f"Scraper error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(format_code, days_limit):
    scraper = get_scraper()
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
        lines = [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LAYOUT ---

st.title("🛡️ MTG Ultimate Meta Tool")

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

# --- COLUMN 1: GOLDFISH ---
with col1:
    st.subheader("Meta % Breakdown")
    meta_df = fetch_goldfish_meta(codes['gold'])
    
    if not meta_df.empty:
        st.info("Click a row to filter results.")
        selection = st.dataframe(
            meta_df, 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )
        
        if len(selection['selection']['rows']) > 0:
            idx = selection['selection']['rows'][0]
            st.session_state.selected_archetype = meta_df.iloc[idx]['Deck Name']
    else:
        st.warning("Goldfish is currently blocking or the table is missing. Try 'Force Refresh'.")

# --- COLUMN 2: TOP 8 ---
with col2:
    filter_txt = st.session_state.selected_archetype
    st.subheader(f"Recent {fmt} Results " + (f"[{filter_txt}]" if filter_txt else ""))
    
    t8_df = fetch_top8_events(codes['top8'], days)
    
    if not t8_df.empty:
        display_df = t8_df.copy()
        if filter_txt:
            # Get first word of archetype (e.g. "Grixis" from "Grixis Midrange")
            kw = filter_txt.split()[0]
            display_df = t8_df[t8_df['Deck Title'].str.contains(kw, case=False, na=False)]

        if display_df.empty:
            st.warning(f"No match for '{filter_txt}'. Showing all.")
            display_df = t8_df

        event_select = st.dataframe(
            display_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )

        if len(event_select['selection']['rows']) > 0:
            row_idx = event_select['selection']['rows'][0]
            deck_url = display_df.iloc[row_idx]['Link']
            
            # Drill down
            current_deck = fetch_decklist(deck_url)
            
            # Spicy Logic
            baseline_urls = display_df['Link'].iloc[0:5].tolist()
            others = [fetch_decklist(u) for u in baseline_urls if u != deck_url]
            all_common_cards = set()
            for d in others:
                for line in d:
                    all_common_cards.add(get_card_name(line))

            st.divider()
            st.subheader(f"Decklist: {display_df.iloc[row_idx]['Deck Title']}")
            
            # Show Decklist
            for line in current_deck:
                card_name = get_card_name(line)
                is_head = any(h in line for h in ["Sideboard", "Mainboard", "Deck"])
                if not is_head and card_name not in all_common_cards and len(all_common_cards) > 0:
                    st.markdown(f":blue[{line}]")
                else:
                    st.text(line)

            # Export
            st.divider()
            clean_txt = "\n".join(current_deck)
            c1, c2 = st.columns(2)
            with c1:
                st.copy_button("📋 Copy Decklist", clean_txt)
            with c2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_txt)}"
                st.link_button("↗️ Export to Moxfield", mox_url)
    else:
        st.info("No Top 8 results found.")
