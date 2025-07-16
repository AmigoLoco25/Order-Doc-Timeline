import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# ---------- AUTH ----------
api_key = st.secrets["HOLDED_API_KEY"]
PASSCODE = st.secrets["STREAMLIT_PASSCODE"]

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pw = st.text_input("🔐 Enter password to continue", type="password")
    if pw == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif pw:
        st.error("Incorrect password.")
    st.stop()

# ---------- PAGE ----------
st.set_page_config(page_title="Order Document Timeline Report", layout="wide")
st.title("📄 Order Document Timeline Report")
st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**  
All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------- FETCH ----------
@st.cache_data(ttl=3600)
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

# ---------- PROCESS ----------
@st.cache_data(ttl=3600)
def build_table():
    presupuesto = fetch_docs("estimate")[["id", "clientName", "total", "date", "docNumber"]].rename(columns={
        "date": "Presupuesto Date",
        "docNumber": "Presupuesto DocNum"
    })
    presupuesto["Presupuesto Date"] = pd.to_datetime(presupuesto["Presupuesto Date"], unit="ms", errors="coerce")

    proforma = fetch_docs("proform")[["id", "date", "docNumber", "from"]].rename(columns={
        "id": "proforma_id", "date": "Proforma Date", "docNumber": "Proforma DocNum"
    })
    proforma["Proforma Date"] = pd.to_datetime(proforma["Proforma Date"], unit="ms", errors="coerce")
    proforma["from_id"] = proforma["from"].apply(lambda x: x.get("id") if isinstance(x, dict) else None)

    pedido = fetch_docs("salesorder")[["id", "date", "docNumber", "from"]].rename(columns={
        "id": "pedido_id", "date": "Pedido Date", "docNumber": "Pedido DocNum"
    })
    pedido["Pedido Date"] = pd.to_datetime(pedido["Pedido Date"], unit="ms", errors="coerce")
    pedido["from_id"] = pedido["from"].apply(lambda x: x.get("id") if isinstance(x, dict) else None)

    albaran = fetch_docs("waybill")[["id", "date", "docNumber", "from"]].rename(columns={
        "id": "albaran_id", "date": "Albaran Date", "docNumber": "Albaran DocNum"
    })
    albaran["Albaran Date"] = pd.to_datetime(albaran["Albaran Date"], unit="ms", errors="coerce")
    albaran["from_id"] = albaran["from"].apply(lambda x: x.get("id") if isinstance(x, dict) else None)

    factura = fetch_docs("invoice")[["id", "date", "docNumber", "from"]].rename(columns={
        "id": "factura_id", "date": "Factura Date", "docNumber": "Factura DocNum"
    })
    factura["Factura Date"] = pd.to_datetime(factura["Factura Date"], unit="ms", errors="coerce")
    factura["from_id"] = factura["from"].apply(lambda x: x.get("id") if isinstance(x, dict) else None)

    df = presupuesto.merge(proforma, left_on="id", right_on="from_id", how="left") \
                    .merge(pedido, left_on="proforma_id", right_on="from_id", how="left") \
                    .merge(albaran, left_on="pedido_id", right_on="from_id", how="left") \
                    .merge(factura, left_on="albaran_id", right_on="from_id", how="left")

    # --- Time Deltas ---
    df["Presupuesto → Proforma"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["Proforma → Pedido"] = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["Pedido → Albaran"] = (df["Albaran Date"] - df["Pedido Date"]).dt.days
    df["Albaran → Factura"] = (df["Factura Date"] - df["Albaran Date"]).dt.days

    # --- Final Order ---
    final = df[[
        "clientName", "total",
        "Presupuesto Date", "Presupuesto → Proforma",
        "Proforma Date", "Proforma → Pedido",
        "Pedido Date", "Pedido → Albaran",
        "Albaran Date", "Albaran → Factura",
        "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum",
        "Pedido DocNum", "Albaran DocNum", "Factura DocNum"
    ]].sort_values(by="Presupuesto Date", ascending=False)

    return final

# ---------- UI ----------
df = build_table()

pedido_filter = st.text_input("Filter by Pedido DocNum (optional):")
if pedido_filter:
    df = df[df["Pedido DocNum"].str.contains(pedido_filter.strip(), case=False, na=False)]

if df.empty:
    st.warning("No documents found.")
else:
    st.success("Timeline generated successfully!")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="order_doc_timeline.csv", mime="text/csv")
