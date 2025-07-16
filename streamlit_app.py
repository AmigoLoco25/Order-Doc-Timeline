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
    user_input = st.text_input("🔐 Enter Passcode", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

st.set_page_config(page_title="📄 Order Document Timeline Report", layout="wide")
st.title("📄 Order Document Timeline Report")
st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**  
All data is pulled live from Holded via the API.
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

@st.cache_data(ttl=3600)
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

# ---------- MAIN LOGIC ----------
@st.cache_data(ttl=3600)
def build_table():
    # Fetch and rename
    presupuesto = fetch_docs("estimate")
    presupuesto = presupuesto.rename(columns={
        "id": "presupuesto_id",
        "contactName": "Client",
        "total": "Total",
        "date": "Presupuesto Date",
        "docNumber": "Presupuesto DocNum"
    })[["presupuesto_id", "Client", "Total", "Presupuesto Date", "Presupuesto DocNum"]]

    proforma = fetch_docs("proform")
    proforma["from_dict"] = proforma["from"].apply(parse_from_cell)
    proforma = proforma[proforma["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    proforma["from_id_proforma"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma = proforma.rename(columns={
        "id": "proforma_id",
        "date": "Proforma Date",
        "docNumber": "Proforma DocNum"
    })[["from_id_proforma", "proforma_id", "Proforma Date", "Proforma DocNum"]]

    pedido = fetch_docs("salesorder")
    pedido["from_dict"] = pedido["from"].apply(parse_from_cell)
    pedido = pedido[pedido["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    pedido["from_id_pedido"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido = pedido.rename(columns={
        "id": "pedido_id",
        "date": "Pedido Date",
        "docNumber": "Pedido DocNum"
    })[["from_id_pedido", "pedido_id", "Pedido Date", "Pedido DocNum"]]

    albaran = fetch_docs("waybill")
    albaran["from_dict"] = albaran["from"].apply(parse_from_cell)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["from_id_albaran"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran = albaran.rename(columns={
        "id": "albaran_id",
        "date": "Albaran Date",
        "docNumber": "Albaran DocNum"
    })[["from_id_albaran", "albaran_id", "Albaran Date", "Albaran DocNum"]]

    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_from_cell)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura["from_id_factura"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura = factura.rename(columns={
        "date": "Factura Date",
        "docNumber": "Factura DocNum"
    })[["from_id_factura", "Factura Date", "Factura DocNum"]]

    # Merge
    df = presupuesto.merge(proforma, left_on="presupuesto_id", right_on="from_id_proforma", how="left")
    df = df.merge(pedido, left_on="proforma_id", right_on="from_id_pedido", how="left")
    df = df.merge(albaran, left_on="pedido_id", right_on="from_id_albaran", how="left")
    df = df.merge(factura, left_on="albaran_id", right_on="from_id_factura", how="left")

    # Convert to datetime
    for col in ["Presupuesto Date", "Proforma Date", "Pedido Date", "Albaran Date", "Factura Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    # Time differences
    df["Pres → Prof (days)"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["Prof → Ped (days)"] = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["Ped → Alb (days)"] = (df["Albaran Date"] - df["Pedido Date"]).dt.days
    df["Alb → Fac (days)"] = (df["Factura Date"] - df["Albaran Date"]).dt.days

    # Final column order
    return df[[
        "Client", "Total",
        "Presupuesto Date", "Pres → Prof (days)",
        "Proforma Date", "Prof → Ped (days)",
        "Pedido Date", "Ped → Alb (days)",
        "Albaran Date", "Alb → Fac (days)",
        "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum", "Pedido DocNum", "Albaran DocNum", "Factura DocNum"
    ]].sort_values("Presupuesto Date")

# ---------- UI ----------
df = build_table()

search = st.text_input("Filter by Pedido Doc Number (optional):", placeholder="e.g. SO250066")
if search:
    df = df[df["Pedido DocNum"].astype(str).str.contains(search, case=False)]

if df.empty:
    st.warning("No documents found.")
else:
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="order_timeline.csv", mime="text/csv")
