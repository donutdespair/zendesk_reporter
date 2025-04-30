# utils/data_processing.py
import pandas as pd
from .zendesk_api import fetch_user_details
import streamlit as st
import datetime as dt
import pytz
from business_duration import businessDuration # Needs to be installed
from io import StringIO # Needed for debug block capture

# --- Custom Field ID and Helper Functions ---
ROOT_CAUSE_FIELD_ID = 22475179409933
def classify_requester(email): # ... (no change) ...
    internal_domain = '@murmuration.org';
    if isinstance(email, str) and email.lower().endswith(internal_domain): return 'Internal'
    elif pd.isna(email) or not isinstance(email, str) or email.strip() == '': return 'Unknown'
    else: return 'External'
def get_custom_field_value(custom_fields_list, target_field_id): # ... (no change) ...
    if not isinstance(custom_fields_list, list): return None
    for field in custom_fields_list:
        if isinstance(field, dict) and field.get('id') == target_field_id: return field.get('value')
    return None

# --- Define FINAL state custom status IDs ---
# List of Custom Status IDs (as STRINGS) that represent a final solved/closed state
# !! Add your 'Closed' custom status ID string here if applicable !!
SOLVED_CLOSED_CUSTOM_IDS = ['2565572'] # Currently only includes 'solved' ID '2565572'


