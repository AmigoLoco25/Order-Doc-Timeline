import streamlit as st
import pandas as pd
import requests

# ---------- 🔐 AUTH ----------
api_key = st.secrets["HOLDED_API_KEY"]
PASSCODE = st.secrets["STREAMLIT_PASSCODE"]

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    user_input = st.text_input("🔐 Enter access passcode", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

# ---------- 📄 TITLE PAGE ----------
st.set_page_config(page_title="Order Document Timeline", layout="wide")
st.title("📄 Order Document Timeline Report")

st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán**

All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------- 🔁 API DOC FETCH ----------
@st.cache_data(ttl=600)
def fetch_documents(doc_type):
    """Fetch documents of a given type from Holded."""
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    if isinstance(data, dict) and "data" in data:
        return pd.DataFrame(data["data"])
    elif isinstance(data, list):
        return pd.DataFrame(data)
    else:
        return pd.DataFrame()

# ---------- 🧩 BUILD TIMELINE ----------
@st.cache_data(ttl=600)
def build_timeline():
    doc_types = {
        "estimate": "Presupuesto",
        "proform": "Proforma",
        "salesorder": "Pedido",
        "deliverynote": "Albarán"
    }

    all_docs = []

    for endpoint, label in doc_types.items():
        try:
            df = fetch_documents(endpoint)
            if not df.empty:
                df = df[["name", "client", "docNumber", "date"]].copy()
                df["Document Type"] = label
                all_docs.append(df)
        except Exception as e:
            st.error(f"Error fetching {label}: {e}")

    if not all_docs:
        return pd.DataFrame()

    combined = pd.concat(all_docs)
    combined.rename(columns={
        "name": "Client Name",
        "client": "Client ID",
        "docNumber": "Document Number",
        "date": "Date"
    }, inplace=True)

    combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    return combined.sort_values(["Client ID", "Date"])

# ---------- 📊 DISPLAY TIMELINE ----------
df = build_timeline()

if df.empty:
    st.warning("No documents retrieved.")
else:
    st.success(f"{len(df)} documents loaded.")
    st.dataframe(df, use_container_width=True)
