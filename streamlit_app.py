import streamlit as st
import pandas as pd
import requests

# ---------------------- AUTHENTICATION ----------------------
api_key = st.secrets["HOLDED_API_KEY"]
PASSCODE = st.secrets["STREAMLIT_PASSCODE"]

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    user_input = st.text_input("🔐 Enter Access Passcode", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

# ---------------------- STREAMLIT PAGE SETUP ----------------------
st.set_page_config(page_title="Order Document Timeline", layout="wide")
st.title("📄 Order Document Timeline Report")
st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán**

All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------------------- HELPER FUNCTIONS ----------------------

@st.cache_data(ttl=600)
def fetch_documents(doc_type):
    """Fetch documents of a given type from Holded."""
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return pd.DataFrame(response.json())

@st.cache_data(ttl=600)
def build_timeline_df():
    """Construct timeline of all documents."""
    doc_types = {
        "presupuesto": "Presupuesto",
        "proform": "Proforma",
        "salesorder": "Pedido",
        "deliverynote": "Albarán"
    }

    timeline_records = []

    for api_name, label in doc_types.items():
        try:
            df = fetch_documents(api_name)
        except Exception as e:
            st.warning(f"Error fetching {label}: {e}")
            continue

        for _, row in df.iterrows():
            timeline_records.append({
                "Client": row.get("contactName", "Unknown"),
                "Document Type": label,
                "Document Number": row.get("docNumber", "N/A"),
                "Date": row.get("date", "")[:10]
            })

    return pd.DataFrame(timeline_records).sort_values(by=["Client", "Date"])

# ---------------------- MAIN APP ----------------------

if st.button("📊 Generate Timeline Report"):
    try:
        df = build_timeline_df()

        if df.empty:
            st.warning("No documents found.")
        else:
            st.success("Report generated successfully!")
            st.dataframe(df, use_container_width=True)

            # Optional: CSV download
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 Download CSV", csv, "order_timeline.csv", "text/csv")

    except Exception as e:
        st.error(f"Error loading data: {e}")
