import streamlit as st
import pandas as pd
from sqlalchemy import text
import extra_streamlit_components as stx
import datetime
from database import conn, init_db
from ui_components import ddp_dialog, batch_actions_dialog

# --- 1. DATA CACHING (The Speed Secret) ---
@st.cache_data(ttl=20)
def fetch_all_guests():
    """Fetches data and caches it for 20 seconds to prevent DB latency"""
    return conn.query("SELECT * FROM guests", ttl=0)

# --- 2. SEARCH & RESULTS FRAGMENT ---
@st.fragment
def search_results_fragment():
    raw_df = fetch_all_guests()
    
    # Defensive Column Check for new features
    expected = ['category', 'speaker_category', 'accompanying_persons', 'poc', 'assigned_gre', 'departure_time', 'housing', 'gift_type', 'ashram_tour']
    for col in expected:
        if col not in raw_df.columns: raw_df[col] = None 
    
    if not raw_df.empty:
        raw_df['arrival_dt'] = pd.to_datetime(raw_df['arrival_time'], format='%d/%m/%Y %H:%M', errors='coerce')

    st.title("🔍 Comprehensive Guest Search")
    
    # Expand to 4 columns to make room for the new search box
    f1, f1a, f2, f3 = st.columns([2, 2, 2, 2]) 
    
    # 1. Extract clean, sorted lists of unique names directly from the data
    all_guests = sorted([str(x) for x in raw_df['name'].dropna().unique() if str(x).strip()])
    all_pocs = sorted([str(x) for x in raw_df['poc'].dropna().unique() if str(x).strip()])
    
    # 2. Use selectbox with index=None to create an autocomplete search bar
    with f1: s_name = st.selectbox("👤 Guest Name", options=all_guests, index=None, placeholder="Type or select...", key="s_name_input")
    with f1a: s_poc = st.selectbox("📞 POC Name", options=all_pocs, index=None, placeholder="Type or select...", key="s_poc_input")
    with f2:
        available = sorted(list(set([str(c).strip() for c in raw_df['category'].dropna() if str(c).strip() not in ["", "nan", "None", "--"]]))) if not raw_df.empty else []
        s_cats = st.multiselect("🏷️ Categories", available, key="s_cat_select")
    with f3:
        today = datetime.date.today()
        d_range = st.date_input("📅 Date Range", value=(today, today), format="DD/MM/YYYY", key="s_date_range")

    filtered_df = raw_df.copy()
    if not filtered_df.empty:
        # 1. Filter by the exact Guest Name selected from the dropdown
        if s_name:
            filtered_df = filtered_df[filtered_df['name'] == s_name]
        
        # 2. Filter by the exact POC selected from the dropdown
        if s_poc:
            filtered_df = filtered_df[filtered_df['poc'] == s_poc]
        if s_cats: filtered_df = filtered_df[filtered_df['category'].isin(s_cats)]
        if isinstance(d_range, tuple) and len(d_range) == 2:
            def to_dummy(dt):
                if pd.isna(dt): return pd.NaT
                return pd.Timestamp(year=2024, month=dt.month, day=dt.day)
            d_start, d_end = to_dummy(d_range[0]), to_dummy(d_range[1])
            filtered_df['dummy_date'] = filtered_df['arrival_dt'].apply(to_dummy)
            filtered_df = filtered_df[(filtered_df['dummy_date'] >= d_start) & (filtered_df['dummy_date'] <= d_end) | filtered_df['arrival_dt'].isna()]

    st.divider()
    is_default = (not s_name) and (not s_cats) and (d_range == (today, today))
    
    if is_default:
        st.subheader("📅 Today's Dashboard")
        disp = raw_df[raw_df['arrival_dt'].dt.date == today] if not raw_df.empty else pd.DataFrame()
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Arrivals", len(disp))
        m2.metric("Pending Pickups", len(disp[disp['airport_pickup_sent'] == 0]) if not disp.empty else 0)
        m3.metric("Dirty Rooms", len(disp[disp['room_cleaned'] == 0]) if not disp.empty else 0)
    else:
        st.subheader("📊 Search Metrics")
        disp = filtered_df
        
        # 1. Prepare base metrics
        metrics_data = [
            ("Total Results", len(disp)),
            ("Speakers", len(disp[disp['speaker_category'] == 'Speaker']) if not disp.empty else 0)
        ]
        
        # 2. Dynamically add category counts using pandas value_counts()
        if not disp.empty and 'category' in disp.columns:
            cat_counts = disp['category'].replace(r'^\s*$', 'Uncategorized', regex=True).fillna('Uncategorized').value_counts()
            for cat_name, count in cat_counts.items():
                metrics_data.append((str(cat_name), count))
        
        # 3. Render metrics cleanly in rows (max 4 columns per row so it doesn't get squished)
        cols_per_row = 4
        for i in range(0, len(metrics_data), cols_per_row):
            cols = st.columns(cols_per_row)
            chunk = metrics_data[i : i + cols_per_row]
            for j, (label, val) in enumerate(chunk):
                cols[j].metric(label, val)

    st.divider()

    if not disp.empty:
        # Priority Sorting
        def eval_warnings(row):
            dt = row['arrival_dt']
            is_today = pd.notna(dt) and dt.date() == today
            room_w = is_today and not bool(row['room_cleaned'])
            gre_w = pd.isna(row['assigned_gre']) or str(row['assigned_gre']).strip() in ["", "-- Unassigned --", "None", "--"]
            return pd.Series([2 if gre_w else (1 if room_w else 0), pd.Timestamp(dt.date()) if pd.notna(dt) else pd.NaT], index=['w_score', 's_date'])

        disp[['w_score', 's_date']] = disp.apply(eval_warnings, axis=1)
        disp = disp.sort_values(by=['s_date', 'w_score', 'arrival_dt'], ascending=[True, False, True], na_position='last')

        selected_ids = [row['id'] for _, row in disp.iterrows() if st.session_state.get(f"chk_{row['id']}", False)]
        c1, c2 = st.columns([8, 2])
        with c2:
            if st.button(f"🛠️ Batch Actions ({len(selected_ids)})", use_container_width=True, key="batch_btn"):
                if selected_ids: batch_actions_dialog(selected_ids)
                else: st.warning("Select guests first.")

        with st.container(border=True):
            # Updated to 6 columns with balanced widths
            h0, h1, h2, h3, h4, h5 = st.columns([0.5, 3, 2, 2, 2, 2])
            h0.write("**☑**")
            h1.write("**Guest Name**")
            h2.write("**Date of Arrival**")
            h3.write("**POC Name**")
            h4.write("**GRE Name**")
            h5.write("**# of Guests**")
            
            for _, row in disp.iterrows():
                with st.container(border=True):
                    r0, r1, r2, r3, r4, r5 = st.columns([0.5, 3, 2, 2, 2, 2])
                    r0.checkbox(" ", key=f"chk_{row['id']}", label_visibility="collapsed")
                    
                    gre_w = pd.isna(row['assigned_gre']) or str(row['assigned_gre']).strip() in ["", "-- Unassigned --"]
                    icon = "🚨" if gre_w else "👤"
                    
                    if r1.button(f"{icon} {row['name']}", key=f"btn_{row['id']}", type="primary" if gre_w else "secondary", use_container_width=True): 
                        ddp_dialog(row.to_dict())
                    
                    if gre_w:
                        st.markdown("<p style='color: #ff4b4b; font-size: 11px; margin-top: -15px;'>🚨 UNASSIGNED</p>", unsafe_allow_html=True)
                        
                    # Reordered to match the requested left-to-right flow
                    r2.write(row['arrival_time'] or "TBD")
                    r3.write(row['poc'] or "TBD")
                    r4.write(row['assigned_gre'] if not gre_w else "❌ Pending")
                    r5.write(str(row.get('accompanying_persons', '0')))
    else: 
        st.warning("No guests found.")

