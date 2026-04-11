import streamlit as st
import pandas as pd
from sqlalchemy import text
import datetime
import urllib.parse
import re
from database import conn

# --- 1. GLOBAL SILENT SAVE CALLBACKS ---
# BUG FIX: Removed st.toast() as drawing UI elements inside dialog callbacks causes blank screen crashes.
def db_update(field, widget_key, gid):
    val = st.session_state[widget_key]
    with conn.session as s:
        s.execute(text(f"UPDATE guests SET {field} = :v WHERE id = :id"), {"v": val, "id": gid})
        s.commit()

def db_update_datetime(field, date_key, time_key, gid):
    d_val = st.session_state.get(date_key)
    t_val = st.session_state.get(time_key)
    
    # SAFTEY CHECK: Do not update the DB until BOTH date and time are selected
    if not d_val or not t_val:
        return 
        
    final_dt = f"{d_val.strftime('%d/%m/%Y')} {t_val.strftime('%H:%M')}"
    with conn.session as s:
        s.execute(text(f"UPDATE guests SET {field} = :v WHERE id = :id"), {"v": final_dt, "id": gid})
        s.commit()

def update_gre_cb(widget_key, gid):
    val = st.session_state[widget_key]
    v = None if val == "-- Unassigned --" else val
    with conn.session as s:
        s.execute(text("UPDATE guests SET assigned_gre = :v WHERE id = :id"), {"v": v, "id": gid})
        s.commit()

def toggle_room_cb(k, gid):
    with conn.session as s:
        s.execute(text("UPDATE guests SET room_cleaned = :r WHERE id = :id"), {"r": int(st.session_state[k]), "id": gid})
        s.commit()
    
def toggle_pk_cb(k, gid):
    with conn.session as s:
        s.execute(text("UPDATE guests SET airport_pickup_sent = :p WHERE id = :id"), {"p": int(st.session_state[k]), "id": gid})
        s.commit()

def toggle_ashram_cb(k, gid):
    with conn.session as s:
        s.execute(text("UPDATE guests SET ashram_tour = :a WHERE id = :id"), {"a": int(st.session_state[k]), "id": gid})
        s.commit()


def parse_dt(dt_str):
    if not dt_str or pd.isna(dt_str) or str(dt_str).strip() in ["", "TBD"]:
        return datetime.date.today(), datetime.time(12, 0)
    try:
        dt_obj = datetime.datetime.strptime(str(dt_str).strip(), "%d/%m/%Y %H:%M")
        return dt_obj.date(), dt_obj.time()
    except:
        return datetime.date.today(), datetime.time(12, 0)


