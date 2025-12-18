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

# --- GITHUB DATA PERSISTENCE ---

def load_from_github():
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            json_data = res.json()
            content = base64.b64decode(json_data['content']).decode('utf-8')
            db = json.loads(content)
            # Ensure keys exist
            if "meta" not in db: db["meta"] = {}
            if "decks" not in db: db["decks"] = []
            return db, json_data['sha']
    except Exception:
        pass
    return {"meta": {}, "decks": []}, None

def save_to_github(data, sha):
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    # Keep only the last 30 days of data in the JSON
    cutoff = datetime.now() - timedelta(days=30)
    data["decks"] = [
        d for d in data["decks"] 
        if datetime.strptime(d['Date'], "%d/%m/%y") > cutoff
    ]
    
    content_encoded = base64.b64encode(json.dumps(data, indent=2).encode('utf-8')).decode('utf-8')
    payload = {
        "message": "Update MTG Database",
        "content": content_encoded,
        "sha": sha
    }
    requests.put(url, headers=headers, json=payload)

# --- SCRAPING LOGIC ---

def scrape_meta(fmt_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{fmt_name}/full#paper"
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        decks = []
        for row in soup.find_all("tr"):
            text = row.get_text(separator=" ")
            pct_match = re.search(r'(\d+\.\d+%)', text)
            if pct_match:
                link = row.find("a")
                if link and len(link.text.strip()) > 2:
                    decks.append({"name": link.text.strip(), "pct": pct_match.group(1)})
        return decks
    except:
        return []

def scrape_top8_incremental(fmt_code, existing_decks):
    scraper = get_scraper()
    url = f"https://www.mtgtop8.com/format?f={fmt_code}&cp=2"
    
    fmt_decks = [d for d in existing_decks if d['format'] == fmt_code]
    newest_cached = None
    if fmt_decks:
        newest_cached = max([datetime.strptime(d['Date'], "%d/%m/%y") for d in fmt_decks])

    new_entries = []
    try:
        res = scraper.get(url, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("tr.hover_tr"):
            cols = row.find_all("td")
            if len(cols) >= 5:
                date_str = cols[4].text.strip()
                try:
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
                except: continue
        return new_entries
    except:
        return []

def fetch_clean_decklist(deck_id):
    scraper = get_scraper()
    try:
        res = scraper.get(f"https://www.mtgtop8.com/dec?d={deck_id}", timeout=15)
        return [l.strip() for l in res.text.splitlines() if l.strip() and not l.startswith("//")]
    except:
        return []

def get_card_name(line):
    return re.sub(r'^\d+\s+', '', line).strip()

# --- APP UI ---

if not GITHUB_TOKEN or not REPO_NAME:
    st.error("Missing GitHub Secrets (GITHUB_TOKEN / REPO_NAME)")
    st.stop()

# Load DB
db, current_sha = load_from_github()

with st.sidebar:
    st.title("Admin Controls")
    sel_fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days_to_show = st.radio("Timeframe", [3, 7, 30], index=2)
    
    if st.button("🔄 Sync New Data"):
        with st.spinner("Writing new data to GitHub..."):
            db["meta"][sel_fmt] = scrape_meta(FORMAT_MAP[sel_fmt]['gold'])
            # FIXED: Calling the correct f