# --- 3. ADMIN TOOLS FRAGMENT ---
@st.fragment
def admin_tools_fragment():
    with st.expander("🛠️ Admin Tools (Add GRE / Bulk Import)"):
        t1, t2 = st.tabs(["Add GRE", "CSV Import"])
        
        with t1:
            with st.form("gre_f", clear_on_submit=True):
                gn = st.text_input("Name")
                gp = st.text_input("Phone (e.g., 9876543210)")
                if st.form_submit_button("Create GRE"):
                    clean_phone = "".join(c for c in str(gp) if c.isdigit() or c == "+")
                    if clean_phone and not clean_phone.startswith("+"): clean_phone = "+91" + clean_phone
                    with conn.session as s:
                        s.execute(text("INSERT INTO gres (gre_name, gre_phone) VALUES (:n, :p)"), {"n": gn, "p": clean_phone})
                        s.commit()
                    st.cache_data.clear()
                    st.success(f"Added {gn}!")

        with t2:
            st.info("📄 **CSV Required Columns:** `name`, `admin_username` (Optional: `poc`, `category`, `housing`, etc.)")
            f = st.file_uploader("Upload CSV", type="csv", key="bulk_csv_uploader")
            if f and st.button("Run Import", type="primary", key="csv_import_btn"):
                data = pd.read_csv(f)
                data.columns = data.columns.str.lower().str.strip()
                with conn.session as s:
                    for _, r in data.iterrows():
                        g_name, a_user = str(r['name']).strip(), str(r['admin_username']).strip()
                        s.execute(text("INSERT INTO admins (username, password) VALUES (:u, :p) ON CONFLICT DO NOTHING"), {"u": a_user, "p": "password123"})
                        
                        # Data Mapping
                        cat = str(r.get('category', '')).strip()
                        hou = str(r.get('housing', 'TBD')).strip()
                        spk = str(r.get('speaker_category', 'Non-Speaker')).strip()
                        
                        existing = s.execute(text("SELECT id FROM guests WHERE name = :n AND admin_owner = :u"), {"n": g_name, "u": a_user}).fetchone()
                        if existing:
                            s.execute(text("UPDATE guests SET category=:c, housing=:h, speaker_category=:s WHERE id=:id"), {"c":cat, "h":hou, "s":spk, "id":existing[0]})
                        else:
                            s.execute(text("INSERT INTO guests (name, admin_owner, category, housing, speaker_category) VALUES (:n, :u, :c, :h, :s)"), {"n":g_name, "u":a_user, "c":cat, "h":hou, "s":spk})
                    s.commit()
                st.cache_data.clear()
                st.success("Import Finished!")

