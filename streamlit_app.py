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
    user_input = st.text_input("🔐 Ingrese la contraseña", type="password")
    if user_input == PASSCODE:
        st.session_state.authenticated = True
        st.rerun()
    elif user_input:
        st.error("Contraseña incorrecta.")
    st.stop()

st.set_page_config(page_title="Fechas entre Documentos", layout="wide")
st.title("📄 Fechas entre Presupuesto → Proforma → Pedido")

st.markdown("Ingrese un número de documento o deje vacío para ver todos.")

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

# ---------- FETCH ESTIMATES ----------
@st.cache_data(ttl=3600)
def fetch_estimates():
    url = "https://api.holded.com/api/invoicing/v1/documents/estimate"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    df = pd.DataFrame(resp.json())
    return df[["id", "date", "docNumber"]].rename(columns={"date": "Presupuesto Date", "docNumber": "Presupuesto DocNum"})

# ---------- FETCH PROFORMAS ----------
@st.cache_data(ttl=3600)
def fetch_proformas():
    url = "https://api.holded.com/api/invoicing/v1/documents/proform"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    df = pd.DataFrame(resp.json())
    df["from_dict"] = df["from"].apply(parse_from_cell)
    df = df[df["from_dict"].apply(lambda d: d.get("docType") == "estimate")]
    df["from_id"] = df["from_dict"].apply(lambda d: d.get("id"))
    df = df.rename(columns={"date": "Proforma Date", "docNumber": "Proforma DocNum", "id": "prof_id"})
    return df[["Proforma Date", "Proforma DocNum", "from_id", "prof_id"]].rename(columns={"from_id": "id"})

# ---------- FETCH PEDIDOS ----------
@st.cache_data(ttl=3600)
def fetch_pedidos():
    url = "https://api.holded.com/api/invoicing/v1/documents/salesorder"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    df = pd.DataFrame(resp.json())
    df["from_dict"] = df["from"].apply(parse_from_cell)
    df = df[df["from_dict"].apply(lambda d: d.get("docType") == "proform")]
    df["from_id"] = df["from_dict"].apply(lambda d: d.get("id"))
    df = df.rename(columns={"date": "Pedido Date", "docNumber": "Pedido DocNum", "id": "pedido_id"})
    return df[["Pedido Date", "Pedido DocNum", "from_id", "pedido_id"]].rename(columns={"from_id": "prof_id"})

# ---------- PROCESS ----------
def build_table():
    pres = fetch_estimates()
    prof = fetch_proformas()
    ped = fetch_pedidos()

    merged = pd.merge(pres, prof, on="id", how="left")
    merged = pd.merge(merged, ped, on="prof_id", how="left")

    # Convert to datetime
    for col in ["Presupuesto Date", "Proforma Date", "Pedido Date"]:
        merged[col] = pd.to_datetime(merged[col], errors="coerce")

    # Calculate intervals
    merged["Días a Proforma"] = (merged["Proforma Date"] - merged["Presupuesto Date"]).dt.days
    merged["Días a Pedido"] = (merged["Pedido Date"] - merged["Proforma Date"]).dt.days

    return merged

# ---------- UI ----------
df = build_table()

search_input = st.text_input("Filtrar por DocNumber (opcional):")
if search_input:
    df = df[df.apply(lambda row: search_input.lower() in str(row["Presupuesto DocNum"]).lower(), axis=1)]

if df.empty:
    st.warning("No se encontraron documentos.")
else:
    st.success("Datos obtenidos correctamente.")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Descargar CSV", data=csv, file_name="documentos_holded.csv", mime="text/csv")

