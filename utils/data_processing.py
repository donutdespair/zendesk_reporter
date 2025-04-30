# utils/data_processing.py
import pandas as pd
# Import the user fetching function (relative import within the package)
from .zendesk_api import fetch_user_details # fetch_recent_ticket_events_cached is called in dashboard.py now
import streamlit as st # For displaying warnings/errors
import datetime as dt # Import datetime module
import pytz           # Import pytz for timezone handling
# --- Use standard direct import for business_duration ---
from business_duration import businessDuration # Import the specific function directly
# Import StringIO for capturing df.info() in debug block if re-enabled
from io import StringIO

# --- Custom Field ID and Helper Functions ---
ROOT_CAUSE_FIELD_ID = 22475179409933 # Make sure this is the correct ID

def classify_requester(email):
    """Classifies email as Internal or External based on domain."""
    internal_domain = '@murmuration.org' # Define your internal domain here
    if isinstance(email, str) and email.lower().endswith(internal_domain):
        return 'Internal'
    # Check for NaN, None, empty strings, or non-string types
    elif pd.isna(email) or not isinstance(email, str) or email.strip() == '':
        return 'Unknown'
    else:
        return 'External'

def get_custom_field_value(custom_fields_list, target_field_id):
    """
    Searches the custom_fields list for a specific field ID and returns its value.
    Returns None if the field list is invalid, the ID is not found, or value is null.
    """
    if not isinstance(custom_fields_list, list):
        return None
    for field in custom_fields_list:
        # Ensure field is a dictionary and has an 'id' key before comparing
        if isinstance(field, dict) and field.get('id') == target_field_id:
            # Return the value associated with the matching ID
            return field.get('value') # Returns None if 'value' key doesn't exist
    return None # Return None if the target ID was not found in the list

# --- Define FINAL state custom status IDs ---
# List of Custom Status IDs (as STRINGS) that represent a final solved/closed state
# !! Add your 'Closed' custom status ID string here if applicable !!
SOLVED_CLOSED_CUSTOM_IDS = ['2565572'] # Currently only includes 'solved' ID '2565572'


