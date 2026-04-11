import streamlit as st
from sqlalchemy import text

# --- INITIALIZE BUILT-IN SQL CONNECTION ---
conn = st.connection("postgresql", type="sql")

def init_db():
    """Ensure tables exist in Supabase and update them if needed"""
    with conn.session as s:
        s.execute(text('CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY, password TEXT);'))
        s.execute(text('CREATE TABLE IF NOT EXISTS gres (gre_id SERIAL PRIMARY KEY, gre_name TEXT, gre_phone TEXT);'))
        # Add the new POCs table here:
        s.execute(text('CREATE TABLE IF NOT EXISTS pocs (poc_id SERIAL PRIMARY KEY, poc_name TEXT UNIQUE, poc_phone TEXT);'))
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
                poc TEXT,
                housing TEXT DEFAULT 'TBD',
                gift_type TEXT DEFAULT 'Pending',
                ashram_tour INTEGER DEFAULT 0
            );
        '''))
        s.commit() 

    # --- FORCE SPEAKER CATEGORY TO TEXT ---
    with conn.session as s:
        try:
            s.execute(text("ALTER TABLE guests ALTER COLUMN speaker_category TYPE TEXT USING speaker_category::text;"))
            s.commit()
        except Exception:
            s.rollback()

    # --- ISOLATED TRANSACTIONS WITH ROLLBACKS ---
    columns_to_add = [
        ("departure_time", "TEXT"),
        ("poc", "TEXT"),
        ("assigned_gre", "TEXT"),
        ("category", "TEXT"),
        ("speaker_category", "TEXT"),
        ("accompanying_persons", "INTEGER DEFAULT 0"),
        ("housing", "TEXT DEFAULT 'TBD'"),
        ("gift_type", "TEXT DEFAULT 'Pending'"),
        ("ashram_tour", "INTEGER DEFAULT 0")
    ]
    
    for col_name, col_type in columns_to_add:
        with conn.session as s:
            try:
                s.execute(text(f"ALTER TABLE guests ADD COLUMN {col_name} {col_type};"))
                s.commit()
            except Exception:
                s.rollback()
