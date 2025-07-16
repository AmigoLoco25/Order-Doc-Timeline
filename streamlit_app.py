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
    user_input = st.text_input("🔐 Enter passcode", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

# ---------- PAGE CONFIG ----------
st.set_page_config(page_title="Order Document Timeline Report", layout="wide")
st.title("📄 Order Document Timeline Report")
st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**

All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------- HELPERS ----------
def parse_from_cell(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except:
            return ast.literal_eval(x)
    return {}

@st.cache_data(ttl=3600)
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

# ---------- DATA PROCESSING ----------
@st.cache_data(ttl=3600)
def build_table():
    presupuesto = fetch_docs("estimate")[["id", "contactName", "total", "date", "docNumber"]].rename(columns={
        "contactName": "Client",
        "date": "Presupuesto Date",
        "docNumber": "Presupuesto DocNum"
    })

    proforma = fetch_docs("proform")
    proforma["from_dict"] = proforma["from"].apply(parse_from_cell)
    proforma = proforma[proforma["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    proforma["from_id"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma = proforma.rename(columns={
        "date": "Proforma Date",
        "docNumber": "Proforma DocNum",
        "id": "proforma_id"
    })[["Proforma Date", "Proforma DocNum", "from_id", "proforma_id"]]

    pedido = fetch_docs("salesorder")
    pedido["from_dict"] = pedido["from"].apply(parse_from_cell)
    pedido = pedido[pedido["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    pedido["from_id"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido = pedido.rename(columns={
        "date": "Pedido Date",
        "docNumber": "Pedido DocNum",
        "id": "pedido_id"
    })[["Pedido Date", "Pedido DocNum", "from_id", "pedido_id"]]

    albaran = fetch_docs("waybill")
    albaran["from_dict"] = albaran["from"].apply(parse_from_cell)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["from_id"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran = albaran.rename(columns={
        "date": "Albaran Date",
        "docNumber": "Albaran DocNum",
        "id": "albaran_id"
    })[["Albaran Date", "Albaran DocNum", "from_id", "albaran_id"]]

    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_from_cell)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura["from_id"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura = factura.rename(columns={
        "date": "Factura Date",
        "docNumber": "Factura DocNum"
    })[["Factura Date", "Factura DocNum", "from_id"]]

    # Merge all docs
    df = presupuesto.merge(proforma, left_on="id", right_on="from_id", how="left")
    df = df.merge(pedido, left_on="proforma_id", right_on="from_id", how="left")
    df = df.merge(albaran, left_on="pedido_id", right_on="from_id", how="left")
    df = df.merge(factura, left_on="albaran_id", right_on="from_id", how="left")

    # Date conversion
    for col in [
        "Presupuesto Date", "Proforma Date", "Pedido Date",
        "Albaran Date", "Factura Date"
    ]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    # Time differences
    df["Presupuesto → Proforma"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["Proforma → Pedido"] = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["Pedido → Albaran"] = (df["Albaran Date"] - df["Pedido Date"]).dt.days
    df["Albaran → Factura"] = (df["Factura Date"] - df["Albaran Date"]).dt.days

    final = df[[
        "Client", "total",
        "Presupuesto Date", "Presupuesto → Proforma",
        "Proforma Date", "Proforma → Pedido",
        "Pedido Date", "Pedido → Albaran",
        "Albaran Date", "Albaran → Factura",
        "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum",
        "Pedido DocNum", "Albaran DocNum", "Factura DocNum"
    ]]

    final.sort_values(by="Presupuesto Date", ascending=False, inplace=True)
    return final

# ---------- UI ----------
df = build_table()

search = st.text_input("🔍 Search by Pedido DocNum (optional):").strip().lower()
if search:
    df = df[df["Pedido DocNum"].str.lower().str.contains(search)]

if df.empty:
    st.warning("No matching records found.")
else:
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="order_timeline_report.csv", mime="text/csv")