# --- V V V --- ADD CACHING DECORATOR --- V V V ---
@st.cache_data(ttl=600) # Cache processed data for 10 mins
# --- ^ ^ ^ --- ADD CACHING DECORATOR --- ^ ^ ^ ---
def process_ticket_data(raw_ticket_data, raw_event_data):
    """
    Cleans, transforms, and enriches raw ticket data. Uses events for solved_at time.
    Calculates Res Time (BH & Cal). Adds requester type & root cause.
    Cached based on inputs raw_ticket_data and raw_event_data.
    """
    # Add a simple print statement to see when this function actually runs vs. uses cache
    # This will only print to the CONSOLE when the function executes, not on cache hit.
    print(f"DEBUG: Running process_ticket_data (Not Cached Output!) - Input tickets: {len(raw_ticket_data)}, Input events: {len(raw_event_data)}")

    if not raw_ticket_data:
        return pd.DataFrame()

    try:
        df = pd.DataFrame(raw_ticket_data)
        if df.empty: return df
    except Exception as e:
        st.error(f"Error creating DataFrame from ticket data: {e}")
        return pd.DataFrame()

    # --- Subject Filter ---
    if 'subject' in df.columns:
        original_count = df.shape[0]
        df = df[df['subject'].ne("SCRUBBED")].copy()
        # if df.shape[0] < original_count: st.write(...) # Keep UI clean
    if df.empty:
        st.warning("No tickets remaining after filtering.")
        return df

    # --- Basic Processing ---
    datetime_cols = ['created_at', 'updated_at']
    for col in datetime_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce', utc=True) # Ensure UTC Aware

    relevant_cols = [
        'id', 'subject', 'description', 'status',
        'custom_status_id', # Include custom status ID
        'priority', 'type', 'requester_id', 'assignee_id', 'organization_id', 'group_id',
        'created_at', 'updated_at', 'tags', 'custom_fields'
    ]
    existing_relevant_cols = [col for col in relevant_cols if col in df.columns]
    df_processed = df[existing_relevant_cols].copy()

    # Ensure custom_status_id is numeric
    if 'custom_status_id' in df_processed.columns:
        df_processed['custom_status_id'] = pd.to_numeric(df_processed['custom_status_id'], errors='coerce')
    else:
        # st.warning("Column 'custom_status_id' not found.") # Keep UI clean
        df_processed['custom_status_id'] = pd.NA


    # --- Process Events to find Solved Times ---
    solved_times = {}
    if raw_event_data:
        remaining_ticket_ids = set(df_processed['id'].tolist())
        relevant_event_data = [event for event in raw_event_data if event.get('ticket_id') in remaining_ticket_ids]

        for event in relevant_event_data:
            child_events = event.get('child_events', [])
            if not isinstance(child_events, list): continue
            for child in child_events:
                 # Check if custom_status_id changed TO a final state ID
                 is_change_event = child.get('event_type') == 'Change'
                 # Check BOTH standard status OR custom status ID field directly
                 is_final_standard_status = child.get('status') in ['solved', 'closed']
                 is_final_custom_status = str(child.get('custom_status_id')) in SOLVED_CLOSED_CUSTOM_IDS

                 if is_change_event and (is_final_standard_status or is_final_custom_status):
                    ticket_id = event.get('ticket_id'); event_timestamp_str = event.get('timestamp')
                    if ticket_id and event_timestamp_str:
                        try:
                            event_dt = pd.to_datetime(event_timestamp_str, unit='s', errors='coerce', utc=True)
                            if pd.notna(event_dt):
                                # Keep the LATEST solved/closed timestamp
                                if ticket_id not in solved_times or event_dt > solved_times[ticket_id]:
                                    solved_times[ticket_id] = event_dt
                        except (ValueError, TypeError): pass # Ignore errors

        df_processed['solved_at_derived'] = pd.to_datetime(df_processed['id'].map(solved_times), errors='coerce', utc=True)
    else:
        df_processed['solved_at_derived'] = pd.NaT
    # Ensure tz aware even if NaT
    try:
         if df_processed['solved_at_derived'].dt.tz is None:
              df_processed['solved_at_derived'] = df_processed['solved_at_derived'].dt.tz_localize('UTC')
    except AttributeError:
         df_processed['solved_at_derived'] = pd.to_datetime(df_processed['solved_at_derived'], utc=True)

    # --- Debug block (Keep commented out unless needed) ---
    # st.divider(); st.subheader("--- DEBUG: Before Business Hour Calc ---")
    # ... (debug prints for created_at/solved_at_derived counts and info) ...
    # st.write("--- END DEBUG ---"); st.divider()

    # --- CALCULATE BUSINESS HOURS RESOLUTION TIME ---
    # st.write("Calculating resolution time in business hours...") # Keep off by default
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

        def calculate_single_business_duration(row):
            nonlocal calculated_count, failed_count, error_print_count
            row_id = row['id']; start_date_val = row['created_at']; end_date_val = row['solved_at_derived']
            try:
                start_date_local = start_date_val.tz_convert(business_timezone)
                end_date_local = end_date_val.tz_convert(business_timezone)
                # Use corrected keywords
                duration = businessDuration(
                    startdate=start_date_local, enddate=end_date_val,
                    starttime=business_start_time, endtime=business_end_time,
                    weekendlist=weekend_list, holidaylist=None, unit='hour'
                )
                calculated_count +=1; return duration if pd.notna(duration) else pd.NA
            except Exception as e:
                failed_count += 1
                if error_print_count < max_error_prints:
                    # Print error to console where streamlit run is executed
                    print(f"WARN: Business duration calc failed for ticket {row_id}: {type(e).__name__} - {e}")
                    error_print_count += 1
                return pd.NA

        business_hours_series = df_calc.apply(calculate_single_business_duration, axis=1)
        df_processed.loc[calc_mask, 'resolution_time_business_hours'] = business_hours_series
        df_processed.loc[df_processed['resolution_time_business_hours'] < 0, 'resolution_time_business_hours'] = pd.NA
        # st.write(f"BH calculated: {calculated_count}/{solved_count_for_calc}. Errors: {failed_count}.") # Summary off by default

    # --- Keep Calendar Hour Calculation ---
    if 'solved_at_derived' in df_processed.columns and 'created_at' in df_processed.columns:
        if pd.api.types.is_datetime64_any_dtype(df_processed['solved_at_derived']) and pd.api.types.is_datetime64_any_dtype(df_processed['created_at']):
            df_processed['resolution_time_calendar_hours'] = (df_processed['solved_at_derived'] - df_processed['created_at']).dt.total_seconds() / 3600
            df_processed.loc[df_processed['resolution_time_calendar_hours'] < 0, 'resolution_time_calendar_hours'] = pd.NA
            df_processed['resolution_time_calendar_hours'] = df_processed['resolution_time_calendar_hours'].fillna(pd.NA)
        else: df_processed['resolution_time_calendar_hours'] = pd.NA
    else: df_processed['resolution_time_calendar_hours'] = pd.NA


    # --- Add Requester Type ---
    if 'requester_id' in df_processed.columns:
        unique_requester_ids = df_processed['requester_id'].dropna().astype(int).unique().tolist()
        if unique_requester_ids:
            user_details_map = fetch_user_details(unique_requester_ids) # fetch_user_details is cached
            if user_details_map: df_processed['requester_email'] = df_processed['requester_id'].map(lambda uid: user_details_map.get(int(uid), {}).get('email') if pd.notna(uid) else None)
            else: df_processed['requester_email'] = None
            df_processed['requester_type'] = df_processed['requester_email'].apply(classify_requester)
        else: df_processed['requester_email'] = None; df_processed['requester_type'] = 'Unknown'
    else: df_processed['requester_email'] = None; df_processed['requester_type'] = 'Unknown'


    # --- Extract Root Cause ---
    try:
        if 'custom_fields' in df_processed.columns:
            df_processed['root_cause'] = df_processed['custom_fields'].apply(lambda cf_list: get_custom_field_value(cf_list, ROOT_CAUSE_FIELD_ID))
            df_processed['root_cause'] = df_processed['root_cause'].fillna('Not Specified')
        else:
            df_processed['root_cause'] = 'Unknown' # No warning needed
    except Exception as e:
        st.error(f"Error processing Root Cause: {e}. Setting to 'Error Processing'.")
        df_processed['root_cause'] = 'Error Processing'

    # print("DEBUG: process_ticket_data finished.") # Optional console log
    return df_processed