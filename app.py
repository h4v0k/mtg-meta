import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re

# --- PAGE CONFIG ---
st.set_page_config(page_title="MTG Meta & Spicy Tracker", layout="wide")

# Function to create a fresh scraper with a rotating User-Agent
def get_scraper():
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
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

# --- SCRAPING FUNCTIONS ---

@st.cache_data(ttl=86400)
def fetch_goldfish(format_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        response = scraper.get(url, timeout=20)
        if "Cloudflare" in response.text and response.status_code == 403:
            return pd.DataFrame(), "Blocked by Cloudflare"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        
        # Method 1: Archetype tiles
        tiles = soup.select(".archetype-tile")
        for tile in tiles:
            name = tile.select_one(".deck-price-paper a")
            meta = tile.select_one(".metagame-percentage-column")
            if name and meta:
                decks.append({"Deck Name": name.text.strip(), "Meta %": meta.text.strip()})
        
        # Method 2: Fallback to any table with a % sign
        if not decks:
            tables = soup.find_all("table")
            for table in tables:
                for row in table.find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 3 and "%" in cols[-1].text:
                        decks.append({
                            "Deck Name": cols[1].text.strip(),
                            "Meta %": cols[-1].text.strip()
                        })
        
        df = pd.DataFrame(decks).drop_duplicates()
        return df, "Success"
    except Exception as e:
        return pd.DataFrame(), str(e)

@st.cache_data(ttl=86400)
def fetch_top8(format_code, days_limit):
    scraper = get_scraper()
    # cp=1 is last 2 weeks, cp=2 is last 2 months
    url = f"https://www.mtgtop8.com/format?f={format_code}&cp=2"
    try:
        response = scraper.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')
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
def fetch_decklist(url):
    scraper = get_scraper()
    try:
        response = scraper.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        lines = [line.text.strip() for line in soup.select(".deck_line") if line.text.strip()]
        return lines
    except:
        return []

def get_card_name(line):
    # Regex to extract name from '4 Lightning Bolt'
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI LAYOUT ---

st.title("🎴 MTG Meta & Spicy Tech Analyzer")

with st.sidebar:
    st.header("Parameters")
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Timeframe", [3, 7, 30], index=1)
    
    st.divider()
    debug_mode = st.checkbox("Show Scraper Debug Info")
    if st.button("🔄 Clear Cache & Refresh"):
        st.cache_data.clear()
        st.rerun()

codes = FORMAT_MAP[fmt]
col1, col2 = st.columns([1, 2])

# LEFT: GOLDFISH
with col1:
    st.subheader("Metagame Share")
    meta_df, m_status = fetch_goldfish(codes['gold'])
    
    if debug_mode:
        st.write(f"Goldfish Status: {m_status}")
        
    if not meta_df.empty:
        st.dataframe(meta_df, hide_index=True, use_container_width=True)
    else:
        st.warning(f"No Goldfish data. Status: {m_status}")

# RIGHT: TOP 8
with col2:
    st.subheader(f"Recent {fmt} Events")
    top8_df, t_status = fetch_top8(codes['top8'], days)
    
    if debug_mode:
        st.write(f"Top8 Status: {t_status}")

    if not top8_df.empty:
        selection = st.dataframe(
            top8_df[['Date', 'Place', 'Deck Title']], 
            on_select="rerun", selection_mode="single-row",
            hide_index=True, use_container_width=True
        )

        if len(selection['selection']['rows']) > 0:
            idx = selection['selection']['rows'][0]
            deck_url = top8_df.iloc[idx]['Link']
            
            # 1. Fetch current deck
            decklist = fetch_decklist(deck_url)
            
            # 2. Spicy Logic (Compare against other decks in the table)
            baseline_urls = top8_df['Link'].iloc[0:8].tolist()
            other_decks = [fetch_decklist(u) for u in baseline_urls if u != deck_url]
            
            other_cards = set()
            for d in other_decks:
                for line in d:
                    other_cards.add(get_card_name(line))

            st.divider()
            st.subheader(f"Decklist: {top8_df.iloc[idx]['Deck Title']}")
            st.info("💡 Cards in :blue[blue] are unique to this deck list.")

            # Display
            for line in decklist:
                name = get_card_name(line)
                is_header = any(x in line for x in ["Sideboard", "Mainboard", "Deck"])
                
                if not is_header and name not in other_cards:
                    st.markdown(f":blue[{line}]")
                else:
                    st.text(line)

            # Export
            clean_text = "\n".join(decklist)
            c1, c2 = st.columns(2)
            with c1:
                st.copy_button("📋 Copy Decklist", clean_text)
            with c2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_text)}"
                st.link_button("↗️ Export to Moxfield", mox_url)
    else:
        st.info("No Top 8 results found.")
