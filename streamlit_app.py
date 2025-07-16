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
    user_input = st.text_input("🔐 Enter passcode to continue", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Incorrect passcode.")
    st.stop()

st.set_page_config(page_title="Order Document Timeline Report", layout="wide")
st.title("📄 Order Document Timeline Report")

st.markdown("""
This tool displays the complete lifecycle of orders through all document stages:  
**Presupuesto → Proforma → Pedido → Albarán → Factura**

All dates, transitions, and document numbers are pulled live from the Holded API.
""")

# ---------- UTILS ----------
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

def parse_from_field(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except:
            return ast.literal_eval(x)
    return {}

# ---------- PROCESS ----------
@st.cache_data(ttl=3600)
def build_table():
    presupuesto = fetch_docs("estimate")[["id", "date", "docNumber"]].rename(columns={"date": "Presupuesto Date", "docNumber": "Presupuesto DocNum"})
    proforma = fetch_docs("proform")
    proforma["from_dict"] = proforma["from"].apply(parse_from_field)
    proforma = proforma[proforma["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    proforma["from_id"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma = proforma.rename(columns={"date": "Proforma Date", "docNumber": "Proforma DocNum", "id": "prof_id"})
    proforma = proforma[["Proforma Date", "Proforma DocNum", "from_id", "prof_id"]].rename(columns={"from_id": "id"})

    pedido = fetch_docs("salesorder")
    pedido["from_dict"] = pedido["from"].apply(parse_from_field)
    pedido = pedido[pedido["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    pedido["from_id"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido = pedido.rename(columns={"date": "Pedido Date", "docNumber": "Pedido DocNum", "id": "pedido_id"})
    pedido = pedido[["Pedido Date", "Pedido DocNum", "from_id", "pedido_id"]].rename(columns={"from_id": "prof_id"})

    albaran = fetch_docs("waybill")
    albaran["from_dict"] = albaran["from"].apply(parse_from_field)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["from_id"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran = albaran.rename(columns={"date": "Albaran Date", "docNumber": "Albaran DocNum", "id": "albaran_id"})
    albaran = albaran[["Albaran Date", "Albaran DocNum", "from_id", "albaran_id"]].rename(columns={"from_id": "pedido_id"})

    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_from_field)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura["from_id"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura = factura.rename(columns={"date": "Factura Date", "docNumber": "Factura DocNum"})
    factura = factura[["Factura Date", "Factura DocNum", "from_id"]].rename(columns={"from_id": "albaran_id"})

    df = presupuesto.merge(proforma, on="id", how="left")
    df = df.merge(pedido, on="prof_id", how="left")
    df = df.merge(albaran, on="pedido_id", how="left")
    df = df.merge(factura, on="albaran_id", how="left")

    for col in ["Presupuesto Date", "Proforma Date", "Pedido Date", "Albaran Date", "Factura Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["Days to Proforma"] = (df["Proforma Date"] - df["Presupuesto Date"]).dt.days
    df["Days to Pedido"] = (df["Pedido Date"] - df["Proforma Date"]).dt.days
    df["Days to Albaran"] = (df["Albaran Date"] - df["Pedido Date"]).dt.days
    df["Days to Factura"] = (df["Factura Date"] - df["Albaran Date"]).dt.days

    df = df.sort_values(by="Presupuesto Date")

    return df

# ---------- DISPLAY ----------
df = build_table()

search = st.text_input("Search by Pedido DocNum (optional):")
if search:
    df = df[df["Pedido DocNum"].astype(str).str.contains(search.strip(), case=False, na=False)]

if df.empty:
    st.warning("No documents found.")
else:
    st.success("Documents loaded successfully.")
    columns = [
        "Presupuesto Date", "Days to Proforma", "Proforma Date", "Days to Pedido",
        "Pedido Date", "Days to Albaran", "Albaran Date", "Days to Factura", "Factura Date",
        "Presupuesto DocNum", "Proforma DocNum", "Pedido DocNum", "Albaran DocNum", "Factura DocNum"
    ]
    st.dataframe(df[columns], use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download CSV", data=csv, file_name="document_timeline.csv", mime="text/csv")
