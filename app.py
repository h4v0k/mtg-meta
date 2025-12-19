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

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", None)
REPO_NAME = st.secrets.get("REPO_NAME", None)
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
    if not GITHUB_TOKEN or not REPO_NAME:
        return {"meta": {}, "decks": []}, None
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            db = json.loads(content)
            return db, data['sha']
        else:
            st.sidebar.error(f"GitHub Load Error: {res.status_code}")
    except Exception as e:
        st.sidebar.error(f"GitHub Load Exception: {e}")
    return {"meta": {}, "decks": []}, None

def save_to_github(data, sha):
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    # Prune old data (keep 30 days)
    cutoff = datetime.now() - timedelta(days=30)
    data["decks"] = [
        d for d in data["decks"] 
        if datetime.strptime(d['Date'], "%d/%m/%y") > cutoff
    ]
    
    content_encoded = base64.b64encode(json.dumps(data, indent=2).encode('utf-8')).decode('utf-8')
    payload = {
        "message": f"Update MTG Data {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content_encoded,
        "sha": sha
    }
    res = requests.put(url, headers=headers, json=payload)
    if res.status_code in [200, 201]:
        return True
    else:
        st.error(f"GitHub Save Error: {res.status_code} - {res.text}")
        return False

# --- SCRAPING ENGINE ---

def scrape_meta(fmt_name):
    scraper = get_scraper()
    url = f"https://www.mtggoldfish.com/metagame/{fmt_name}/full#paper"
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code != 200:
            st.warning(f"MTGGoldfish returned status {res.status_code} (Likely Blocked)")
            return []
        
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
    except Exception as e:
        st.error(f"Goldfish Scrape Error: {e}")
        return []

def scrape_top8_incremental(fmt_code, existing_decks):
    scraper = get_scraper()
    url = f"https://www.mtgtop8.com/format?f={fmt_code}&cp=1"
    
    fmt_decks = [d for d in existing_decks if d['format'] == fmt_code]
    newest_cached = None
    if fmt_decks:
        newest_cached = max([datetime.strptime(d['Date'], "%d/%m/%y") for d in fmt_decks])

    new_entries = []
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code != 200:
            st.warning(f"MTGTop8 returned status {res.status_code} (Likely Blocked)")
            return []
            
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
    except Exception as e:
        st.error(f"MTGTop8 Scrape Error: {e}")
        return []

# --- MAIN UI ---

db, current_sha = load_from_github()

with st.sidebar:
    st.title("🛡️ MTG Tracker Admin")
    sel_fmt = st.selectbox("Format", list(FORMAT_MAP.keys()))
    days_to_show = st.radio("Display window", [3, 7, 30], index=2)
    
    st.divider()
    if st.button("🔄 Sync New Decks (Daily)"):
        with st.spinner("Step 1: Scraping Websites..."):
            scraped_meta = scrape_meta(FORMAT_MAP[sel_fmt]['gold'])
            new_decks = scrape_top8_incremental(FORMAT_MAP[sel_fmt]['top8'], db["decks"])
            
            if not scraped_meta and not new_decks:
                st.error("❌ Both websites blocked the scrape. Try again in an hour or run locally.")
            else:
                st.write(f"✅ Found {len(scraped_meta)} archetypes and {len(new_decks)} new decks.")
                with st.spinner("Step 2: Saving to GitHub..."):
                    db["meta"][sel_fmt] = scraped_meta
                    db["decks"].extend(new_decks)
                    success = save_to_github(db, current_sha)
                    if success:
                        st.success("🎉 Database Updated Successfully!")
                        st.rerun()

# Layout
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Metagame %")
    meta_data = db["meta"].get(sel_fmt, [])
    selected_archetype = None
    if meta_data:
        m_df = pd.DataFrame(meta_data)
        m_sel = st.dataframe(m_df, on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)
        if m_sel.selection.rows:
            selected_archetype = m_df.iloc[m_sel.selection.rows[0]]['name']
    else:
        st.info("Database is empty. Please click 'Sync New Decks' in the sidebar.")

with col2:
    st.subheader("Recent Results")
    cutoff = datetime.now() - timedelta(days=days_to_show)
    filtered = [d for d in db["decks"] if d['format'] == FORMAT_MAP[sel_fmt]['top8'] and datetime.strptime(d['Date'], "%d/%m/%y") >= cutoff]
    
    if selected_archetype:
        kw = selected_archetype.split()[0].lower()
        filtered = [d for d in filtered if kw in d['Title'].lower()]

    if filtered:
        f_df = pd.DataFrame(filtered)
        e_sel = st.dataframe(f_df[['Date', 'Place', 'Title']], on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)

        if e_sel.selection.rows:
            target = filtered[e_sel.selection.rows[0]]
            
            # Use MTGTop8 .dec export for list (Cleanest text)
            if "cards" not in target:
                with st.spinner("Downloading decklist..."):
                    scraper = get_scraper()
                    res = scraper.get(f"https://www.mtgtop8.com/dec?d={target['ID']}")
                    target["cards"] = [l.strip() for l in res.text.splitlines() if l.strip() and not l.startswith("//")]
                    _, latest_sha = load_from_github()
                    save_to_github(db, latest_sha)

            st.divider()
            st.subheader(target["Title"])
            
            # Visual List
            for line in target["cards"]:
                st.text(line)

            # Actions
            list_txt = "\n".join(target["cards"])
            a1, a2 = st.columns(2)
            with a1:
                st.copy_button("📋 Copy List", list_txt)
            with a2:
                mox_url = f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(list_txt)}"
                st.link_button("↗️ Moxfield", mox_url)
    else:
        st.write("No matching decks found.")
