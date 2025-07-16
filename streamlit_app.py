import streamlit as st
import pandas as pd
import requests
import json
import ast
from datetime import datetime, timezone
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
    # --- Fetch base docs ---
    presupuesto = fetch_docs("estimate").rename(columns={
        "id": "presupuesto_id",
        "contactName": "Client",
        "docNumber": "Presupuesto DocNum",
        "date": "Presupuesto Date"
    })[["presupuesto_id", "Client", "Presupuesto Date", "Presupuesto DocNum"]]

    proforma = fetch_docs("proform").rename(columns={
        "id": "proforma_id",
        "docNumber": "Proforma DocNum",
        "date": "Proforma Date",
        "from": "from_proforma"
    })
    proforma["from_dict"] = proforma["from_proforma"].apply(parse_from_cell)
    proforma["from_id_presupuesto"] = proforma["from_dict"].apply(lambda d: d.get("id"))
    proforma = proforma[["proforma_id", "Proforma Date", "Proforma DocNum", "from_id_presupuesto"]]

    pedido = fetch_docs("salesorder").rename(columns={
        "id": "pedido_id",
        "date": "Pedido Date",
        "docNumber": "Pedido DocNum"
    })
    pedido["from_dict"] = pedido["from"].apply(parse_from_cell)
    pedido["from_docType"] = pedido["from_dict"].apply(lambda d: d.get("docType"))
    pedido["from_id"] = pedido["from_dict"].apply(lambda d: d.get("id"))
    pedido = pedido[["pedido_id", "Pedido Date", "Pedido DocNum", "from_docType", "from_id"]]

    # --- Link pedido → proforma ---
    pedido_proforma = pedido[pedido["from_docType"] == "proform"].merge(
        proforma, left_on="from_id", right_on="proforma_id", how="left"
    )

    # → then link to presupuesto via proforma
    pedido_proforma = pedido_proforma.merge(
        presupuesto, left_on="from_id_presupuesto", right_on="presupuesto_id", how="left"
    )

    # --- Link pedido → presupuesto directly ---
    pedido_presupuesto = pedido[pedido["from_docType"] == "estimate"].merge(
        presupuesto, left_on="from_id", right_on="presupuesto_id", how="left"
    )
    pedido_presupuesto["Proforma DocNum"] = pd.NA
    pedido_presupuesto["Proforma Date"] = pd.NaT

    # --- Standalone pedidos ---
    pedido_standalone = pedido[pedido["from_docType"].isna()]
    pedido_standalone["Client"] = pd.NA
    pedido_standalone["Presupuesto DocNum"] = pd.NA
    pedido_standalone["Presupuesto Date"] = pd.NaT
    pedido_standalone["Proforma DocNum"] = pd.NA
    pedido_standalone["Proforma Date"] = pd.NaT

    # --- Combine all paths ---
    all_pedidos = pd.concat([
        pedido_proforma[[
            "Client", "pedido_id", "Pedido DocNum", "Pedido Date",
            "Proforma DocNum", "Proforma Date",
            "Presupuesto DocNum", "Presupuesto Date"
        ]],
        pedido_presupuesto[[
            "Client", "pedido_id", "Pedido DocNum", "Pedido Date",
            "Proforma DocNum", "Proforma Date",
            "Presupuesto DocNum", "Presupuesto Date"
        ]],
        pedido_standalone[[
            "Client", "pedido_id", "Pedido DocNum", "Pedido Date",
            "Proforma DocNum", "Proforma Date",
            "Presupuesto DocNum", "Presupuesto Date"
        ]]
    ], ignore_index=True)

    # --- Link to Albarán ---
    albaran = fetch_docs("waybill")
    albaran["from_dict"] = albaran["from"].apply(parse_from_cell)
    albaran = albaran[albaran["from_dict"].apply(lambda d: d.get("docType") == "salesorder")]
    albaran["from_id_albaran"] = albaran["from_dict"].apply(lambda d: d.get("id"))
    albaran = albaran.rename(columns={
        "id": "albaran_id",
        "date": "Albaran Date",
        "docNumber": "Albaran DocNum"
    })[["from_id_albaran", "albaran_id", "Albaran Date", "Albaran DocNum"]]

    all_pedidos = all_pedidos.merge(albaran, left_on="pedido_id", right_on="from_id_albaran", how="left")

    # --- Link to Factura ---
    factura = fetch_docs("invoice")
    factura["from_dict"] = factura["from"].apply(parse_from_cell)
    factura = factura[factura["from_dict"].apply(lambda d: d.get("docType") == "waybill")]
    factura["from_id_factura"] = factura["from_dict"].apply(lambda d: d.get("id"))
    factura = factura.rename(columns={
        "date": "Factura Date",
        "docNumber": "Factura DocNum"
    })[["from_id_factura", "Factura Date", "Factura DocNum"]]

    all_pedidos = all_pedidos.merge(factura, left_on="albaran_id", right_on="from_id_factura", how="left")

    # --- Format dates ---
    madrid_tz = pytz.timezone('Europe/Madrid')
    date_cols = [
        "Presupuesto Date", "Proforma Date", "Pedido Date", "Albaran Date", "Factura Date"
    ]
    for col in date_cols:
        if col in all_pedidos.columns:
            all_pedidos[col] = all_pedidos[col].apply(
                lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(madrid_tz)
                if pd.notnull(ts) else pd.NaT
            )

    # --- Time deltas ---
    all_pedidos["Pres → Prof (days)"] = (all_pedidos["Proforma Date"] - all_pedidos["Presupuesto Date"]).dt.days
    all_pedidos["Prof → Ped (days)"] = (all_pedidos["Pedido Date"] - all_pedidos["Proforma Date"]).dt.days
    all_pedidos["Ped → Alb (days)"] = (all_pedidos["Albaran Date"] - all_pedidos["Pedido Date"]).dt.days
    all_pedidos["Alb → Fac (days)"] = (all_pedidos["Factura Date"] - all_pedidos["Albaran Date"]).dt.days

    # --- Final formatting ---
    for col in date_cols:
        all_pedidos[col] = all_pedidos[col].dt.strftime("%d-%m-%Y")

    all_pedidos["__sort_date"] = pd.to_datetime(all_pedidos["Pedido Date"], format="%d-%m-%Y", errors="coerce")
    all_pedidos = all_pedidos.sort_values("__sort_date", ascending=False).drop(columns="__sort_date")

    return all_pedidos[[
        "Client", "Presupuesto DocNum", "Presupuesto Date", "Pres → Prof (days)",
        "Proforma DocNum", "Proforma Date", "Prof → Ped (days)",
        "Pedido DocNum", "Pedido Date", "Ped → Alb (days)",
        "Albaran DocNum", "Albaran Date", "Alb → Fac (days)",
        "Factura DocNum", "Factura Date"
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

    if search:
        filename=f"{search}_order_timeline.xlsx"
    else:
        filename="order_timeline.xlsx"
    excel_buffer = io.BytesIO()
                    
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    excel_buffer.seek(0)
                    
                        # Download button
    st.download_button(
        label="📥 Download Excel",
        data=excel_buffer,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


