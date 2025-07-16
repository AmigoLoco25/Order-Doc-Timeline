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
    user_input = st.text_input("🔐 Enter password to access", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect password.")
    st.stop()

st.set_page_config(page_title="Order Document Timeline", layout="wide")
st.title("📄 Order Document Timeline Report")

st.markdown("""
This tool displays the complete timeline of each order through the document lifecycle:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**  
You can search by any **Pedido** document number.
""")

# ---------- UTIL ----------
def parse_cell(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except:
            return ast.literal_eval(x)
    return {}

# ---------- FETCH FUNCTIONS ----------
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

@st.cache_data(ttl=3600)
def build_table():
    presup = fetch_docs("estimate")[["id", "date", "docNumber", "contactName", "total"]]
    presup.rename(columns={
        "id": "pres_id",
        "date": "Presupuesto Date",
        "docNumber": "Presupuesto DocNum",
        "contactName": "Client",
        "total": "Total (€)"
    }, inplace=True)

    proforma = fetch_docs("proform")
    proforma["from_dict"] = proforma["from"].apply(parse_cell)
    proforma = proforma[proforma["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    proforma["pres_id"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma.rename(columns={
        "id": "prof_id",
        "date": "Proforma Date",
        "docNumber": "Proforma DocNum"
    }, inplace=True)

    pedido = fetch_docs("salesorder")
    pedido["from_dict"] = pedido["from"].apply(parse_cell)
    pedido = pedido[pedido["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    pedido["prof_id"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido.rename(columns={
        "id": "pedido_id",
        "date": "Pedido Date",
        "docNumber": "Pedido DocNum"
    }, inplace=True)

    albaran = fetch_docs("deliverynote")
    albaran["from_dict"] = albaran["from"].apply(parse_cell)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["pedido_id"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran.rename(columns={
        "id": "albaran_id",
        "date": "Albarán Date",
        "docNumber": "Albarán DocNum"
    }, inplace=True)

    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_cell)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "deliverynote")]
    factura["albaran_id"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura.rename(columns={
        "id": "factura_id",
        "date": "Factura Date",
        "docNumber": "Factura DocNum"
    }, inplace=True)

    # Merge all
    df = presup.merge(proforma, on="pres_id", how="left")\
               .merge(pedido, on="prof_id", how="left")\
               .merge(albaran, on="pedido_id", how="left")\
               .merge(factura, on="albaran_id", how="left")

    # Convert dates
    date_cols = [
        "Presupuesto Date", "Proforma Date", "Pedido Date",
        "Albarán Date", "Factura Date"
    ]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    # Calculate durations
    df["→ Proforma (Days)"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["→ Pedido (Days)"] = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["→ Albarán (Days)"] = (df["Albarán Date"] - df["Pedido Date"]).dt.days
    df["→ Factura (Days)"] = (df["Factura Date"] - df["Albarán Date"]).dt.days

    # Reorder
    final_cols = [
        "Client", "Total (€)",
        "Presupuesto Date", "→ Proforma (Days)", "Proforma Date", "→ Pedido (Days)",
        "Pedido Date", "→ Albarán (Days)", "Albarán Date", "→ Factura (Days)", "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum", "Pedido DocNum", "Albarán DocNum", "Factura DocNum"
    ]
    return df[final_cols]

# ---------- UI ----------
df = build_table()

pedido_search = st.text_input("Search by Pedido DocNum (optional):")
if pedido_search:
    df = df[df["Pedido DocNum"].str.contains(pedido_search, case=False, na=False)]

if df.empty:
    st.warning("No documents found.")
else:
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="order_document_timeline.csv", mime="text/csv")
