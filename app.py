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
                         value="B0DNKXYG1X\nB0D7J5NNJY")  # ASINs
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

        # --- START: aggregation, totals row, summary and Excel export ---
        df = pd.DataFrame(results)

        # Ensure numeric types where appropriate
        df['Average Rating'] = pd.to_numeric(df.get('Average Rating'), errors='coerce')
        df['Total Reviews'] = pd.to_numeric(df.get('Total Reviews'), errors='coerce')

        # Ensure star columns exist and numeric
        star_cols = ["5★", "4★", "3★", "2★", "1★"]
        for col in star_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            else:
                df[col] = 0

        # Aggregations
        # Unweighted mean (mean of ASIN average ratings)
        unweighted_mean = None
        if df['Average Rating'].dropna().size > 0:
            unweighted_mean = round(df['Average Rating'].dropna().mean(), 3)

        # Weighted mean (by Total Reviews)
        weighted_mean = None
        total_reviews_sum = int(df['Total Reviews'].dropna().sum()) if df['Total Reviews'].dropna().size > 0 else 0
        if total_reviews_sum > 0:
            weighted_val = (df['Average Rating'].fillna(0) * df['Total Reviews'].fillna(0)).sum()
            weighted_mean = round(weighted_val / total_reviews_sum, 3)

        # Star totals
        total_5 = int(df["5★"].sum())
        total_4 = int(df["4★"].sum())
        total_3 = int(df["3★"].sum())
        total_2 = int(df["2★"].sum())
        total_1 = int(df["1★"].sum())

        # Create totals row (unweighted mean placed under Average Rating as requested)
        totals_row = {
            "ASIN": "GRAND TOTAL",
            "Design": None,
            "Size": None,
            "Average Rating": unweighted_mean,
            "Total Reviews": total_reviews_sum,
            "5★": total_5,
            "4★": total_4,
            "3★": total_3,
            "2★": total_2,
            "1★": total_1
        }

        # Ensure all keys exist in df columns
        for k in totals_row.keys():
            if k not in df.columns:
                df[k] = None

        # Append totals row
        df_with_totals = pd.concat([df, pd.DataFrame([totals_row])], ignore_index=True)

        # Streamlit summary display
        st.markdown("### Summary")
        c1, c2, c3 = st.columns(3)
        c1.metric("Unweighted avg (mean of ASIN averages)", unweighted_mean if unweighted_mean is not None else "N/A")
        c2.metric("Weighted avg (by total reviews)", weighted_mean if weighted_mean is not None else "N/A")
        c3.metric("Total reviews (sum)", total_reviews_sum)

        # Star breakdown table + chart
        star_df = pd.DataFrame({
            "Stars": ["5★", "4★", "3★", "2★", "1★"],
            "Count": [total_5, total_4, total_3, total_2, total_1]
        })
        st.write("**Star counts (sum across ASINs):**")
        st.table(star_df)
        st.bar_chart(star_df.set_index("Stars"))

        # Show full results with totals row
        st.subheader("Results")
        st.dataframe(df_with_totals)

        # Prepare Excel with Details + Summary sheets
        out = BytesIO()
        try:
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                # Details sheet (with grand total row)
                df_with_totals.to_excel(writer, index=False, sheet_name="Details")
                # Summary sheet
                summary_dict = {
                    "Metric": ["Unweighted mean", "Weighted mean", "Total reviews sum", "Total 5★", "Total 4★", "Total 3★", "Total 2★", "Total 1★"],
                    "Value": [unweighted_mean, weighted_mean, total_reviews_sum, total_5, total_4, total_3, total_2, total_1]
                }
                pd.DataFrame(summary_dict).to_excel(writer, index=False, sheet_name="Summary")
                writer.save()
            out.seek(0)
            st.download_button("⬇️ Download Excel (Details + Summary)", data=out.getvalue(),
                               file_name="asin_reviews_with_totals.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            # fallback: simple single-sheet excel if openpyxl not available
            out2 = BytesIO()
            df_with_totals.to_excel(out2, index=False)
            out2.seek(0)
            st.warning(f"Could not create multi-sheet Excel (openpyxl required). Error: {e}. Providing single-sheet export.")
            st.download_button("⬇️ Download Excel (single sheet)", data=out2.getvalue(),
                               file_name="asin_reviews.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        # --- END: aggregation, totals row, summary and Excel export ---

        # show credits info if available
        if credits_remaining is not None:
            st.info(f"Credits used in last response: {credits_used}; Credits remaining (approx): {credits_remaining}")