# --- MAIN APP FLOW ---
def main():
    st.set_page_config(page_title="Dignitary Management", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.logged_in = False

    st.sidebar.title("🛂 Event Control")
    mode = st.sidebar.radio("Navigate to:", ["Public Search", "Staff Portal (GRE)", "Admin Portal"])

    if mode == "Public Search":
        st.title("🛂 Guest Inquiry")
        search = st.text_input("Enter Guest Name")
        if search:
            df = conn.query("SELECT name, arrival_time, departure_time, housing FROM guests WHERE name ILIKE :n", params={"n": f"%{search}%"}, ttl=0)
            st.dataframe(df, use_container_width=True)

    elif mode == "Staff Portal (GRE)":
        st.title("🛎️ Staff Portal (GRE)")
        gre_name = st.text_input("Enter GRE Name")
        if gre_name:
            st.info(f"Welcome {gre_name}. (Feature logic remains in main script for now).")

    elif mode == "Admin Portal":
        # Login logic
        if not st.session_state.logged_in:
            u, p = st.text_input("Username"), st.text_input("Password", type="password")
            if st.button("Login"):
                res = conn.query("SELECT * FROM admins WHERE username = :u AND password = :p", params={"u": u, "p": p}, ttl=0)
                if not res.empty:
                    st.session_state.logged_in, st.session_state.user = True, u
                    st.rerun()
        
        if st.session_state.logged_in:
            search_results_fragment()
            st.divider()
            admin_tools_fragment()

if __name__ == "__main__":
    main()
