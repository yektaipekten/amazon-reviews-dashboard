# app.py
import os
import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO

st.set_page_config(page_title="Amazon Reviews Dashboard", layout="wide")

# ---- CONFIG ----
# Read API key from Streamlit secrets or environment
API_KEY = st.secrets.get("RAINFOREST_API_KEY") or os.environ.get("RAINFOREST_API_KEY")
MARKETPLACE = "amazon.pl"

# Optional simple password protection (set APP_PASSWORD in Streamlit secrets)
APP_PASSWORD = st.secrets.get("APP_PASSWORD")  # optional

if APP_PASSWORD:
    pw = st.text_input("Password", type="password")
    if pw != APP_PASSWORD:
        st.stop()

st.title("📊 Amazon Reviews Dashboard")
st.write("Click **Fetch Reviews** to pull ratings & breakdown from Amazon.")

# Small UI for ASIN input (you can paste full list or keep repo-managed list)
asins_text = st.text_area("ASINs (one per line)", height=150,
                         value="B0DNKXYG1X\nB0D7J5NNJY")  # default small example
ASINS = [a.strip() for a in asins_text.splitlines() if a.strip()]

mapping_dict = {}
mapping_loaded = False
mapping_path = "ASINs.csv"
if os.path.exists(mapping_path):
    try:
        # try reading with header first
        map_df = pd.read_csv(mapping_path, dtype=str)
        # normalize column names
        map_df.columns = [c.strip() for c in map_df.columns]
        if "ASIN" not in map_df.columns:
            # file likely has no header — read without header and assign columns
            map_df = pd.read_csv(mapping_path, header=None, dtype=str)
            # assign column names based on available columns
            if map_df.shape[1] == 1:
                map_df.columns = ["ASIN"]
                map_df["Design"] = None
                map_df["Size"] = None
            elif map_df.shape[1] == 2:
                map_df.columns = ["ASIN", "Design"]
                map_df["Size"] = None
            else:
                map_df.columns = ["ASIN", "Design", "Size"] + list(map_df.columns[3:])
        # ensure required cols exist
        if "Design" not in map_df.columns:
            map_df["Design"] = None
        if "Size" not in map_df.columns:
            map_df["Size"] = None
        # normalize ASIN values
        map_df["ASIN"] = map_df["ASIN"].astype(str).str.strip().str.upper()
        # build dict: {ASIN: {"Design": val, "Size": val}}
        mapping_dict = map_df.set_index("ASIN")[["Design", "Size"]].T.to_dict()
        mapping_loaded = True
        st.info(f"Loaded mapping from {mapping_path} ({len(mapping_dict)} rows).")
    except Exception as e:
        st.warning(f"Could not read mapping file {mapping_path}: {e}")

if st.button("Fetch Reviews"):
    if not API_KEY:
        st.error("API key not found. Please configure RAINFOREST_API_KEY in Streamlit Secrets.")
    elif not ASINS:
        st.warning("Please enter at least one ASIN.")
    else:
        progress = st.progress(0)
        results = []
        total = len(ASINS)
        credits_used = 0
        credits_remaining = None

        for i, asin in enumerate(ASINS, start=1):
            with st.spinner(f"Fetching {asin} ({i}/{total})"):
                url = "https://api.rainforestapi.com/request"
                params = {
                    "api_key": API_KEY,
                    "type": "product",
                    "amazon_domain": MARKETPLACE,
                    "asin": asin
                }
                try:
                    r = requests.get(url, params=params, timeout=30)
                    data = r.json()
                    # show credits info on first request (if available)
                    info = data.get("request_info", {})
                    credits_used = info.get("credits_used", credits_used)
                    credits_remaining = info.get("credits_remaining", credits_remaining)

                    product = data.get("product", {})
                    # default values
                    design = None
                    size = None

                    # first try to extract from API if available
                    if product:
                        for spec in product.get("specifications", []):
                            name = spec.get("name", "").lower()
                            val = spec.get("value")
                            if val is None:
                                continue
                            if "rozmiar" in name or "size" in name:
                                if not size:
                                    size = val
                            if "colour" in name or "color" in name or "dedesignsen" in name:
                                if not design:
                                    design = val

                    # if mapping loaded and ASIN matches, override design/size with mapping values
                    map_entry = mapping_dict.get(asin.strip().upper())
                    if map_entry:
                        # map_entry contains {"Design": ..., "Size": ...}
                        m_design = map_entry.get("Design")
                        m_size = map_entry.get("Size")
                        # use mapping value if it's not empty/NaN
                        if pd.notna(m_design) and str(m_design).strip() != "":
                            design = m_design
                        if pd.notna(m_size) and str(m_size).strip() != "":
                            size = m_size

                    if not product or "rating" not in product:
                        results.append({
                            "ASIN": asin, "Design": design, "Size": size,
                            "Average Rating": None, "Total Reviews": None,
                            "5★": None, "4★": None, "3★": None, "2★": None, "1★": None,
                        })
                    else:
                        br = product.get("rating_breakdown", {})
                        results.append({
                            "ASIN": asin,
                            "Design": design,
                            "Size": size,
                            "Average Rating": product.get("rating"),
                            "Total Reviews": product.get("ratings_total"),
                            "5★": br.get("five_star", {}).get("count", 0),
                            "4★": br.get("four_star", {}).get("count", 0),
                            "3★": br.get("three_star", {}).get("count", 0),
                            "2★": br.get("two_star", {}).get("count", 0),
                            "1★": br.get("one_star", {}).get("count", 0),
                        })
                except Exception as e:
                    st.error(f"Error fetching {asin}: {e}")
                    results.append({
                        "ASIN": asin, "Design": None, "Size": None,
                        "Average Rating": None, "Total Reviews": None,
                        "5★": None, "4★": None, "3★": None, "2★": None, "1★": None,
                    })

            progress.progress(i / total)
            time.sleep(0.5)  # keep reasonable pacing

        df = pd.DataFrame(results)
        st.subheader("Results")
        st.dataframe(df)

        # show credits info if available
        if credits_remaining is not None:
            st.info(f"Credits used in last response: {credits_used}; Credits remaining (approx): {credits_remaining}")

        # download excel
        out = BytesIO()
        df.to_excel(out, index=False)
        st.download_button("⬇️ Download Excel", data=out.getvalue(), file_name="asin_reviews.xlsx",
                           mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")
