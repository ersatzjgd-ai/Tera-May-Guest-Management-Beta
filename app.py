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
                airport_pickup_sent INTEGER DEFAULT 0,
                stay_location TEXT,
                room_cleaned INTEGER DEFAULT 0,
                assigned_gre_id INTEGER
            );
        '''))
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
        if not st.session_state.logged_in:
            st.subheader("Admin Login")
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.button("Login"):
                check = conn.query("SELECT * FROM admins WHERE username=:u AND password=:p", params={"u":u, "p":p}, ttl=0)
                if not check.empty:
                    st.session_state.logged_in = True
                    st.session_state.user = u
                    st.rerun()
                else: st.error("Access Denied")
        else:
            st.sidebar.button("Logout", on_click=lambda: st.session_state.update({"logged_in": False}))
            st.title(f"📊 Dashboard: {st.session_state.user}")
            
            # Dashboard Metrics
            df = conn.query("SELECT * FROM guests WHERE admin_owner = :u", params={"u": st.session_state.user}, ttl=0)
            
            if not df.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Dignitaries", len(df))
                m2.metric("Pickups Pending", len(df[df['airport_pickup_sent'] == 0]))
                m3.metric("Rooms Unclean", len(df[df['room_cleaned'] == 0]))
                st.dataframe(df, use_container_width=True)
            
            st.divider()
            st.subheader("Bulk Import (CSV)")
            file = st.file_uploader("Upload CSV", type="csv")
            if file:
                data = pd.read_csv(file)
                if st.button("Execute Import"):
                    with conn.session as s:
                        for _, r in data.iterrows():
                            # Create Admin
                            s.execute(text("INSERT INTO admins (username, password) VALUES (:u, :p) ON CONFLICT DO NOTHING"),
                                      {"u": r['admin_username'], "p": str(r['admin_password'])})
                            # Create Guest
                            s.execute(text("INSERT INTO guests (name, admin_owner) VALUES (:n, :u)"),
                                      {"n": r['name'], "u": r['admin_username']})
                        s.commit()
                    st.success("CSV Processed and Sync'd to Cloud Database.")

if __name__ == "__main__":
    main()
