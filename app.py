import streamlit as st
import pandas as pd
import json
import requests
import base64
import urllib.parse
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="MTG Meta Analyzer", layout="wide")

# --- CONFIG ---
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN")
REPO_NAME = st.secrets.get("REPO_NAME")
DB_FILE = "database.json"

FORMAT_MAP = {
    "Standard": "ST", "Modern": "MO", "Pioneer": "PI", "Legacy": "LE", "Pauper": "PAU"
}

def load_from_github():
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            content = base64.b64decode(res.json()['content']).decode('utf-8')
            return json.loads(content)
    except: pass
    return {"meta": {}, "decks": []}

def get_card_name(line):
    return re.sub(r'^\d+\s+', '', line).strip()

# --- UI ---
db = load_from_github()

st.title("🧙‍♂️ MTG Metagame Analyzer")
st.info("Data is synced daily from local sources to bypass Cloudflare blocks.")

if not db["decks"]:
    st.warning("Database is empty. Please run the Local Sync script on your Mac.")
    st.stop()

sel_fmt_name = st.sidebar.selectbox("Format", list(FORMAT_MAP.keys()))
fmt_code = FORMAT_MAP[sel_fmt_name]

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Metagame %")
    # Pull meta for selected format
    meta_list = db["meta"].get(sel_fmt_name, [])
    if meta_list:
        m_df = pd.DataFrame(meta_list)
        m_sel = st.dataframe(m_df, on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)
        selected_archetype = m_df.iloc[m_sel['selection']['rows'][0]]['name'] if m_sel['selection']['rows'] else None
    else: st.write("No meta data.")

with col2:
    st.subheader("Recent Results")
    # Filter decks in the 30-day cache
    filtered = [d for d in db["decks"] if d['format'] == fmt_code]
    if selected_archetype:
        kw = selected_archetype.split()[0].lower()
        filtered = [d for d in filtered if kw in d['Title'].lower()]

    if filtered:
        f_df = pd.DataFrame(filtered)
        e_sel = st.dataframe(f_df[['Date', 'Place', 'Title']], on_select="rerun", selection_mode="single-row", hide_index=True, use_container_width=True)

        if e_sel['selection']['rows']:
            target = filtered[e_sel['selection']['rows'][0]]
            
            # Spicy Logic: Compare against other decks of same archetype in the 30-day DB
            kw = target['Title'].split()[0].lower()
            pool = [d['cards'] for d in db['decks'] if d.get('cards') and kw in d['Title'].lower() and d['ID'] != target['ID']]
            commons = {get_card_name(l) for dlist in pool for l in dlist}

            st.divider()
            st.subheader(target['Title'])
            
            for line in target.get('cards', []):
                nm = get_card_name(line)
                if nm not in commons and len(commons) > 0 and not any(x in line for x in ["Sideboard", "//"]):
                    st.markdown(f":blue[{line}]")
                else: st.text(line)

            txt = "\n".join(target.get('cards', []))
            c1, c2 = st.columns(2)
            with c1: st.copy_button("📋 Copy", txt)
            with c2: st.link_button("↗️ Moxfield", f"https://www.moxfield.com/decks/import?decklist={urllib.parse.quote(txt)}")