# --- 2. DIGNITARY DETAILS PAGE UI ---
@st.dialog("DDP - Dignitary Details Page", width="large")
def ddp_dialog(guest_data_input):
    gid = guest_data_input['id']
    
    # Stability fix: Always fetch the freshest data to prevent update loops
    try:
        fresh_df = conn.query("SELECT * FROM guests WHERE id = :id", params={"id": gid}, ttl=0)
        if not fresh_df.empty:
            guest_data = fresh_df.iloc[0].to_dict()
        else:
            guest_data = guest_data_input
    except:
        guest_data = guest_data_input

    st.subheader(f"👤 {guest_data['name']}")
    st.caption("✨ *Inline Editing Enabled: Type and press Enter or click away to save instantly.*")
    
    info_c1, info_c2, info_c3 = st.columns(3)
    
    with info_c1:
        st.markdown("### 🪪 Profile")
        
        st.text_input("Category", value=guest_data.get('category', ''), key=f"cat_{gid}", 
                      on_change=db_update, args=("category", f"cat_{gid}", gid))
        
        st.selectbox("Speaker Status", ["Speaker", "Non-Speaker"], 
                     index=0 if guest_data.get('speaker_category') == "Speaker" else 1,
                     key=f"spk_{gid}", on_change=db_update, args=("speaker_category", f"spk_{gid}", gid))
        
        st.number_input("Accompanying Pax", min_value=0, 
                        value=int(guest_data.get('accompanying_persons', 0)) if pd.notna(guest_data.get('accompanying_persons')) else 0,
                        key=f"pax_{gid}", on_change=db_update, args=("accompanying_persons", f"pax_{gid}", gid))
        
        st.text_input("POC Name", value=guest_data.get('poc', ''), key=f"poc_{gid}",
                      on_change=db_update, args=("poc", f"poc_{gid}", gid))
                      
        st.text_input("GIFT Type", value=guest_data.get('gift_type', 'Pending'), key=f"gift_{gid}",
                      on_change=db_update, args=("gift_type", f"gift_{gid}", gid))

    with info_c2:
        st.markdown("### ✈️ Logistics")
        
        st.text_input("Housing / Room", value=guest_data.get('housing', 'TBD'), key=f"hou_{gid}",
                      on_change=db_update, args=("housing", f"hou_{gid}", gid))
        
        gre_df = conn.query("SELECT gre_name FROM gres", ttl=0)
        avail_gres = ["-- Unassigned --"] + gre_df['gre_name'].tolist() if not gre_df.empty else ["-- Unassigned --"]
        current_gre = guest_data.get('assigned_gre') if pd.notna(guest_data.get('assigned_gre')) and str(guest_data.get('assigned_gre')).strip() not in ["", "None"] else "-- Unassigned --"
        if current_gre not in avail_gres: avail_gres.append(current_gre)
        
        st.selectbox("Assigned GRE", avail_gres, index=avail_gres.index(current_gre),
                     key=f"gre_{gid}", on_change=update_gre_cb, args=(f"gre_{gid}", gid))

        # --- WHATSAPP & CALLING FEATURE ---
        if current_gre != "-- Unassigned --":
            gre_query = conn.query("SELECT gre_phone FROM gres WHERE gre_name = :n", params={"n": current_gre}, ttl=0)
            if not gre_query.empty:
                raw_phone = str(gre_query.iloc[0]['gre_phone']).strip()
                if raw_phone and raw_phone.lower() not in ["none", "nan", ""]:
                    st.markdown(f"📞 **Call {current_gre}:** [{raw_phone}](tel:{raw_phone})")
                    
                    clean_phone = re.sub(r'\D', '', raw_phone) 
                    
                    arr_str = guest_data.get('arrival_time', 'TBD')
                    dep_str = guest_data.get('departure_time', 'TBD')
                    room_str = guest_data.get('housing', 'TBD')
                    poc_str = guest_data.get('poc', 'TBD')
                    pax_str = guest_data.get('accompanying_persons', 0)
                    gift_str = guest_data.get('gift_type', 'Pending')
                    ash_str = "Yes" if guest_data.get('ashram_tour') else "No"
                    
                    wa_msg = f"🛎️ *New VIP Assignment*\n\nHello {current_gre},\nYou have been assigned as the GRE for the following guest:\n\n👤 *Guest:* {guest_data['name']} (+{pax_str} Pax)\n✈️ *Arrival:* {arr_str}\n🛫 *Departure:* {dep_str}\n🏨 *Room Allotment:* {room_str}\n📞 *Guest POC:* {poc_str}\n🎁 *Gift Status:* {gift_str}\n🛕 *Ashram Tour:* {ash_str}\n\nPlease ensure everything is ready."
                    
                    wa_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(wa_msg)}"
                    st.link_button("💬 Send WhatsApp Itinerary", wa_url, use_container_width=True)
                else:
                    st.warning(f"⚠️ No phone number saved for {current_gre}.")
            else:
                st.warning(f"⚠️ GRE '{current_gre}' not found in the GRE database.")

        st.divider()
        
        # --- ARRIVAL TIME LOGIC ---
        arr_str = guest_data.get('arrival_time')
        if not arr_str or str(arr_str).strip() in ["", "None", "TBD", "nan"]:
            st.warning("⚠️ Date of Arrival: **Not Assigned**")
            with st.expander("➕ Assign Arrival Date & Time"):
                c_arr1, c_arr2 = st.columns(2)
                c_arr1.date_input("Arrival Date", value=None, key=f"arr_d_{gid}", on_change=db_update_datetime, args=("arrival_time", f"arr_d_{gid}", f"arr_t_{gid}", gid))
                c_arr2.time_input("Arrival Time", value=None, key=f"arr_t_{gid}", on_change=db_update_datetime, args=("arrival_time", f"arr_d_{gid}", f"arr_t_{gid}", gid))
        else:
            arr_d, arr_t = parse_dt(arr_str)
            c_arr1, c_arr2 = st.columns(2)
            c_arr1.date_input("Arrival Date", value=arr_d, format="DD/MM/YYYY", key=f"arr_d_{gid}", on_change=db_update_datetime, args=("arrival_time", f"arr_d_{gid}", f"arr_t_{gid}", gid))
            c_arr2.time_input("Time", value=arr_t, key=f"arr_t_{gid}", on_change=db_update_datetime, args=("arrival_time", f"arr_d_{gid}", f"arr_t_{gid}", gid))

        # --- DEPARTURE TIME LOGIC ---
        dep_str = guest_data.get('departure_time')
        if not dep_str or str(dep_str).strip() in ["", "None", "TBD", "nan"]:
            st.warning("⚠️ Date of Departure: **Not Assigned**")
            with st.expander("➕ Assign Departure Date & Time"):
                c_dep1, c_dep2 = st.columns(2)
                c_dep1.date_input("Departure Date", value=None, key=f"dep_d_{gid}", on_change=db_update_datetime, args=("departure_time", f"dep_d_{gid}", f"dep_t_{gid}", gid))
                c_dep2.time_input("Departure Time", value=None, key=f"dep_t_{gid}", on_change=db_update_datetime, args=("departure_time", f"dep_d_{gid}", f"dep_t_{gid}", gid))
        else:
            dep_d, dep_t = parse_dt(dep_str)
            c_dep1, c_dep2 = st.columns(2)
            c_dep1.date_input("Departure Date", value=dep_d, format="DD/MM/YYYY", key=f"dep_d_{gid}", on_change=db_update_datetime, args=("departure_time", f"dep_d_{gid}", f"dep_t_{gid}", gid))
            c_dep2.time_input("Time", value=dep_t, key=f"dep_t_{gid}", on_change=db_update_datetime, args=("departure_time", f"dep_d_{gid}", f"dep_t_{gid}", gid))

    with info_c3:
        st.markdown("### 🛎️ Ground Status")
        
        st.toggle("Room Cleaned", value=bool(guest_data.get('room_cleaned', 0)), key=f"ddp_rm_{gid}", on_change=toggle_room_cb, args=(f"ddp_rm_{gid}", gid))
        st.toggle("Pickup Sent", value=bool(guest_data.get('airport_pickup_sent', 0)), key=f"ddp_pk_{gid}", on_change=toggle_pk_cb, args=(f"ddp_pk_{gid}", gid))
        st.toggle("Ashram Tour", value=bool(guest_data.get('ashram_tour', 0)), key=f"ddp_ash_{gid}", on_change=toggle_ashram_cb, args=(f"ddp_ash_{gid}", gid))

        st.divider()
        st.info(f"**Admin Owner:** {guest_data.get('admin_owner', 'System')}")
        
        # --- NEW: HOUSING CONTACT ---
        st.markdown("### 🏨 Housing Support")
        st.markdown("📞 **Call Housing:** [9699372475](tel:9699372475)")

