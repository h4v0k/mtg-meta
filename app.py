import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import re
import json
import requests
import base64

# --- CONFIGURATION ---
st.set_page_config(page_title="MTG Cloud Meta Tracker", layout="wide")

# GitHub API setup
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
REPO_NAME = st.secrets.get("REPO_NAME")
DB_FILE = "database.json"

FORMAT_MAP = {
    "Standard": {"gold": "standard", "top8": "ST"},
    "Modern": {"gold": "modern", "top8": "MO"},
    "Pioneer": {"gold": "pioneer", "top8": "PI"},
    "Legacy": {"gold": "legacy", "top8": "LE"},
    "Pauper": {"gold": "pauper", "top8": "PAU"}
}

def get_scraper():
    return cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})

# --- GITHUB STORAGE LOGIC ---

def load_from_github():
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        content = base64.b64decode(res.json()['content']).decode('utf-8')
        return json.loads(content), res.json()['sha']
    return {"meta": {}, "decks": []}, None

def save_to_github(data, sha):
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    # Prune decks older than 30 days
    cutoff = datetime.now() - timedelta(days=30)
    data["decks"] = [d for d in data["decks"] if datetime.strptime(d['Date'], "%d/%m/%y") > cutoff]
    
    content_encoded = base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')
    payload = {
        "message": "Update MTG Database",
        "content": content_encoded,
        "sha": sha
    }
    requests.put(url, headers=headers, json=payload)

# --- SCRAPING ENGINE ---

def scrape_meta(fmt_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{fmt_name}#paper"
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        meta = []
        for tile in soup.select(".archetype-tile"):
            name = tile.select_one(".deck-price-paper a, .archetype-tile-description a")
            pct = re.search(r'(\d+\.\d+%)', tile.get_text())
            if name and pct:
                meta.append({"name": name.text.strip(), "pct": pct.group(1)})
        return meta
    except: return []

def scrape_top8_new(fmt_code, existing_decks):
    scraper = get_scraper()
    url = f"https://www.mtgtop8.com/format?f={fmt_code}&cp=1"
    newest_cached = None
    fmt_decks = [d for d in existing_decks if d['format'] == fmt_code]
    if fmt_decks:
        newest_cached = max([datetime.strptime(d['Date'], "%d/%m/%y") for d in fmt_decks])

    new_entries = []
    try:
        res = scraper.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("tr.hover_tr"):
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                ev_date = datetime.strptime(date_str, "%d/%m/%y")
                if newest_cached and ev_date <= newest_cached: break
                if ev_date < (datetime.now() - timedelta(days=30)): continue
                
                link = cols[1].find("a")
                if link:
                    d_id = re.search(r'd=(\d+)', link['href'])
                    new_entries.append({
                        "format": fmt_code, "Date": date_str, "Place": cols[2].text.strip(),
                        "Title": link.text.strip(), "ID": d_id.group(1) if d_id else None
                    })
        return new_entries
    except: return []

def fetch_list(deck_id):
    scraper = get_scraper()
    try:
        res = scraper.get(f"https://www.mtgtop8.com/dec?d={deck_id}")
        return [l.strip() for l in res.text.splitlines() if l.strip() and not l.startswith("//")]
    except: return []

# --- APP UI ---

if not GITHUB_TOKEN:
    st.error("Please set GITHUB_TOKEN in Streamlit Secrets.")
    st.stop()

# Load Database
db, db_sha = load_from_github()

with st.sidebar:
    st.title("Settings")
    sel_fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days = st.radio("Show Last", [3, 7, 30], index=2)
    
    if st.button("🔄 Sync with Websites"):
        with st.spinner("Finding new decks..."):
            db["meta"][sel_fmt] = scrape_meta(FORMAT_MAP[sel_fmt]['gold'])
            new_list = scrape_top8_new(FORMAT_MAP[sel_fmt]['top8'], db["decks"])
            db["decks"].extend(new_list)
            save_to_github(db, db_sha)
            st.success(f"Synced {len(new_list)} new decks!")
            st.rerun()

col1, col2 = st.columns([1, 2])

# Column 1: Meta
with col1:
    st.subheader("Metagame %")
    meta_list = db["meta"].get(sel_fmt, [])
    if meta_list:
        df_meta = pd.DataFrame(meta_list)
        sel = st.dataframe(df_meta, on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)
        selected_archetype = df_meta.iloc[sel.selection.rows[0]]['name'] if sel.selection.rows else None
    else: st.info("No data. Click Sync.")

# Column 2: Decks
with col2:
    st.subheader(f"Recent {sel_fmt} Decks")
    cutoff = datetime.now() - timedelta(days=days)
    filtered = [d for d in db["decks"] if d['format'] == FORMAT_MAP[sel_fmt]['top8'] and datetime.strptime(d['Date'], "%d/%m/%y") >= cutoff]
    
    if selected_archetype:
        kw = selected_archetype.split()[0].lower()
        filtered = [d for d in filtered if kw in d['Title'].lower()]

    if filtered:
        df_f = pd.DataFrame(filtered)
        d_sel = st.dataframe(df_f[['Date', 'Place', 'Title']], on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)

        if d_sel.selection.rows:
            target = filtered[d_sel.selection.rows[0]]
            
            # Lazy load list
            if "cards" not in target:
                target["cards"] = fetch_list(target["ID"])
                save_to_github(db, db_sha)

            # Spicy Highlighting
            archetype_pool = [d["cards"] for d in db["decks"] if "cards" in d and target["Title"].split()[0].lower() in d['Title'].lower() and d["ID"] != target["ID"]]
            commons = {re.sub(r'^\d+\s+', '', l).strip() for dlist in archetype_pool for l in dlist}

            st.divider()
            st.subheader(target["Title"])
            
            for line in target["cards"]:
                name = re.sub(r'^\d+\s+', '', line).strip()
                if name not in commons and len(commons) > 0 and not any(x in line for x in ["Sideboard", "//"]):
                    st.markdown(f":blue[{line}]")
                else: st.text(line)

            txt = "\n".join(target["cards"])
            c1, c2 = st.columns(2)
            with c1: st.copy_button("📋 Copy", txt)
            with c2: st.link_button("↗️ Moxfield", f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(txt)}")
    else: st.write("No decks in cache for this filter.")
