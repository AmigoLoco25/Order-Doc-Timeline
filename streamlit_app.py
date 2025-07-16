import streamlit as st
import pandas as pd
import requests
import json
import ast
import pytz
import io

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

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

# ---------- HELPERS ----------
def parse_from_cell(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return ast.literal_eval(x)
    return {}

@st.cache_data(ttl=3600)
def fetch_docs(doc_type):
    url = f"https://api.holded.com/api/invoicing/v1/documents/{doc_type}"
    headers = {"accept": "application/json", "key": api_key}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())

@st.cache_data(ttl=3600)
def build_table():
    # 1) Load all document sets
    presupuesto_df = fetch_docs("estimate")
    proforma_df    = fetch_docs("proform")
    pedidos_df     = fetch_docs("salesorder")
    albaran_df     = fetch_docs("waybill")
    factura_df     = fetch_docs("invoice")

    # 2) Prep Presupuesto
    presupuesto_df = presupuesto_df.rename(columns={
        "id": "presupuesto_id",
        "contactName": "Client",
        "date": "Presupuesto Date",
        "docNumber": "Presupuesto DocNum"
    })[["presupuesto_id", "Client", "Presupuesto Date", "Presupuesto DocNum"]]

    # 3) Prep Proforma
    proforma_df["from_dict"]             = proforma_df["from"].apply(parse_from_cell)
    proforma_df["from_id_presupuesto"]   = proforma_df["from_dict"].apply(lambda d: d.get("id"))
    proforma_df = proforma_df.rename(columns={
        "id": "proforma_id",
        "date": "Proforma Date",
        "docNumber": "Proforma DocNum"
    })[["proforma_id", "Proforma Date", "Proforma DocNum", "from_id_presupuesto"]]

    # 4) Prep Pedido base
    pedidos_df["from_dict"]    = pedidos_df["from"].apply(parse_from_cell)
    pedidos_df["from_docType"] = pedidos_df["from_dict"].apply(lambda d: d.get("docType"))
    pedidos_df["from_id"]      = pedidos_df["from_dict"].apply(lambda d: d.get("id"))
    pedido_base = pedidos_df.rename(columns={
        "id": "pedido_id",
        "date": "Pedido Date",
        "docNumber": "Pedido DocNum",
        "contactName": "Client",
        "total": "Total"
    })[["pedido_id", "Pedido Date", "Pedido DocNum", "Client", "Total", "from_docType", "from_id"]]

    # 5) Build each flow

    # A) Full chain: Presupuesto ← Proforma ← Pedido
    pedido_proforma = (
        pedido_base[pedido_base["from_docType"] == "proform"]
        .merge(proforma_df,    left_on="from_id",               right_on="proforma_id",        how="left")
        .merge(presupuesto_df, left_on="from_id_presupuesto",   right_on="presupuesto_id",    how="left")
    )

    # B) Direct Presupuesto ← Pedido
    pedido_presupuesto = (
        pedido_base[pedido_base["from_docType"] == "estimate"]
        .merge(presupuesto_df, left_on="from_id", right_on="presupuesto_id", how="left")
    )
    pedido_presupuesto["Proforma DocNum"] = pd.NA
    pedido_presupuesto["Proforma Date"]   = pd.NaT

    # C) Standalone Pedido (e.g. Wix)
    pedido_standalone = pedido_base[pedido_base["from_docType"].isna()].copy()
    for c in ["Presupuesto DocNum", "Presupuesto Date", "Proforma DocNum", "Proforma Date"]:
        pedido_standalone[c] = pd.NA

    # 6) Combine
    all_pedidos = pd.concat([pedido_proforma, pedido_presupuesto, pedido_standalone], ignore_index=True)

    # 7) Link Albarán
    albaran_df["from_dict"] = albaran_df["from"].apply(parse_from_cell)
    albaran_df["from_id"]   = albaran_df["from_dict"].apply(lambda d: d.get("id"))
    albaran_df = albaran_df.rename(columns={
        "id": "albaran_id",
        "date": "Albaran Date",
        "docNumber": "Albaran DocNum"
    })[["albaran_id", "Albaran Date", "Albaran DocNum", "from_id"]]
    all_pedidos = all_pedidos.merge(
        albaran_df, left_on="pedido_id", right_on="from_id", how="left"
    )

    # 8) Link Factura
    factura_df["from_dict"] = factura_df["from"].apply(parse_from_cell)
    factura_df["from_id"]   = factura_df["from_dict"].apply(lambda d: d.get("id"))
    factura_df = factura_df[factura_df["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura_df = factura_df.rename(columns={
        "date": "Factura Date",
        "docNumber": "Factura DocNum"
    })[["Factura Date", "Factura DocNum", "from_id"]].rename(columns={"from_id": "albaran_id"})
    all_pedidos = all_pedidos.merge(
        factura_df, left_on="albaran_id", right_on="albaran_id", how="left"
    )

    # 9) Convert timestamps → Europe/Madrid datetime
    madrid_tz = pytz.timezone("Europe/Madrid")
    date_cols = ["Presupuesto Date", "Proforma Date", "Pedido Date", "Albaran Date", "Factura Date"]
    for col in date_cols:
        all_pedidos[col] = (
            pd.to_datetime(all_pedidos[col], unit="s", utc=True)
              .dt.tz_convert(madrid_tz)
        )

    # 10) Compute stage durations
    all_pedidos["Pres → Prof (days)"] = (all_pedidos["Proforma Date"] - all_pedidos["Presupuesto Date"]).dt.days
    all_pedidos["Prof → Ped (days)"] = (all_pedidos["Pedido Date"]   - all_pedidos["Proforma Date"]).dt.days
    all_pedidos["Ped → Alb (days)"]  = (all_pedidos["Albaran Date"]  - all_pedidos["Pedido Date"]).dt.days
    all_pedidos["Alb → Fac (days)"]  = (all_pedidos["Factura Date"]  - all_pedidos["Albaran Date"]).dt.days

    # 11) Format dates for display
    for col in date_cols:
        all_pedidos[col] = all_pedidos[col].dt.strftime("%d-%m-%Y")

    # 12) Sort by most recent Pedido Date
    all_pedidos["__sort_date"] = pd.to_datetime(all_pedidos["Pedido Date"], format="%d-%m-%Y", errors="coerce")
    all_pedidos = all_pedidos.sort_values("__sort_date", ascending=False).drop(columns="__sort_date")

    # 13) Final column ordering
    return all_pedidos[[
        "Client", "Total",
        "Presupuesto DocNum", "Presupuesto Date", "Pres → Prof (days)",
        "Proforma DocNum",  "Proforma Date",   "Prof → Ped (days)",
        "Pedido DocNum",    "Pedido Date",     "Ped → Alb (days)",
        "Albaran DocNum",   "Albaran Date",    "Alb → Fac (days)",
        "Factura DocNum",   "Factura Date"
    ]]

# ---------- UI ----------
df = build_table()

search = st.text_input("Filter by Pedido Doc Number (optional):", placeholder="e.g. SO250066")
if search:
    df = df[df["Pedido DocNum"].astype(str).str.contains(search, case=False)]

if df.empty:
    st.warning("No documents found.")
else:
    st.dataframe(df, use_container_width=True)
    filename = f"{search}_order_timeline.xlsx" if search else "order_timeline.xlsx"
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    buffer.seek(0)
    st.download_button(
        label="📥 Download Excel",
        data=buffer,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
