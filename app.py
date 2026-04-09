import streamlit as st
import pandas as pd
from sqlalchemy import text

# --- INITIALIZE BUILT-IN SQL CONNECTION ---
conn = st.connection("postgresql", type="sql")

def init_db():
    """Ensure tables exist in Supabase"""
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
                assigned_gre_id INTEGER
            );
        '''))
        # This safely adds the departure column to your existing table without wiping your data
        try:
            s.execute(text("ALTER TABLE guests ADD COLUMN departure_time TEXT;"))
        except Exception:
            pass 
        s.commit()

# --- APP UI ---
def main():
    st.set_page_config(page_title="Dignitary Management System", layout="wide")
    init_db()

    if "logged_in" not in st.session_state: st.session_state.logged_in = False

    st.sidebar.title("🛂 Event Control")
    mode = st.sidebar.radio("Navigate to:", ["Public Search", "Staff Portal (GRE)", "Admin Portal"])

    # --- 1. PUBLIC SEARCH ---
    if mode == "Public Search":
        st.title("🔍 Guest Inquiry")
        search = st.text_input("Enter Guest Name")
        if search:
            query = "SELECT name, arrival_time, stay_location FROM guests WHERE name ILIKE :name"
            res = conn.query(query, params={"name": f"%{search}%"}, ttl=0)
            st.dataframe(res, use_container_width=True)

    # --- 2. STAFF PORTAL (LIVE STATUS UPDATES) ---
    elif mode == "Staff Portal (GRE)":
        st.title("📱 GRE Live Update Portal")
        gre_name = st.text_input("Enter your Registered GRE Name")
        
        if gre_name:
            # Check if GRE exists
            gre_data = conn.query("SELECT gre_id FROM gres WHERE gre_name = :name", params={"name": gre_name}, ttl=0)
            
            if not gre_data.empty:
                gre_id = int(gre_data.iloc[0]['gre_id'])
                st.success(f"Verified: {gre_name}")
                
                # Fetch assigned guests
                guests = conn.query("SELECT * FROM guests WHERE assigned_gre_id = :id", params={"id": gre_id}, ttl=0)
                
                for _, row in guests.iterrows():
                    with st.expander(f"Guest: {row['name']}", expanded=True):
                        c1, c2 = st.columns(2)
                        p_check = c1.checkbox("Pickup Done", value=bool(row['airport_pickup_sent']), key=f"p{row['id']}")
                        r_check = c2.checkbox("Room Ready", value=bool(row['room_cleaned']), key=f"r{row['id']}")
                        
                        if st.button("Sync Changes", key=f"btn{row['id']}"):
                            with conn.session as s:
                                s.execute(text("UPDATE guests SET airport_pickup_sent = :p, room_cleaned = :r WHERE id = :id"),
                                          {"p": int(p_check), "r": int(r_check), "id": row['id']})
                                s.commit()
                            st.toast("Updated successfully!")
                            st.rerun()
            else:
                st.error("GRE Name not recognized.")

    # --- 3. ADMIN PORTAL ---
    elif mode == "Admin Portal":
        if st.session_state.logged_in:
            st.success(f"Welcome, {st.session_state.user}!")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.user = ""
                st.rerun()

            st.divider()

            # --- 1. VIEW TOGGLE & FETCH DATA ---
            view_mode = st.radio("Display Mode:", ["Only your guests", "All guests"], horizontal=True)

            if view_mode == "Only your guests":
                df = conn.query("SELECT * FROM guests WHERE admin_owner = :u", params={"u": st.session_state.user}, ttl=0)
            else:
                df = conn.query("SELECT * FROM guests", ttl=0)

            if not df.empty:
                df['arrival_dt'] = pd.to_datetime(df['arrival_time'], format='%d/%m/%Y %H:%M', errors='coerce')
                df = df.sort_values(by='arrival_dt', ascending=True, na_position='last')

                # --- 2. TODAY'S ARRIVAL ALERTS ---
                today = pd.Timestamp.now().date()
                today_guests = df[df['arrival_dt'].dt.date == today]

                if not today_guests.empty:
                    st.subheader("🚨 Today's Arrivals - Action Required")
                    for _, guest in today_guests.iterrows():
                        arr_time = guest['arrival_dt'].strftime('%H:%M') if pd.notnull(guest['arrival_dt']) else "Unknown Time"
                        if guest['room_cleaned'] == 0:
                            st.error(f"⚠️ **{guest['name']}** arrives today at {arr_time}. **Room is NOT clean!**")
                        else:
                            st.success(f"✅ **{guest['name']}** arrives today at {arr_time}. Room is clean.")
                    st.divider()

                # --- 3. DASHBOARD METRICS & TABLE ---
                st.subheader("Guest Overview")
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Guests (in view)", len(df))
                m2.metric("Pickups Pending", len(df[df['airport_pickup_sent'] == 0]))
                m3.metric("Rooms Unclean", len(df[df['room_cleaned'] == 0]))
                
                display_df = df.drop(columns=['arrival_dt'])
                st.dataframe(display_df, use_container_width=True)

                # --- 4. NEW: MANAGE GUEST ITINERARIES ---
                st.divider()
                st.subheader("📅 Manage Guest Itineraries")
                
                # Create a list of guest names for the dropdown
                guest_list = df['name'].tolist()
                selected_guest = st.selectbox("Select a Guest to Assign Times:", ["-- Select Guest --"] + guest_list)
                
                if selected_guest != "-- Select Guest --":
                    with st.form("update_times_form"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write("**Arrival**")
                            arr_date = st.date_input("Arrival Date", format="DD/MM/YYYY")
                            arr_time = st.time_input("Arrival Time")
                        with c2:
                            st.write("**Departure**")
                            dep_date = st.date_input("Departure Date", format="DD/MM/YYYY")
                            dep_time = st.time_input("Departure Time")
                            
                        if st.form_submit_button("Save Itinerary"):
                            # Format to match our existing logic (DD/MM/YYYY HH:MM)
                            f_arr = f"{arr_date.strftime('%d/%m/%Y')} {arr_time.strftime('%H:%M')}"
                            f_dep = f"{dep_date.strftime('%d/%m/%Y')} {dep_time.strftime('%H:%M')}"
                            
                            with conn.session as s:
                                s.execute(
                                    text("UPDATE guests SET arrival_time = :a, departure_time = :d WHERE name = :n"),
                                    {"a": f_arr, "d": f_dep, "n": selected_guest}
                                )
                                s.commit()
                            st.success(f"Successfully saved itinerary for {selected_guest}!")
                            st.rerun()
            else:
                st.info("No guests found in this view.")

            # --- 5. BULK IMPORT (CSV) - SIMPLIFIED ---
            st.divider()
            st.subheader("Bulk Import (CSV)")
            st.markdown("Upload a CSV with exactly 2 columns: `name` and `admin_username`")
            
            file = st.file_uploader("Upload Guest CSV", type="csv")
            if file:
                data = pd.read_csv(file)
                if st.button("Execute Import"):
                    with conn.session as s:
                        for _, r in data.iterrows():
                            # Auto-create Admin with default password
                            s.execute(text("INSERT INTO admins (username, password) VALUES (:u, :p) ON CONFLICT DO NOTHING"),
                                      {"u": str(r['admin_username']), "p": "password123"})
                            
                            # Insert Guest (Arrival/Departure remain blank until assigned in app)
                            s.execute(text("INSERT INTO guests (name, admin_owner) VALUES (:n, :u)"),
                                      {"n": str(r['name']), "u": str(r['admin_username'])})
                        s.commit()
                    st.success("CSV Processed! Guests added. Assign their arrival times in the panel above.")
                    st.rerun()

if __name__ == "__main__":
    main()
