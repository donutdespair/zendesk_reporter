# dashboard.py
import streamlit as st
import pandas as pd
import time
from dotenv import load_dotenv
import os
from streamlit.errors import StreamlitSecretNotFoundError

# Import utility functions
from utils.zendesk_api import (
    configure_api_client,
    fetch_recent_tickets_cached,
    fetch_recent_ticket_events_cached,
    fetch_user_details
)
from utils.data_processing import process_ticket_data
from utils.plotting import (
    plot_tickets_by_status,
    plot_tickets_per_day,
    plot_resolution_distribution,
    plot_internal_external_breakdown,
    plot_median_resolution_by_root_cause
)
import matplotlib.pyplot as plt

# --- Constants ---
# API_FETCH_LOOKBACK_DAYS removed, using slider value directly

# List of Custom Status IDs that represent an open/pending/hold/new state
OPEN_CUSTOM_STATUS_IDS = [
    2565492, # New
    2565512, # Open
    2565532, # Pending
    2565552, # Third Party Provider Hold
    26734791021965  # Engineering
]

# --- CUSTOM STATUS ID to NAME MAPPING ---
# !! Update with your actual names/IDs for Closed/Deleted !!
CUSTOM_STATUS_MAP = {
    2565492: "New",
    2565512: "Open",
    2565532: "Pending",
    2565552: "Third Party Provider Hold",
    26734791021965: "Engineering",
    2565572: "Solved",
    # Example placeholders (replace with actual IDs and Names)
    12345678: "Closed", # Placeholder ID for 'closed' count
    87654321: "Deleted", # Placeholder ID for 'deleted' count
    'Missing': "Missing Status ID"
}

# Load Env Vars
load_dotenv()

# Password Check Function (remove this function and the main 'if check_password():' block if not needed)
def check_password():
    """
    Checks if the user has entered the correct password.
    Uses st.session_state to keep track of login status.
    Checks st.secrets first (handling error if file not found), then os.getenv.
    Returns True if logged in, False otherwise.
    """
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.title("Dashboard Login")
        st.write("Please enter the password to access the dashboard.")
        with st.form("login_form"):
            password_input = st.text_input("Password:", type="password", key="password_input_form")
            submitted = st.form_submit_button("Login")
            if submitted:
                app_password_from_secrets = None; correct_password = None
                try: app_password_from_secrets = st.secrets.get("APP_PASSWORD")
                except StreamlitSecretNotFoundError: pass
                except Exception as e: st.warning(f"Error accessing secrets: {e}"); pass
                app_password_from_env = os.getenv("APP_PASSWORD")
                correct_password = app_password_from_secrets if app_password_from_secrets is not None else app_password_from_env
                if correct_password is None: st.error("Config Error: APP_PASSWORD not set.")
                elif password_input == correct_password: st.session_state.password_correct = True; st.rerun()
                else: st.error("Password incorrect."); st.session_state.password_correct = False
        return False
    else:
         return True

