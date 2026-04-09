import streamlit as st
import pandas as pd
from sqlalchemy import text
import extra_streamlit_components as stx
import datetime
import streamlit.components.v1 as components

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
                assigned_gre_id INTEGER,
                poc TEXT
            );
        '''))
        # Safely adds the departure column to your existing table without wiping your data
        try:
            s.execute(text("ALTER TABLE guests ADD COLUMN departure_time TEXT;"))
        except Exception:
            pass 
        # Safely adds the POC column to your existing table
        try:
            s.execute(text("ALTER TABLE guests ADD COLUMN poc TEXT;"))
        except Exception:
            pass 
        s.commit()

# --- APP UI ---
def main():
    st.set_page_config(page_title="Dignitary Management System", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: 
        st.session_state.logged_in = False
        st.session_state.user = ""

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
                st.error("GRE account not found. Please contact an Admin to create your account.")
                
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
        # Initialize Cookie Manager
        cookie_manager = stx.CookieManager()
        
        # Check if they already have a valid cookie from a previous day
        saved_user = cookie_manager.get(cookie="admin_user")
        if saved_user and not st.session_state.logged_in:
            st.session_state.logged_in = True
            st.session_state.user = saved_user
        
        # --- LOGIN SCREEN ---
        if not st.session_state.logged_in:
            st.title("🔐 Admin Login")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            
            # The new checkbox
            remember_me = st.checkbox("Keep me logged in for 30 days")
            
            if st.button("Login"):
                admin_check = conn.query("SELECT * FROM admins WHERE username = :u AND password = :p", 
                                         params={"u": username, "p": password}, ttl=0)
                if not admin_check.empty:
                    st.session_state.logged_in = True
                    st.session_state.user = username
                    
                    # Set the cookie if they checked the box
                    if remember_me:
                        cookie_manager.set("admin_user", username, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
                    
        # --- ADMIN DASHBOARD ---
        if st.session_state.logged_in:
            st.success(f"Welcome, {st.session_state.user}!")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.user = ""
                cookie_manager.delete("admin_user") # Destroy the cookie on logout
                st.rerun()

            st.divider()

            # --- FETCH DATA ---
            view_mode = st.radio("Display Mode:", ["Only your guests", "All guests"], horizontal=True)

            if view_mode == "Only your guests":
                df = conn.query("SELECT * FROM guests WHERE admin_owner = :u", params={"u": st.session_state.user}, ttl=0)
            else:
                df = conn.query("SELECT * FROM guests", ttl=0)

            if not df.empty:
                df['arrival_dt'] = pd.to_datetime(df['arrival_time'], format='%d/%m/%Y %H:%M', errors='coerce')
                df = df.sort_values(by='arrival_dt', ascending=True, na_position='last')

                # --- MOBILE UPGRADE 1: METRICS AT THE TOP ---
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Guests", len(df))
                m2.metric("Pickups Pending", len(df[df['airport_pickup_sent'] == 0]))
                m3.metric("Rooms Unclean", len(df[df['room_cleaned'] == 0]))
                st.divider()

                # --- TODAY'S ARRIVAL ALERTS ---
                today = pd.Timestamp.now().date()
                today_guests = df[df['arrival_dt'].dt.date == today]

                if not today_guests.empty:
                    st.subheader("🚨 Today's Arrivals")
                    for _, guest in today_guests.iterrows():
                        arr_time = guest['arrival_dt'].strftime('%H:%M') if pd.notnull(guest['arrival_dt']) else "Unknown Time"
                        if guest['room_cleaned'] == 0:
                            st.error(f"⚠️ **{guest['name']}** arrives at {arr_time}. **Room NOT clean!**")
                        else:
                            st.success(f"✅ **{guest['name']}** arrives at {arr_time}. Room is clean.")
                    st.divider()

                # --- MOBILE UPGRADE 2: SMART SEARCH & EXPANDABLE CARDS ---
                st.subheader("📱 Guest Roster")
                
                # The New Smart Search Bar
                guest_names = df['name'].tolist()
                searched_guest = st.selectbox("🔍 Search to auto-open a guest's card:", ["-- View All --"] + guest_names)

                st.markdown("*Tap any card below to expand manually:*")
                
                for _, guest in df.iterrows():
                    # Handle blank arrival times gracefully
                    arr_str = guest['arrival_time'] if pd.notna(guest['arrival_time']) else "Time TBD"
                    
                    # Check if this is the searched guest
                    is_expanded = (searched_guest == guest['name'])
                    
                    # INJECT INVISIBLE ANCHOR TARGET
                    st.markdown(f"<div id='guest-{guest['id']}'></div>", unsafe_allow_html=True)
                    
                    # Create the expandable card
                    with st.expander(f"👤 {guest['name']} | Arr: {arr_str}", expanded=is_expanded):
                        st.write(f"**Assigned Admin:** {guest['admin_owner']}")
                        st.write(f"**Departure:** {guest['departure_time'] if pd.notna(guest['departure_time']) else 'TBD'}")
                        
                        # --- DISPLAY POC AND GRE ---
                        display_poc = guest['poc'] if 'poc' in guest and pd.notna(guest['poc']) else 'None'
                        display_gre = guest['assigned_gre_id'] if pd.notna(guest['assigned_gre_id']) else 'Unassigned'
                        
                        st.write(f"**POC:** {display_poc}")
                        st.write(f"**Assigned GRE (ID):** {display_gre}")
                        
                        st.markdown("**Quick Actions:**")
                        c1, c2 = st.columns(2)
                        
                        # One-Tap Toggle: Room Cleaned
                        with c1:
                            room_val = bool(guest['room_cleaned'])
                            new_room = st.toggle("Room Cleaned", value=room_val, key=f"rm_{guest['id']}")
                            if new_room != room_val:
                                with conn.session as s:
                                    s.execute(text("UPDATE guests SET room_cleaned = :r WHERE id = :id"), 
                                              {"r": int(new_room), "id": guest['id']})
                                    s.commit()
                                st.rerun() 

                        # One-Tap Toggle: Airport Pickup
                        with c2:
                            pickup_val = bool(guest['airport_pickup_sent'])
                            new_pickup = st.toggle("Pickup Sent", value=pickup_val, key=f"pk_{guest['id']}")
                            if new_pickup != pickup_val:
                                with conn.session as s:
                                    s.execute(text("UPDATE guests SET airport_pickup_sent = :p WHERE id = :id"), 
                                              {"p": int(new_pickup), "id": guest['id']})
                                    s.commit()
                                st.rerun() 

                    # --- TRIGGER AUTO-SCROLL JAVASCRIPT ---
                    if is_expanded:
                        components.html(
                            f"""
                            <script>
                                var element = window.parent.document.getElementById('guest-{guest['id']}');
                                if (element) {{
                                    element.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                                }}
                            </script>
                            """,
                            height=0
                        )

                # --- MANAGE GUEST ITINERARIES ---
                st.divider()
                st.subheader("📅 Manage Guest Itineraries")
                
                selected_guest_itin = st.selectbox("Select a Guest to Assign Times:", ["-- Select Guest --"] + guest_names, key="itin_select")
                
                if selected_guest_itin != "-- Select Guest --":
                    with st.form("update_times_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**Arrival**")
                            arr_date = st.date_input("Arrival Date", format="DD/MM/YYYY")
                            arr_time = st.time_input("Arrival Time")
                        with col2:
                            st.write("**Departure**")
                            dep_date = st.date_input("Departure Date", format="DD/MM/YYYY")
                            dep_time = st.time_input("Departure Time")
                            
                        if st.form_submit_button("Save Itinerary"):
                            f_arr = f"{arr_date.strftime('%d/%m/%Y')} {arr_time.strftime('%H:%M')}"
                            f_dep = f"{dep_date.strftime('%d/%m/%Y')} {dep_time.strftime('%H:%M')}"
                            
                            with conn.session as s:
                                s.execute(
                                    text("UPDATE guests SET arrival_time = :a, departure_time = :d WHERE name = :n"),
                                    {"a": f_arr, "d": f_dep, "n": selected_guest_itin}
                                )
                                s.commit()
                            st.success(f"Successfully saved itinerary for {selected_guest_itin}!")
                            st.rerun()
            else:
                st.info("No guests found in this view.")

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
            st.markdown("Upload a CSV with exactly 3 columns: `name`, `admin_username`, and `poc`")
            
            file = st.file_uploader("Upload Guest CSV", type="csv")
            if file:
                data = pd.read_csv(file)
                if st.button("Execute Import"):
                    with conn.session as s:
                        for _, r in data.iterrows():
                            # Clean up strings to prevent whitespace issues causing duplicates
                            g_name = str(r['name']).strip()
                            a_user = str(r['admin_username']).strip()
                            poc_name = str(r['poc']).strip() if 'poc' in r and pd.notna(r['poc']) else "Not Provided"
                            
                            # Auto-create Admin with default password 'password123'
                            s.execute(text("INSERT INTO admins (username, password) VALUES (:u, :p) ON CONFLICT DO NOTHING"),
                                      {"u": a_user, "p": "password123"})
                            
                            # Check if this guest already exists in the database
                            existing = s.execute(text("SELECT id FROM guests WHERE name = :n AND admin_owner = :u"), 
                                                 {"n": g_name, "u": a_user}).fetchone()
                            
                            # Only insert if they DO NOT exist yet
                            if not existing:
                                s.execute(text("INSERT INTO guests (name, admin_owner, poc) VALUES (:n, :u, :poc)"),
                                          {"n": g_name, "u": a_user, "poc": poc_name})
                        s.commit()
                    st.success("CSV Processed! New guests added with their POCs.")
                    st.rerun()

if __name__ == "__main__":
    main()