# --- FULL UPDATED FUNCTION ---
def process_ticket_data(raw_ticket_data, raw_event_data):
    """
    Cleans, transforms, and enriches raw ticket data from Incremental API.
    Uses ticket event data looking for specific CUSTOM status IDs for solved_at time.
    Calculates Resolution Time (Business Hours & Calendar). Adds requester type and root cause.
    """
    if not raw_ticket_data: return pd.DataFrame()
    try: df = pd.DataFrame(raw_ticket_data)
    except Exception as e: st.error(f"Error creating DataFrame: {e}"); return pd.DataFrame()
    if df.empty: return df

    # --- Subject Filter ---
    if 'subject' in df.columns: # ... (subject filter logic) ...
        original_count = df.shape[0]; df = df[df['subject'].ne("SCRUBBED")].copy();
        # if df.shape[0] < original_count: st.write(...)
    if df.empty: st.warning("No tickets remaining after filtering."); return df

    # --- Basic Processing ---
    datetime_cols = ['created_at', 'updated_at'];
    for col in datetime_cols:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)

    relevant_cols = [
        'id', 'subject', 'description', 'status', 'custom_status_id',
        'priority', 'type','requester_id', 'assignee_id', 'organization_id', 'group_id',
        'created_at', 'updated_at', 'tags','custom_fields'
    ]
    existing_relevant_cols = [col for col in relevant_cols if col in df.columns]
    df_processed = df[existing_relevant_cols].copy()

    if 'custom_status_id' in df_processed.columns:
        df_processed['custom_status_id'] = pd.to_numeric(df_processed['custom_status_id'], errors='coerce')
    else: df_processed['custom_status_id'] = pd.NA


    # --- Process Events to find Solved Times ---
    solved_times = {}
    if raw_event_data:
        remaining_ticket_ids = set(df_processed['id'].tolist())
        relevant_event_data = [event for event in raw_event_data if event.get('ticket_id') in remaining_ticket_ids]
        for event in relevant_event_data: # Use corrected logic checking custom_status_id key
            child_events = event.get('child_events', [])
            if not isinstance(child_events, list): continue
            for child in child_events:
                 is_change_event = child.get('event_type') == 'Change'
                 is_final_custom_status = str(child.get('custom_status_id')) in SOLVED_CLOSED_CUSTOM_IDS
                 if is_change_event and is_final_custom_status:
                    ticket_id = event.get('ticket_id'); event_timestamp_str = event.get('timestamp')
                    if ticket_id and event_timestamp_str:
                        try:
                            event_dt = pd.to_datetime(event_timestamp_str, unit='s', errors='coerce', utc=True)
                            if pd.notna(event_dt):
                                if ticket_id not in solved_times or event_dt > solved_times[ticket_id]: solved_times[ticket_id] = event_dt
                        except (ValueError, TypeError): pass
        df_processed['solved_at_derived'] = pd.to_datetime(df_processed['id'].map(solved_times), errors='coerce', utc=True)
    else: df_processed['solved_at_derived'] = pd.NaT
    try: # Ensure tz aware even if NaT
         if df_processed['solved_at_derived'].dt.tz is None: df_processed['solved_at_derived'] = df_processed['solved_at_derived'].dt.tz_localize('UTC')
    except AttributeError: df_processed['solved_at_derived'] = pd.to_datetime(df_processed['solved_at_derived'], utc=True)


    # --- DEBUG block (Optional - can be removed) ---
    # st.divider(); st.subheader("--- DEBUG: Before Business Hour Calc ---")
    # if 'created_at' in df_processed.columns and 'solved_at_derived' in df_processed.columns:
    #     st.dataframe(df_processed[['id', 'created_at', 'solved_at_derived']].head(10))
    #     buffer = StringIO(); df_processed[['created_at', 'solved_at_derived']].info(buf=buffer); info_str = buffer.getvalue(); st.text(info_str)
    #     created_valid_count = df_processed['created_at'].notna().sum(); solved_valid_count = df_processed['solved_at_derived'].notna().sum()
    #     st.write(f"Valid 'created_at' count: {created_valid_count}"); st.write(f"Valid 'solved_at_derived' count: {solved_valid_count}")
    # else: st.warning("Columns missing for debug check.")
    # st.write("--- END DEBUG ---"); st.divider()


    # --- CALCULATE BUSINESS HOURS RESOLUTION TIME ---
    st.write("Calculating resolution time in business hours (Mon-Fri, 9am-8pm ET)...")
    business_start_time = dt.time(9, 0, 0); business_end_time = dt.time(20, 0, 0)
    business_timezone = pytz.timezone('America/New_York'); weekend_list = [5, 6]
    df_processed['resolution_time_business_hours'] = pd.NA
    df_processed['resolution_time_business_hours'] = pd.to_numeric(df_processed['resolution_time_business_hours'], errors='coerce')
    calc_mask = df_processed['created_at'].notna() & df_processed['solved_at_derived'].notna()
    df_calc = df_processed[calc_mask].copy()

    business_hours_series = pd.Series(dtype='float64') # Initialize empty series

    if not df_calc.empty:
        solved_count_for_calc = len(df_calc)
        calculated_count = 0; failed_count = 0
        error_print_count = 0; max_error_prints = 5

        def calculate_single_business_duration(row): # Uses corrected keywords
            nonlocal calculated_count, failed_count, error_print_count
            row_id = row['id']; start_date_val = row['created_at']; end_date_val = row['solved_at_derived']
            try:
                start_date_local = start_date_val.tz_convert(business_timezone)
                end_date_local = end_date_val.tz_convert(business_timezone)
                duration = businessDuration(
                    startdate=start_date_local, enddate=end_date_local,
                    starttime=business_start_time, endtime=business_end_time,
                    weekendlist=weekend_list, holidaylist=None, unit='hour'
                )
                calculated_count +=1; return duration if pd.notna(duration) else pd.NA
            except Exception as e:
                failed_count += 1
                if error_print_count < max_error_prints: print(f"WARN: BH calc failed Tkt {row_id}: {type(e).__name__} - {e}"); error_print_count += 1
                return pd.NA

        business_hours_series = df_calc.apply(calculate_single_business_duration, axis=1)
        df_processed.loc[calc_mask, 'resolution_time_business_hours'] = business_hours_series
        df_processed.loc[df_processed['resolution_time_business_hours'] < 0, 'resolution_time_business_hours'] = pd.NA
        # Turn off summary message by default for cleaner UI
        # st.write(f"BH calculated: {calculated_count}/{solved_count_for_calc}. Errors: {failed_count}.")
    # else: st.write("No tickets with valid dates for business hour calculation.") # Also off

    # --- Keep Calendar Hour Calculation ---
    if 'solved_at_derived' in df_processed.columns and 'created_at' in df_processed.columns: # ... (calendar hour logic) ...
        if pd.api.types.is_datetime64_any_dtype(df_processed['solved_at_derived']) and pd.api.types.is_datetime64_any_dtype(df_processed['created_at']):
            df_processed['resolution_time_calendar_hours'] = (df_processed['solved_at_derived'] - df_processed['created_at']).dt.total_seconds() / 3600; df_processed.loc[df_processed['resolution_time_calendar_hours'] < 0] = pd.NA; df_processed['resolution_time_calendar_hours'] = df_processed['resolution_time_calendar_hours'].fillna(pd.NA)
        else: df_processed['resolution_time_calendar_hours'] = pd.NA
    else: df_processed['resolution_time_calendar_hours'] = pd.NA


    # --- Add Requester Type ---
    if 'requester_id' in df_processed.columns: # ... (requester type logic) ...
        unique_requester_ids = df_processed['requester_id'].dropna().astype(int).unique().tolist()
        if unique_requester_ids:
            user_details_map = fetch_user_details(unique_requester_ids);
            if user_details_map: df_processed['requester_email'] = df_processed['requester_id'].map(lambda uid: user_details_map.get(int(uid), {}).get('email') if pd.notna(uid) else None)
            else: df_processed['requester_email'] = None
            df_processed['requester_type'] = df_processed['requester_email'].apply(classify_requester)
        else: df_processed['requester_email'] = None; df_processed['requester_type'] = 'Unknown'
    else: df_processed['requester_email'] = None; df_processed['requester_type'] = 'Unknown'


    # --- Extract Root Cause ---
    try: # ... (root cause logic with try/except) ...
        if 'custom_fields' in df_processed.columns:
            df_processed['root_cause'] = df_processed['custom_fields'].apply(lambda cf_list: get_custom_field_value(cf_list, ROOT_CAUSE_FIELD_ID)); df_processed['root_cause'] = df_processed['root_cause'].fillna('Not Specified')
        else: df_processed['root_cause'] = 'Unknown'
    except Exception as e: st.error(f"Error processing Root Cause: {e}."); df_processed['root_cause'] = 'Error Processing'

    return df_processed