# --- Main App Logic ---
# Remove the 'if check_password():' check if password login is not desired
if check_password():
    # Configure API Client first thing after potential login
    if 'api_configured' not in st.session_state: st.session_state.api_configured = False
    if not st.session_state.api_configured:
         if configure_api_client(): st.session_state.api_configured = True
         else: pass # configure_api_client calls st.stop() on failure

    # --- Sidebar Setup ---
    # Remove "Logged In" message if password check is removed
    st.sidebar.success("Logged In Successfully!") # Remove if password check removed
    st.sidebar.divider()
    st.title("Zendesk Support Metrics Dashboard")

    st.sidebar.header("Dashboard Controls")
    # Update lookback slider
    update_lookback_days = st.sidebar.slider(
        "1. Fetch data updated in last N days:", 7, 180, 30, 7, key="update_lookback_slider",
        help="Select the number of past days to look for ticket AND ticket event updates. Affects all data shown."
    )
    st.sidebar.divider()
    st.sidebar.markdown("##### Filter by Creation Date")
    use_creation_filter = st.sidebar.checkbox("Filter analysis by ticket creation date?", value=False, key="use_creation_filter_cb", help="If checked, analysis below will only include tickets created within the specified number of days.") # Default OFF
    filter_creation_days = 0
    if use_creation_filter:
        filter_creation_days = st.sidebar.number_input("Analyze tickets created in last N days:", 1, value=90, step=30, key="filter_creation_days_num") # Default 90 when ON
    st.sidebar.divider()
    st.sidebar.markdown("##### Exclude Root Causes")
    st.sidebar.caption("(Applies to KPIs & Dist. plot)")
    exclude_rc_placeholder = st.sidebar.empty() # Placeholder for multiselect
    st.sidebar.divider()
    st.sidebar.caption("Business Hours Used: Mon-Fri, 9am-8pm EST/EDT")


    # --- Data Fetching & Processing ---
    start_time_unix = int(time.time()) - (update_lookback_days * 24 * 60 * 60)
    start_time_str = pd.to_datetime(start_time_unix, unit='s').strftime('%Y-%m-%d %H:%M:%S')

    st.info(f"Fetching tickets & events updated since: {start_time_str} UTC (Last {update_lookback_days} days)")
    with st.spinner(f"Fetching & processing data..."):
        raw_ticket_data = fetch_recent_tickets_cached(start_time_unix)
        raw_event_data = fetch_recent_ticket_events_cached(start_time_unix)
        df_processed = process_ticket_data(raw_ticket_data, raw_event_data)

    # --- Display Results ---
    st.header("Dashboard Results")
    if df_processed.empty:
        if raw_ticket_data or raw_event_data: st.warning("Data fetched, but processing resulted in an empty DataFrame...")
        else: st.warning(f"No ticket or event data was fetched for the last {update_lookback_days} days.")
        with st.expander("Raw Tickets"): st.json(raw_ticket_data[:10] if raw_ticket_data else "N/A")
        with st.expander("Raw Events"): st.json(raw_event_data[:10] if raw_event_data else "N/A")
    else:
        st.success(f"Successfully processed {df_processed.shape[0]:,} tickets updated in the last {update_lookback_days} days.")

        # --- Populate Root Cause Filter ---
        available_root_causes = []; placeholder_rc = ['Not Specified', 'Unknown', 'Error Processing']
        if 'root_cause' in df_processed.columns: available_root_causes = sorted([rc for rc in df_processed['root_cause'].unique() if pd.notna(rc) and rc not in placeholder_rc])
        excluded_root_causes = exclude_rc_placeholder.multiselect("Select Root Causes to Exclude:", options=available_root_causes, default=[], key="exclude_rc_multiselect")

        # --- Apply Filters ---
        df_analysis = df_processed.copy(); creation_filter_applied = False
        if use_creation_filter and filter_creation_days > 0 and 'created_at' in df_analysis.columns: # Age Filter
             try:
                if df_analysis['created_at'].dt.tz is None: df_analysis['created_at'] = df_analysis['created_at'].dt.tz_localize('UTC')
                cutoff_date = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=filter_creation_days); original_count = df_analysis.shape[0]; df_analysis = df_analysis[df_analysis['created_at'] >= cutoff_date].copy();
                if df_analysis.shape[0] < original_count: creation_filter_applied = True; st.info(f"Applied creation date filter: Analyzing {df_analysis.shape[0]:,} tickets...")
             except Exception as e: st.warning(f"Could not apply age filter: {e}")
        # Removed message when filter off

        df_metrics_final = df_analysis.copy(); rc_filter_applied = False
        if excluded_root_causes and 'root_cause' in df_metrics_final.columns: # RC Filter
            original_metric_count = df_metrics_final.shape[0]; df_metrics_final = df_metrics_final[~df_metrics_final['root_cause'].isin(excluded_root_causes)].copy();
            if df_metrics_final.shape[0] < original_metric_count: rc_filter_applied = True

        # --- Key Metrics ---
        st.subheader("Key Metrics")
        metric_note = "(Metrics based on: "; filter_notes = []; # Build caption
        if creation_filter_applied: filter_notes.append(f"Created in last {filter_creation_days} days")
        elif use_creation_filter and filter_creation_days <= 0: filter_notes.append("Created (No day limit)")
        else: filter_notes.append(f"Tickets updated in last {update_lookback_days} days")
        if rc_filter_applied: filter_notes.append(f"Excluding RCs: {', '.join(excluded_root_causes)}")
        metric_note += "; ".join(filter_notes) + ")"
        st.caption(metric_note)

        col1, col2, col3 = st.columns(3)
        total_metric_tickets = df_metrics_final.shape[0]; col1.metric(f"Tickets Included", f"{total_metric_tickets:,}")
        if 'custom_status_id' in df_metrics_final.columns: # Open count
             temp_status_id_col = pd.to_numeric(df_metrics_final['custom_status_id'], errors='coerce'); open_tickets = df_metrics_final[temp_status_id_col.isin(OPEN_CUSTOM_STATUS_IDS)].shape[0]; col2.metric("Currently 'Open' Status", f"{open_tickets:,}", help=f"Custom Status IDs: {OPEN_CUSTOM_STATUS_IDS}")
        else: col2.metric("Currently 'Open' Status", "N/A", help="Custom Status ID missing.")
        target_res_col = 'resolution_time_business_hours'; # Resolution metric
        if target_res_col in df_metrics_final.columns and df_metrics_final[target_res_col].notna().any(): avg_res_bh = df_metrics_final[target_res_col].mean(); med_res_bh = df_metrics_final[target_res_col].median(); col3.metric("Median Resolution (Business Hrs)", f"{med_res_bh:.1f}" if pd.notna(med_res_bh) else "N/A", help="Mon-Fri, 9am-8pm ET.");
        else: col3.metric("Median Resolution (Business Hrs)", "N/A", help="No solved tickets found.")
        if target_res_col in df_metrics_final.columns and pd.notna(avg_res_bh): col3.caption(f"Average (BH): {avg_res_bh:.1f} hrs")

        st.divider()
        st.subheader("Visualizations")
        plot_note_parts = []; # Build plot caption
        if creation_filter_applied: plot_note_parts.append(f"Filtered by Creation Date (Last {filter_creation_days} days)")
        if rc_filter_applied: plot_note_parts.append(f"Excluding RCs from Distribution plot")
        if plot_note_parts: st.caption(f"(Plots respect filters as noted)")

        # Arrange plots
        col_viz1, col_viz2 = st.columns(2)
        with col_viz1:
            st.markdown("##### Tickets by Status"); fig_status = plot_tickets_by_status(df_analysis);
            if fig_status: st.pyplot(fig_status); plt.close(fig_status)
            st.markdown("##### Resolution Time Distribution (Business Hours)"); fig_res_dist = plot_resolution_distribution(df_metrics_final);
            if fig_res_dist: st.pyplot(fig_res_dist); plt.close(fig_res_dist)
        with col_viz2:
            st.markdown("##### Tickets Created Over Time"); fig_daily = plot_tickets_per_day(df_analysis);
            if fig_daily: st.pyplot(fig_daily); plt.close(fig_daily)
            st.markdown("##### Internal vs External Requesters"); fig_requester_type = plot_internal_external_breakdown(df_analysis);
            if fig_requester_type: st.pyplot(fig_requester_type); plt.close(fig_requester_type)

        st.divider()
        st.subheader("Median Resolution Time by Root Cause (Business Hours)")
        if creation_filter_applied: st.caption(f"(Plot below based on tickets created in the last {filter_creation_days} days)")
        if 'root_cause' in df_analysis.columns and target_res_col in df_analysis.columns and df_analysis['root_cause'].notna().any() and df_analysis[target_res_col].notna().any():
             fig_root_cause_median = plot_median_resolution_by_root_cause(df_analysis)
             if fig_root_cause_median: st.pyplot(fig_root_cause_median); plt.close(fig_root_cause_median)
        else: st.info("Insufficient data to plot Median Resolution Time by Root Cause.")

        # --- V V V --- CLEANED UP DATA TABLE SECTION --- V V V ---
        st.divider()
        # Renamed expander and removed internal debug prints
        with st.expander("View Filtered Ticket Data Details"):
             table_caption = "Showing tickets "
             if creation_filter_applied:
                 table_caption += f"created in last {filter_creation_days} days."
             else:
                 table_caption += f"updated in last {update_lookback_days} days."
             table_caption += f" (Total: {df_analysis.shape[0]} tickets)" # Add count here
             st.caption(table_caption)

             # Define columns to show in the table
             cols_to_show = [
                 'id', 'subject', 'status', 'custom_status_id', 'priority', 'type',
                 'requester_type', 'root_cause', 'created_at', 'solved_at_derived',
                 'resolution_time_business_hours', 'resolution_time_calendar_hours'
                 ]
             # Ensure columns exist before trying to display them
             final_cols_to_show_in_table = [col for col in cols_to_show if col in df_analysis.columns]

             # Display the main data table using df_analysis
             st.dataframe(df_analysis[final_cols_to_show_in_table], use_container_width=True, hide_index=True)
        # --- ^ ^ ^ --- END CLEANED UP DATA TABLE SECTION --- ^ ^ ^ ---

        # Raw data expanders
        with st.expander("View Raw Fetched Ticket Data (JSON sample)"): st.json(raw_ticket_data[:10] if raw_ticket_data else "N/A")
        with st.expander("View Raw Fetched Event Data (JSON sample)"): st.json(raw_event_data[:10] if raw_event_data else "N/A")