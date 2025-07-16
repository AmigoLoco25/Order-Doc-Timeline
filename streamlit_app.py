import streamlit as st
import pandas as pd
import requests

# ---------- AUTHENTICATION ----------
api_key = st.secrets["HOLDED_API_KEY"]
PASSCODE = st.secrets["STREAMLIT_PASSCODE"]

# Require login passcode
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Secure Access")
    user_input = st.text_input("Enter the passcode to access this app:", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

# ---------- STREAMLIT UI ----------
st.set_page_config(page_title="Order Document Timeline", layout="wide")
st.title("📄 Order Document Timeline Report")

st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:
**Presupuesto → Proforma → Pedido → Albaran → Factura**.

All dates, transitions, and document numbers are pulled via the Holded API.
""")

# ---------- LOAD DATA ----------
@st.cache_data(ttl=3600)
def load_order_data():
    file_path = "main.csv"  # Ensure this CSV is in your GitHub repo
    df = pd.read_csv(file_path)
    return df

df = load_order_data()

# ---------- DISPLAY FILTERED DATA ----------
search_client = st.text_input("Search by Client Name (optional):", placeholder="e.g. John Doe")
if search_client:
    filtered_df = df[df["Cliente"].str.contains(search_client, case=False, na=False)]
else:
    filtered_df = df

if filtered_df.empty:
    st.warning("No results found.")
else:
    st.success(f"{len(filtered_df)} results found.")
    st.dataframe(filtered_df, use_container_width=True)

    # Download button
    csv = filtered_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 Download CSV",
        data=csv,
        file_name="order_timeline.csv",
        mime="text/csv"
    )