# --- 3. BATCH ACTIONS DIALOG ---
@st.dialog("🛠️ Batch Actions", width="medium")
def batch_actions_dialog(selected_ids):
    st.write(f"**Applying changes to {len(selected_ids)} selected guests.**")

    gre_df = conn.query("SELECT gre_name FROM gres", ttl=0)
    avail_gres = ["-- No Change --"] + gre_df['gre_name'].tolist() if not gre_df.empty else ["-- No Change --"]
    
    batch_gre = st.selectbox("Assign GRE", avail_gres)
    batch_room = st.selectbox("Update Room", ["-- No Change --", "Mark Cleaned", "Mark Dirty/Pending"])
    batch_pickup = st.selectbox("Update Pickup", ["-- No Change --", "Mark Sent", "Mark Pending"])

    if st.button("Apply Changes", type="primary", use_container_width=True):
        with conn.session as s:
            for gid in selected_ids:
                if batch_gre != "-- No Change --":
                    s.execute(text("UPDATE guests SET assigned_gre = :g WHERE id = :id"), {"g": batch_gre, "id": gid})
                if batch_room != "-- No Change --":
                    r_val = 1 if batch_room == "Mark Cleaned" else 0
                    s.execute(text("UPDATE guests SET room_cleaned = :r WHERE id = :id"), {"r": r_val, "id": gid})
                if batch_pickup != "-- No Change --":
                    p_val = 1 if batch_pickup == "Mark Sent" else 0
                    s.execute(text("UPDATE guests SET airport_pickup_sent = :p WHERE id = :id"), {"p": p_val, "id": gid})
            s.commit()
        st.success(f"Updated {len(selected_ids)} guests!")
        
        for gid in selected_ids:
            st.session_state[f"chk_{gid}"] = False
        st.rerun()
