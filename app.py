import streamlit as st
import pandas as pd
from sqlalchemy import text
import extra_streamlit_components as stx
import datetime

# --- INITIALIZE BUILT-IN SQL CONNECTION ---
conn = st.connection("postgresql", type="sql")

def init_db():
    """Ensure tables exist in Supabase and update them if needed"""
    with conn.session as s:
        s.execute(text('CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY, password TEXT);'))
        s.execute(text('CREATE TABLE IF NOT EXISTS gres (gre_id SERIAL PRIMARY KEY, gre_name TEXT, gre_phone TEXT);'))
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS guests (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                admin_owner TEXT,
                arrival_time TEXT,
                departure_time TEXT,
                airport_pickup_sent INTEGER DEFAULT 0,
                stay_location TEXT,
                room_cleaned INTEGER DEFAULT 0,
                assigned_gre TEXT,
                poc TEXT
            );
        '''))
        s.commit() 

    # --- ISOLATED TRANSACTIONS WITH ROLLBACKS ---
    columns_to_add = [
        ("departure_time", "TEXT"),
        ("poc", "TEXT"),
        ("assigned_gre", "TEXT"),
        ("category", "TEXT"),
        ("speaker_category", "TEXT"),
        ("accompanying_persons", "INTEGER DEFAULT 0")
    ]
    
    for col_name, col_type in columns_to_add:
        with conn.session as s:
            try:
                s.execute(text(f"ALTER TABLE guests ADD COLUMN {col_name} {col_type};"))
                s.commit()
            except Exception:
                s.rollback() 

# --- APP UI ---
def main():
    st.set_page_config(page_title="Dignitary Management System", layout="wide")
    init_db()

    # --- SESSION STATE INITIALIZATION ---
    if "logged_in" not in st.session_state: 
        st.session_state.logged_in = False
        st.session_state.user = ""
    if "admin_view" not in st.session_state:
        st.session_state.admin_view = "search" 
    if "selected_guest_id" not in st.session_state:
        st.session_state.selected_guest_id = None

    st.sidebar.title("🛂 Event Control")
    mode = st.sidebar.radio("Navigate to:", ["Public Search", "Staff Portal (GRE)", "Admin Portal"])

    # --- 1. PUBLIC SEARCH ---
    if mode == "Public Search":
        st.title("🛂 Guest Inquiry")
        search = st.text_input("Enter Guest Name")
        if search:
            df = conn.query("SELECT name, arrival_time, departure_time, stay_location, airport_pickup_sent, room_cleaned FROM guests WHERE name ILIKE :n", params={"n": f"%{search}%"}, ttl=0)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Guest not found.")

    # --- 2. STAFF PORTAL (GRE) ---
    elif mode == "Staff Portal (GRE)":
        st.title("🛎️ Staff Portal (GRE)")
        gre_name = st.text_input("Enter your GRE Name to access")
        
        if st.button("Access Portal"):
            gre_check = conn.query("SELECT * FROM gres WHERE gre_name ILIKE :n", params={"n": f"%{gre_name}%"}, ttl=0)
            if not gre_check.empty:
                st.success(f"Access Granted. Welcome, {gre_name}!")
                st.session_state.gre_user = gre_name
            else:
                st.error("GRE account not found. Please contact an Admin.")
                
        if st.session_state.get("gre_user"):
            st.divider()
            st.subheader("Update Guest Status")
            guests_df = conn.query("SELECT id, name, arrival_time, room_cleaned, airport_pickup_sent FROM guests", ttl=0)
            st.dataframe(guests_df, use_container_width=True)
            
            with st.form("update_status"):
                guest_id = st.selectbox("Select Guest ID to update", guests_df['id'].tolist())
                room_status = st.checkbox("Room Cleaned?")
                pickup_status = st.checkbox("Airport Pickup Sent?")
                if st.form_submit_button("Update Status"):
                    with conn.session as s:
                        s.execute(text("UPDATE guests SET room_cleaned = :r, airport_pickup_sent = :p WHERE id = :id"),
                                  {"r": int(room_status), "p": int(pickup_status), "id": guest_id})
                        s.commit()
                    st.success("Status updated successfully!")
                    st.rerun()

    # --- 3. ADMIN PORTAL ---
    elif mode == "Admin Portal":
        cookie_manager = stx.CookieManager()
        saved_user = cookie_manager.get(cookie="admin_user")
        
        if saved_user and not st.session_state.logged_in:
            st.session_state.logged_in = True
            st.session_state.user = saved_user
        
        # --- LOGIN SCREEN ---
        if not st.session_state.logged_in:
            st.title("🔐 Admin Login")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            remember_me = st.checkbox("Keep me logged in for 30 days")
            
            if st.button("Login"):
                admin_check = conn.query("SELECT * FROM admins WHERE username = :u AND password = :p", 
                                         params={"u": username, "p": password}, ttl=0)
                if not admin_check.empty:
                    st.session_state.logged_in = True
                    st.session_state.user = username
                    if remember_me:
                        cookie_manager.set("admin_user", username, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
                    
        # --- ADMIN AUTHORIZED AREA ---
        if st.session_state.logged_in:
            colA, colB = st.columns([8, 1])
            colA.success(f"Welcome, {st.session_state.user}!")
            if colB.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.user = ""
                st.session_state.admin_view = "search"
                cookie_manager.delete("admin_user")
                st.rerun()

            st.divider()

            # Fetch all guests into memory for Pandas filtering
            raw_df = conn.query("SELECT * FROM guests", ttl=0)
            
            # Defensive Pandas Columns (Prevents UI crashes if DB is empty or catching up)
            expected_columns = ['category', 'speaker_category', 'accompanying_persons', 'poc', 'assigned_gre', 'departure_time']
            for col in expected_columns:
                if col not in raw_df.columns:
                    raw_df[col] = None 

            if not raw_df.empty:
                raw_df['arrival_dt'] = pd.to_datetime(raw_df['arrival_time'], format='%d/%m/%Y %H:%M', errors='coerce')

            # ==========================================
            # VIEW 1: SEARCH DASHBOARD
            # ==========================================
            if st.session_state.admin_view == "search":
                st.title("🔍 Comprehensive Guest Search")
                
                # --- FILTERING UI ---
                f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
                
                with f_col1:
                    search_name = st.text_input("👤 Search by Guest Name", placeholder="Type a name...")
                
                with f_col2:
                    available_cats = [c for c in raw_df['category'].unique() if pd.notna(c)] if not raw_df.empty else []
                    selected_cats = st.multiselect("🏷️ Filter by Category", available_cats, placeholder="Select categories...")
                
                with f_col3:
                    today = datetime.date.today()
                    date_range = st.date_input("📅 Arrival Date Range", value=(today, today + datetime.timedelta(days=7)))

                # --- APPLY FILTERS LOGIC ---
                filtered_df = raw_df.copy()
                
                if not filtered_df.empty:
                    if search_name:
                        filtered_df = filtered_df[filtered_df['name'].str.contains(search_name, case=False, na=False)]
                    
                    if selected_cats:
                        filtered_df = filtered_df[filtered_df['category'].isin(selected_cats)]
                    
                    if isinstance(date_range, tuple) and len(date_range) == 2:
                        start_date, end_date = date_range
                        mask = (filtered_df['arrival_dt'].dt.date >= start_date) & (filtered_df['arrival_dt'].dt.date <= end_date)
                        filtered_df = filtered_df[mask | filtered_df['arrival_dt'].isna()]

                    st.markdown(f"**Showing {len(filtered_df)} Results**")

                    # --- SEARCH RESULTS TABLE (INTERACTIVE) ---
                    if not filtered_df.empty:
                        h_col1, h_col2, h_col3, h_col4, h_col5 = st.columns([3, 2, 2, 2, 1.5])
                        h_col1.markdown("**Guest Name**")
                        h_col2.markdown("**GRE Name**")
                        h_col3.markdown("**POC Name**")
                        h_col4.markdown("**Date of Arrival**")
                        h_col5.markdown("**Pax**")
                        st.divider()

                        for _, row in filtered_df.iterrows():
                            r_col1, r_col2, r_col3, r_col4, r_col5 = st.columns([3, 2, 2, 2, 1.5])
                            
                            with r_col1:
                                if st.button(f"👤 {row['name']}", key=f"btn_{row['id']}", use_container_width=True):
                                    st.session_state.selected_guest_id = row['id']
                                    st.session_state.admin_view = "ddp"
                                    st.rerun()
                            
                            r_col2.write(row['assigned_gre'] if pd.notna(row['assigned_gre']) else "--")
                            r_col3.write(row['poc'] if pd.notna(row['poc']) else "--")
                            r_col4.write(row['arrival_time'] if pd.notna(row['arrival_time']) else "TBD")
                            pax_val = int(row['accompanying_persons']) if pd.notna(row['accompanying_persons']) else 0
                            r_col5.write(f"+ {pax_val}")
                    else:
                        st.warning("No guests match your exact filter criteria.")
                else:
                    st.info("The database is currently empty. Please import guests below.")

                # --- ADD NEW GRE ACCOUNT ---
                st.divider()
                st.subheader("Add New GRE (Staff) Account")
                with st.form("add_gre_form"):
                    new_gre_name = st.text_input("GRE Full Name")
                    new_gre_phone = st.text_input("GRE Phone Number")
                    submit_gre = st.form_submit_button("Create GRE Account")
                    
                    if submit_gre:
                        if new_gre_name.strip():
                            with conn.session as s:
                                s.execute(
                                    text("INSERT INTO gres (gre_name, gre_phone) VALUES (:name, :phone)"),
                                    {"name": new_gre_name, "phone": new_gre_phone}
                                )
                                s.commit()
                            st.success(f"Successfully added GRE: {new_gre_name}")
                            st.rerun() 
                        else:
                            st.error("GRE Name cannot be empty.")

                # --- BULK IMPORT (CSV) ---
                st.divider()
                st.subheader("Bulk Import (CSV)")
                st.markdown("Upload a CSV with exactly 6 columns: `name`, `admin_username`, `poc`, `category`, `speaker_category`, and `accompanying_persons`")
                
                file = st.file_uploader("Upload Guest CSV", type="csv")
                if file:
                    data = pd.read_csv(file)
                    if st.button("Execute Import"):
                        with conn.session as s:
                            for _, r in data.iterrows():
                                g_name = str(r['name']).strip()
                                a_user = str(r['admin_username']).strip()
                                poc_name = str(r['poc']).strip() if 'poc' in r and pd.notna(r['poc']) else "Not Provided"
                                cat_name = str(r['category']).strip() if 'category' in r and pd.notna(r['category']) else "Uncategorized"
                                spk_cat = str(r['speaker_category']).strip() if 'speaker_category' in r and pd.notna(r['speaker_category']) else "Non-Speaker"
                                
                                try:
                                    pax_num = int(r['accompanying_persons']) if 'accompanying_persons' in r and pd.notna(r['accompanying_persons']) else 0
                                except:
                                    pax_num = 0
                                
                                s.execute(text("INSERT INTO admins (username, password) VALUES (:u, :p) ON CONFLICT DO NOTHING"),
                                          {"u": a_user, "p": "password123"})
                                
                                existing = s.execute(text("SELECT id FROM guests WHERE name = :n AND admin_owner = :u"), 
                                                     {"n": g_name, "u": a_user}).fetchone()
                                
                                if not existing:
                                    s.execute(text("""INSERT INTO guests 
                                                      (name, admin_owner, poc, category, speaker_category, accompanying_persons) 
                                                      VALUES (:n, :u, :poc, :cat, :spk, :pax)"""),
                                              {"n": g_name, "u": a_user, "poc": poc_name, "cat": cat_name, "spk": spk_cat, "pax": pax_num})
                            s.commit()
                        st.success("CSV Processed! New guests added successfully.")
                        st.rerun()

            # ==========================================
            # VIEW 2: DDP - DIGNITARY DETAILS PAGE
            # ==========================================
            elif st.session_state.admin_view == "ddp":
                guest_data = raw_df[raw_df['id'] == st.session_state.selected_guest_id].iloc[0]

                if st.button("⬅️ Back to Search Results"):
                    st.session_state.admin_view = "search"
                    st.rerun()

                st.title("DDP - Dignitary Details Page")
                st.subheader(f"Dignitary: {guest_data['name']}")
                
                info_c1, info_c2, info_c3 = st.columns(3)
                
                with info_c1:
                    st.markdown("### 🪪 Profile")
                    st.write(f"**Category:** {guest_data['category']}")
                    st.write(f"**Speaker Status:** {guest_data['speaker_category']}")
                    pax_val = int(guest_data['accompanying_persons']) if pd.notna(guest_data['accompanying_persons']) else 0
                    st.write(f"**Accompanying Pax:** {pax_val}")
                    st.write(f"**POC Name:** {guest_data['poc']}")

                with info_c2:
                    st.markdown("### ✈️ Logistics")
                    st.write(f"**Arrival:** {guest_data['arrival_time'] if pd.notna(guest_data['arrival_time']) else 'TBD'}")
                    st.write(f"**Departure:** {guest_data['departure_time'] if pd.notna(guest_data['departure_time']) else 'TBD'}")
                    st.write(f"**Admin Owner:** {guest_data['admin_owner']}")
                    st.write(f"**Assigned GRE:** {guest_data['assigned_gre'] if pd.notna(guest_data['assigned_gre']) else 'Unassigned'}")
                
                with info_c3:
                    st.markdown("### 🛎️ Ground Status")
                    room_status = "✅ Clean" if guest_data['room_cleaned'] else "❌ Dirty/Pending"
                    st.write(f"**Room Status:** {room_status}")
                    pickup_status = "🚗 Sent" if guest_data['airport_pickup_sent'] else "⏳ Pending"
                    st.write(f"**Airport Pickup:** {pickup_status}")
                    
                st.divider()
                st.info("Additional guest information modules can be added here as we expand the database.")

if __name__ == "__main__":
    main()
