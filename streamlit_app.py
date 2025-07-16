import streamlit as st
import pandas as pd
import requests
import json
import ast
from datetime import datetime

# ---------- AUTHENTICATION ----------
api_key = st.secrets["HOLDED_API_KEY"]
PASSCODE = st.secrets["STREAMLIT_PASSCODE"]

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    user_input = st.text_input("🔐 Enter passcode to access:", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

# ---------- PAGE SETUP ----------
st.set_page_config(page_title="📄 Order Document Timeline Report", layout="wide")
st.title("📄 Order Document Timeline Report")

st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**  
All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------- HELPER ----------
def parse_from_cell(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except:
            return ast.literal_eval(x)
    return {}

# ---------- FETCH DOCS ----------
@st.cache_data(ttl=3600)
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

# ---------- BUILD FULL TABLE ----------
@st.cache_data(ttl=3600)
def build_table():
    presupuesto = fetch_docs("estimate")[["id", "clientName", "total", "date", "docNumber"]]
    presupuesto.columns = ["Presupuesto ID", "Client", "Total", "Presupuesto Date", "Presupuesto DocNum"]

    proforma = fetch_docs("proform")
    proforma["from_dict"] = proforma["from"].apply(parse_from_cell)
    proforma = proforma[proforma["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    proforma["Presupuesto ID"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma = proforma[["Presupuesto ID", "date", "docNumber", "id"]]
    proforma.columns = ["Presupuesto ID", "Proforma Date", "Proforma DocNum", "Proforma ID"]

    pedido = fetch_docs("salesorder")
    pedido["from_dict"] = pedido["from"].apply(parse_from_cell)
    pedido = pedido[pedido["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    pedido["Proforma ID"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido = pedido[["Proforma ID", "date", "docNumber", "id"]]
    pedido.columns = ["Proforma ID", "Pedido Date", "Pedido DocNum", "Pedido ID"]

    albaran = fetch_docs("waybill")
    albaran["from_dict"] = albaran["from"].apply(parse_from_cell)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["Pedido ID"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran = albaran[["Pedido ID", "date", "docNumber", "id"]]
    albaran.columns = ["Pedido ID", "Albarán Date", "Albarán DocNum", "Albarán ID"]

    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_from_cell)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura["Albarán ID"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura = factura[["Albarán ID", "date", "docNumber"]]
    factura.columns = ["Albarán ID", "Factura Date", "Factura DocNum"]

    # Merge step-by-step
    df = presupuesto.merge(proforma, on="Presupuesto ID", how="left")
    df = df.merge(pedido, on="Proforma ID", how="left")
    df = df.merge(albaran, on="Pedido ID", how="left")
    df = df.merge(factura, on="Albarán ID", how="left")

    # Convert dates
    date_cols = ["Presupuesto Date", "Proforma Date", "Pedido Date", "Albarán Date", "Factura Date"]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    # Calculate differences in days
    df["→ Proforma"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["→ Pedido"]   = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["→ Albarán"]  = (df["Albarán Date"] - df["Pedido Date"]).dt.days
    df["→ Factura"]  = (df["Factura Date"] - df["Albarán Date"]).dt.days

    # Reorder columns
    ordered_cols = [
        "Client", "Total",
        "Presupuesto Date", "→ Proforma",
        "Proforma Date", "→ Pedido",
        "Pedido Date", "→ Albarán",
        "Albarán Date", "→ Factura",
        "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum", "Pedido DocNum", "Albarán DocNum", "Factura DocNum"
    ]
    return df[ordered_cols]

# ---------- UI ----------
df = build_table()

# Sort by Presupuesto Date
df = df.sort_values("Presupuesto Date")

search_input = st.text_input("Filter by Pedido Doc Number:")
if search_input:
    df = df[df["Pedido DocNum"].astype(str).str.contains(search_input, case=False)]

if df.empty:
    st.warning("No matching documents found.")
else:
    st.success("✅ Document timeline loaded successfully!")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="order_document_timeline.csv", mime="text/csv")
