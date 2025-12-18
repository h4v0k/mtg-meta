import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import urllib.parse

# Initialize scraper
scraper = cloudscraper.create_scraper()

st.set_page_config(page_title="MTG Meta & Spicy Tech", layout="wide")

# --- CACHED SCRAPING FUNCTIONS (Refreshing Daily) ---

@st.cache_data(ttl="1d")  # Stores data for 24 hours
def fetch_metagame(format_name):
    """Pulls the % breakdown from MTGGoldfish"""
    url = f"https://www.mtggoldfish.com/metagame/{format_name}#paper"
    try:
        response = scraper.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        decks = []
        for row in soup.select(".archetype-tile")[:15]:  # Get Top 15
            name = row.select_one(".deck-price-paper a").text.strip()
            perc = row.select_one(".metagame-percentage-column").text.strip()
            decks.append({"Deck": name, "Meta %": perc})
        return pd.DataFrame(decks)
    except:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def fetch_top8_list(format_code):
    """Pulls the recent Top 8 event entries from MTGTop8"""
    url = f"https://www.mtgtop8.com/format?f={format_code}"
    try:
        response = scraper.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        events = []
        rows = soup.select("tr.hover_tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 4:
                events.append({
                    "Date": cols[4].text.strip(),
                    "Place": cols[2].text.strip(),
                    "Title": cols[1].text.strip(),
                    "Link": "https://www.mtgtop8.com/" + cols[1].find('a')['href']
                })
        return pd.DataFrame(events)
    except:
        return pd.DataFrame()

@st.cache_data(ttl="1d")
def get_deck_details(url):
    """Pulls a full decklist from a specific MTGTop8 link"""
    response = scraper.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    decklist = []
    # MTGTop8 lists cards in divs with class 'deck_line'
    for line in soup.select(".deck_line"):
        decklist.append(line.text.strip())
    return decklist

# --- LOGIC: SPICY CARD IDENTIFICATION ---

def identify_spicy_cards(current_deck, other_decks_data):
    """
    Compares the current deck against a baseline of other decks.
    A card is 'spicy' if it appears in the current deck but is rare in others.
    """
    # Simple logic: If we don't have comparison data, nothing is spicy yet
    if not other_decks_data:
        return current_deck, []
    
    # Flatten all cards in 'other' decks into a frequency map
    all_other_cards = [card.split(' ', 1)[-1] for deck in other_decks_data for card in deck]
    
    spicy_list = []
    processed_deck = []
    
    for line in current_deck:
        parts = line.split(' ', 1)
        if len(parts) > 1:
            qty, name = parts
            # If card appears in less than 20% of other decks, mark it blue
            if all_other_cards.count(name) < (len(other_decks_data) * 0.2):
                processed_deck.append(f"{qty} :blue[{name}]")
                spicy_list.append(line)
            else:
                processed_deck.append(line)
        else:
            processed_deck.append(line)
            
    return processed_deck, spicy_list

# --- USER INTERFACE ---

st.title("🛡️ MTG Daily Meta & Spicy Tech")
st.caption(f"Last Refresh: {datetime.now().strftime('%Y-%m-%d')}. Data persists for 24 hours.")

# Sidebar setup
FORMAT_MAP = {"Standard": "ST", "Modern": "MO", "Pioneer": "PI", "Legacy": "LE"}
GOLDFISH_MAP = {"Standard": "standard", "Modern": "modern", "Pioneer": "pioneer", "Legacy": "legacy"}

with st.sidebar:
    fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    timeframe = st.selectbox("Analysis Window", ["3 Days", "7 Days", "30 Days"])

col1, col2 = st.columns([1, 2])

# Column 1: Metagame %
with col1:
    st.subheader("Meta Breakdown")
    meta_df = fetch_metagame(GOLDFISH_MAP[fmt])
    if not meta_df.empty:
        st.dataframe(meta_df, use_container_width=True, hide_index=True)

# Column 2: Recent Top 8s
with col2:
    st.subheader(f"Recent {fmt} Top 8s")
    top8_df = fetch_top8_list(FORMAT_MAP[fmt])
    
    if not top8_df.empty:
        # Display table
        selected_event = st.dataframe(
            top8_df[['Date', 'Place', 'Title']], 
            on_select="rerun", 
            selection_mode="single-row",
            use_container_width=True,
            hide_index=True
        )

        # If a deck is clicked
        if len(selected_event['selection']['rows']) > 0:
            idx = selected_event['selection']['rows'][0]
            url = top8_df.iloc[idx]['Link']
            
            # 1. Get current deck
            raw_deck = get_deck_details(url)
            
            # 2. Get baseline (sample of 3 other decks for comparison)
            baseline_urls = top8_df['Link'].iloc[0:5].tolist()
            other_decks = [get_deck_details(u) for u in baseline_urls if u != url]
            
            # 3. Process spicy cards
            display_deck, spicy_cards = identify_spicy_cards(raw_deck, other_decks)
            
            st.divider()
            st.subheader(f"Decklist: {top8_df.iloc[idx]['Title']}")
            st.info("Blue cards = Unique/Spicy inclusions compared to others.")

            # Display with blue highlighting
            st.markdown("\n".join([f"- {line}" for line in display_deck]))
            
            # ACTION BUTTONS
            clean_deck_text = "\n".join(raw_deck)
            
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                # Built-in Copy button (Streamlit 1.22+)
                st.copy_button("📋 Copy Plain Decklist", clean_deck_text)
            with c2:
                # Moxfield Export
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(clean_deck_text)}"
                st.link_button("↗️ Export to Moxfield", mox_url)

    else:
        st.warning("No recent events found. Try a different format.")
