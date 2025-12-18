import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="MTG Meta Analyzer", layout="wide")

FORMAT_MAP = {
    "Standard": {"gold": "standard", "top8": "ST"},
    "Modern": {"gold": "modern", "top8": "MO"},
    "Pioneer": {"gold": "pioneer", "top8": "PI"},
    "Legacy": {"gold": "legacy", "top8": "LE"},
    "Pauper": {"gold": "pauper", "top8": "PAU"}
}

def get_scraper():
    return cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})

def clean_card_name(line):
    return re.sub(r'^\d+\s+', '', line).strip()

# --- DATA FETCHING ---

@st.cache_data(ttl=86400)
def fetch_goldfish_meta(fmt_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{fmt_name}#paper"
    try:
        resp = scraper.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
        decks = []
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({"Deck Name": name.text.strip(), "Meta %": meta.text.strip()})
        if not decks:
            table = soup.find("table", class_=re.compile(r'metagame-table'))
            if table:
                for row in table.select("tr")[1:]:
                    cols = row.select("td")
                    if len(cols) >= 4:
                        decks.append({"Deck Name": cols[1].text.strip(), "Meta %": cols[3].text.strip()})
        return pd.DataFrame(decks)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_top8_events(fmt_code, days_limit):
    scraper = get_scraper()
    url = f"https://www.mtgtop8.com/format?f={fmt_code}&cp=2"
    try:
        resp = scraper.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
        events = []
        for row in soup.select("tr.hover_tr"):
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
                    ev_date = datetime.strptime(date_str, "%d/%m/%y")
                    if (datetime.now() - ev_date).days > days_limit: continue
                except: continue
                link = cols[1].find("a")
                if link:
                    events.append({
                        "Date": date_str, "Place": cols[2].text.strip(),
                        "Deck Title": link.text.strip(), "Link": "https://www.mtgtop8.com/" + link['href']
                    })
        return pd.DataFrame(events)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        resp = scraper.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        return [l.text.strip() for l in soup.select(".deck_line") if l.text.strip()]
    except:
        return []

# --- APP UI ---

st.title("🧙‍♂️ MTG Metagame & Spicy Tech Tracker")

if "filter_archetype" not in st.session_state:
    st.session_state.filter_archetype = None

with st.sidebar:
    st.header("Settings")
    fmt_choice = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days_choice = st.radio("Timeframe", ["3 Days", "7 Days", "30 Days"], index=1)
    days_val = int(days_choice.split()[0])
    if st.button("Reset Archetype Filter"):
        st.session_state.filter_archetype = None
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt_choice]
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Meta Breakdown")
    meta_df = fetch_goldfish_meta(codes['gold'])
    if not meta_df.empty:
        st.info("Click a row to filter events.")
        m_sel = st.dataframe(meta_df, on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)
        if len(m_sel['selection']['rows']) > 0:
            st.session_state.filter_archetype = meta_df.iloc[m_sel['selection']['rows'][0]]['Deck Name']
    else:
        st.warning("Metagame data unavailable.")

with col2:
    cur_filt = st.session_state.filter_archetype
    st.subheader(f"Recent Results" + (f" ({cur_filt})" if cur_filt else ""))
    t8_df = fetch_top8_events(codes['top8'], days_val)
    if not t8_df.empty:
        disp_df = t8_df.copy()
        if cur_filt:
            keyword = cur_filt.split()[0]
            disp_df = t8_df[t8_df['Deck Title'].str.contains(keyword, case=False, na=False)]
        
        e_sel = st.dataframe(disp_df[['Date', 'Place', 'Deck Title']], on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)

        if len(e_sel['selection']['rows']) > 0:
            row_idx = e_sel['selection']['rows'][0]
            deck_url = disp_df.iloc[row_idx]['Link']
            
            target_list = fetch_decklist(deck_url)
            baseline_urls = disp_df['Link'].iloc[0:6].tolist()
            other_decks = [fetch_decklist(u) for u in baseline_urls if u != deck_url]
            
            common_cards = set()
            for d in other_decks:
                for l in d: common_cards.add(clean_card_name(l))

            st.divider()
            st.subheader(f"Decklist: {disp_df.iloc[row_idx]['Deck Title']}")
