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
st.write("Click **Fetch Reviews** to pull ratings & breakdown from Amazon (Poland).")

# Small UI for ASIN input (you can paste full list or keep repo-managed list)
asins_text = st.text_area("ASINs (one per line)", height=150,
                         value="B0DNKXYG1X\nB0D7J5NNJY")  # default small example
ASINS = [a.strip() for a in asins_text.splitlines() if a.strip()]

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
                params = {"api_key": API_KEY, "type": "product", "amazon_domain": MARKTETPLACE if False else "amazon.pl", "asin": asin}
                # Note: using direct string to avoid accidental var name bug
                params = {"api_key": API_KEY, "type": "product", "amazon_domain": "amazon.pl", "asin": asin}
                try:
                    r = requests.get(url, params=params, timeout=30)
                    data = r.json()
                    # show credits info on first request (if available)
                    info = data.get("request_info", {})
                    credits_used = info.get("credits_used", credits_used)
                    credits_remaining = info.get("credits_remaining", credits_remaining)

                    product = data.get("product", {})
                    if not product or "rating" not in product:
                        results.append({
                            "ASIN": asin, "Design": None, "Size": None,
                            "Average Rating": None, "Total Reviews": None,
                            "5★": None, "4★": None, "3★": None, "2★": None, "1★": None,
                        })
                    else:
                        # extract small spec fields
                        design = None
                        size = None
                        for spec in product.get("specifications", []):
                            name = spec.get("name", "").lower()
                            val = spec.get("value")
                            if "rozmiar" in name or "size" in name:
                                size = val
                            if "kolor" in name or "color" in name or "desen" in name:
                                design = val

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
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
