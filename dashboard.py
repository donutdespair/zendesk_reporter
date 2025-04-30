# dashboard.py
import streamlit as st
import pandas as pd
import time
from dotenv import load_dotenv
import os
# --- Import the specific error ---
from streamlit.errors import StreamlitSecretNotFoundError
# Import utility functions
from utils.zendesk_api import (
    configure_api_client, fetch_recent_tickets_cached,
    fetch_recent_ticket_events_cached, fetch_user_details,
    fetch_ticket_comments # <-- Import comment fetcher
)
from utils.data_processing import process_ticket_data
from utils.plotting import (
    plot_tickets_by_status, plot_tickets_per_day,
    plot_resolution_distribution, plot_internal_external_breakdown,
    plot_median_resolution_by_root_cause,
    plot_engineering_ticket_age
)
# Import Summarizer utils
from utils.summarizer import configure_gemini, summarize_text # Import config and summarize functions
import matplotlib.pyplot as plt


# --- Constants & Maps ---
OPEN_CUSTOM_STATUS_IDS = [ 2565492, 2565512, 2565532, 2565552, 26734791021965 ]
CUSTOM_STATUS_MAP = { # !! Update !!
    2565492: "New", 2565512: "Open", 2565532: "Pending",
    2565552: "Third Party Provider Hold", 26734791021965: "Engineering",
    2565572: "Solved",
    # Example placeholders (replace with actual IDs and Names)
    12345678: "Closed", # Placeholder ID for 'closed' count
    87654321: "Deleted", # Placeholder ID for 'deleted' count
    'Missing': "Missing Status ID"
}

# Load Env Vars
load_dotenv()

# --- Initialize Session State ---
# ... (Session state initialization remains the same) ...
if 'summary_output' not in st.session_state: st.session_state.summary_output = ""
if 'data_processed' not in st.session_state: st.session_state.data_processed = None
if 'data_analysis' not in st.session_state: st.session_state.data_analysis = None
if 'data_metrics_final' not in st.session_state: st.session_state.data_metrics_final = None
if 'figures' not in st.session_state: st.session_state.figures = {}
if 'metrics' not in st.session_state: st.session_state.metrics = {}
if 'filters' not in st.session_state: st.session_state.filters = {}
if 'password_correct' not in st.session_state: st.session_state.password_correct = False
if 'api_clients_configured' not in st.session_state: st.session_state.api_clients_configured = False


# Password Check Function (remove if not needed)
def check_password():
    """ Checks password, uses session state. Includes robust secrets handling. """
    if st.session_state.password_correct: return True
    st.title("Dashboard Login"); st.write("Please enter the password...")
    with st.form("login_form"):
        password_input = st.text_input("Password:", type="password", key="password_input_form")
        submitted = st.form_submit_button("Login")
        if submitted:
            app_password_secret = None; correct_password = None
            secrets_path_project = os.path.join(".streamlit", "secrets.toml"); secrets_path_global = os.path.expanduser("~/.streamlit/secrets.toml")
            use_st_secrets = os.path.exists(secrets_path_project) or os.path.exists(secrets_path_global)
            if use_st_secrets:
                try: app_password_secret = st.secrets.get("APP_PASSWORD")
                except Exception as e: st.warning(f"Error reading APP_PASSWORD secret: {e}")
            app_password_env = os.getenv("APP_PASSWORD")
            correct_password = app_password_secret if app_password_secret is not None else app_password_env
            if correct_password is None: st.error("Config Error: APP_PASSWORD not set.")
            elif password_input == correct_password: st.session_state.password_correct = True; st.rerun()
            else: st.error("Password incorrect."); st.session_state.password_correct = False
    return False

# --- Main App Logic ---
if check_password(): # Gate the whole app

    # --- Configure API Clients ---
    if not st.session_state.api_clients_configured:
         print("Attempting to configure API clients...")
         zendesk_ok = configure_api_client()
         gemini_ok = configure_gemini() # Uses robust check internally
         if zendesk_ok and gemini_ok: st.session_state.api_clients_configured = True; print("API clients configured.")
         else: st.error("API configuration failed. Check credentials/keys and console logs."); st.stop()

    # --- Sidebar Setup ---
    # Removed "Logged In" message for cleaner look if password check removed later
    # st.sidebar.success("Logged In Successfully!")
    st.sidebar.divider()
    st.title("Zendesk Support Metrics Dashboard")

    st.sidebar.header("Dashboard Controls")
    update_lookback_days = st.sidebar.slider("1. Fetch data updated in last N days:", 7, 180, st.session_state.filters.get('update_lookback_days', 30), 7, key="update_lookback_slider")
    st.sidebar.divider(); st.sidebar.markdown("##### Filter by Creation Date"); use_creation_filter = st.sidebar.checkbox("Filter analysis by creation date?", st.session_state.filters.get('use_creation_filter', False), key="use_creation_filter_cb")
    filter_creation_days = 0
    if use_creation_filter: filter_creation_days = st.sidebar.number_input("Analyze tickets created in last N days:", 1, st.session_state.filters.get('filter_creation_days', 90), 30, key="filter_creation_days_num")
    st.sidebar.divider(); st.sidebar.markdown("##### Exclude Root Causes"); st.sidebar.caption("(Applies to KPIs & Dist. plot)"); exclude_rc_placeholder = st.sidebar.empty(); st.sidebar.divider()

    # --- Ticket Summarizer Section ---
    st.sidebar.header("Ticket Summarizer")
    ticket_id_to_summarize = st.sidebar.number_input("Enter Zendesk Ticket ID:", 1, step=1, value=None, key="ticket_id_summarize")
    summarize_button = st.sidebar.button("Summarize Ticket Comments", key="summarize_ticket_btn")

    if summarize_button and ticket_id_to_summarize:
        try:
            ticket_id_int = int(ticket_id_to_summarize)
            # --- V V V --- SYNTAX CORRECTED HERE --- V V V ---
            with st.spinner(f"Fetching comments for ticket {ticket_id_int}..."):
                # Function call indented on the next line
                comment_text, fetch_error = fetch_ticket_comments(ticket_id_int)
            # --- ^ ^ ^ --- SYNTAX CORRECTED HERE --- ^ ^ ^ ---

            if fetch_error: st.session_state.summary_output = f"Error: {fetch_error}"
            elif not comment_text: st.session_state.summary_output = "Warning: No comment text found."
            else:
                with st.spinner("Summarizing comments with Gemini..."):
                    summary = summarize_text(comment_text) # Use imported function
                st.session_state.summary_output = summary # Store result in session state
        except ValueError: st.session_state.summary_output = "Error: Invalid Ticket ID."
        except Exception as e: st.session_state.summary_output = f"An unexpected error occurred: {e}"

    # Always display summary output from session state if it exists
    if st.session_state.summary_output:
         st.sidebar.text_area("Summary:", st.session_state.summary_output, height=250, key="summary_output_display", help="Summary generated by Gemini AI.")

    st.sidebar.divider()
    st.sidebar.caption("Business Hours Used: Mon-Fri, 9am-8pm EST/EDT")

    # --- Check if Filters Changed ---
    current_filters = { 'update_lookback_days': update_lookback_days, 'use_creation_filter': use_creation_filter, 'filter_creation_days': filter_creation_days if use_creation_filter else 0, 'excluded_root_causes': [] } # RC list populated after data load
    filters_changed_flag = False
    if st.session_state.filters.get('update_lookback_days') != current_filters['update_lookback_days'] or \
       st.session_state.filters.get('use_creation_filter') != current_filters['use_creation_filter'] or \
       st.session_state.filters.get('filter_creation_days') != current_filters['filter_creation_days'] or \
       st.session_state.data_processed is None:
           filters_changed_flag = True; print("INFO: Main filters changed or data missing...")
    # Update stored filters (excluding RC for now)
    st.session_state.filters['update_lookback_days'] = current_filters['update_lookback_days']
    st.session_state.filters['use_creation_filter'] = current_filters['use_creation_filter']
    st.session_state.filters['filter_creation_days'] = current_filters['filter_creation_days']


    # --- Main Panel ---
    # st.title("Zendesk Support Metrics Dashboard") # Moved title up

    # --- Data Fetching & Processing (Conditional) ---
    if filters_changed_flag:
        start_time_unix = int(time.time()) - (update_lookback_days * 24 * 60 * 60)
        st.info(f"Fetching & processing data for last {update_lookback_days} days...")
        with st.spinner(f"Fetching & processing data..."):
            raw_ticket_data = fetch_recent_tickets_cached(start_time_unix)
            raw_event_data = fetch_recent_ticket_events_cached(start_time_unix)
            df_processed = process_ticket_data(raw_ticket_data, raw_event_data)
            st.session_state.data_processed = df_processed
            st.session_state.data_analysis = None; st.session_state.data_metrics_final = None
            st.session_state.metrics = {}; st.session_state.figures = {}
            print("INFO: Data processed and stored/updated.")
    else:
        df_processed = st.session_state.data_processed


    # --- Display Results ---
    st.header("Dashboard Results")
    if df_processed is None or df_processed.empty:
         st.warning(f"No ticket data found or processed for the lookback period ({update_lookback_days} days).")
         # Cannot show raw data if not stored in state
         # with st.expander("Raw Tickets"): st.json(raw_ticket_data[:10] if raw_ticket_data else "N/A")
         # with st.expander("Raw Events"): st.json(raw_event_data[:10] if raw_event_data else "N/A")
    else:
        st.success(f"Displaying analysis based on {df_processed.shape[0]:,} tickets updated in the last {update_lookback_days} days.")

        # --- Populate & Check Root Cause Filter ---
        available_root_causes = []; placeholder_rc = ['Not Specified', 'Unknown', 'Error Processing']
        if 'root_cause' in df_processed.columns: available_root_causes = sorted([rc for rc in df_processed['root_cause'].unique() if pd.notna(rc) and rc not in placeholder_rc])
        default_excluded = st.session_state.filters.get('excluded_root_causes', [])
        excluded_root_causes = exclude_rc_placeholder.multiselect("Select Root Causes to Exclude:", options=available_root_causes, default=default_excluded, key="exclude_rc_multiselect")
        if st.session_state.filters.get('excluded_root_causes') != excluded_root_causes: filters_changed_flag = True; print("INFO: Root cause filter changed..."); st.session_state.filters['excluded_root_causes'] = excluded_root_causes

        # --- Apply Filters (Conditional) ---
        if filters_changed_flag or st.session_state.data_analysis is None:
            print("INFO: Applying filters...")
            df_analysis = df_processed.copy(); creation_filter_applied = False
            if use_creation_filter and filter_creation_days > 0 and 'created_at' in df_analysis.columns:
                 try:
                    if df_analysis['created_at'].dt.tz is None: df_analysis['created_at'] = df_analysis['created_at'].dt.tz_localize('UTC')
                    cutoff_date = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=filter_creation_days); original_count = df_analysis.shape[0]; df_analysis = df_analysis[df_analysis['created_at'] >= cutoff_date].copy();
                    if df_analysis.shape[0] < original_count: creation_filter_applied = True;
                 except Exception as e: st.warning(f"Could not apply age filter: {e}")
            df_metrics_final = df_analysis.copy(); rc_filter_applied = False
            if excluded_root_causes and 'root_cause' in df_metrics_final.columns:
                original_metric_count = df_metrics_final.shape[0]; df_metrics_final = df_metrics_final[~df_metrics_final['root_cause'].isin(excluded_root_causes)].copy();
                if df_metrics_final.shape[0] < original_metric_count: rc_filter_applied = True
            st.session_state.data_analysis = df_analysis; st.session_state.data_metrics_final = df_metrics_final; st.session_state.creation_filter_applied_flag = creation_filter_applied; st.session_state.rc_filter_applied_flag = rc_filter_applied
        else:
            df_analysis = st.session_state.data_analysis; df_metrics_final = st.session_state.data_metrics_final; creation_filter_applied = st.session_state.creation_filter_applied_flag; rc_filter_applied = st.session_state.rc_filter_applied_flag

        # --- Calculate Metrics & Generate Figures (Conditional) ---
        if filters_changed_flag or not st.session_state.metrics or not st.session_state.figures:
            print("INFO: Recalculating metrics and/or regenerating figures...")
            # ... (Calculate metrics and generate figures, store in session state) ...
            current_metrics = {}; current_figures = {} # ... (metric calculations) ...
            current_metrics['total_tickets'] = st.session_state.data_metrics_final.shape[0]
            if 'custom_status_id' in st.session_state.data_metrics_final.columns: temp_status_id = pd.to_numeric(st.session_state.data_metrics_final['custom_status_id'], errors='coerce'); current_metrics['open_tickets'] = st.session_state.data_metrics_final[temp_status_id.isin(OPEN_CUSTOM_STATUS_IDS)].shape[0]
            else: current_metrics['open_tickets'] = "N/A"
            target_res_col = 'resolution_time_business_hours'
            if target_res_col in st.session_state.data_metrics_final.columns and st.session_state.data_metrics_final[target_res_col].notna().any(): current_metrics['avg_res_bh'] = st.session_state.data_metrics_final[target_res_col].mean(); current_metrics['med_res_bh'] = st.session_state.data_metrics_final[target_res_col].median()
            else: current_metrics['avg_res_bh'] = None; current_metrics['med_res_bh'] = None
            st.session_state.metrics = current_metrics # ... (figure generation) ...
            current_figures['status_plot'] = plot_tickets_by_status(st.session_state.data_analysis); current_figures['res_dist_plot'] = plot_resolution_distribution(st.session_state.data_metrics_final); current_figures['daily_plot'] = plot_tickets_per_day(st.session_state.data_analysis); current_figures['requester_plot'] = plot_internal_external_breakdown(st.session_state.data_analysis); current_figures['root_cause_plot'] = plot_median_resolution_by_root_cause(st.session_state.data_analysis); current_figures['eng_age_plot'] = plot_engineering_ticket_age(st.session_state.data_analysis);
            st.session_state.figures = current_figures

        # --- Display Metrics (Read from session state) ---
        st.subheader("Key Metrics")
        metric_note = "(Metrics based on: "; filter_notes = []; # ... build metric_note ... ; st.caption(metric_note)
        if creation_filter_applied: filter_notes.append(f"Tickets created in last {filter_creation_days} days")
        elif use_creation_filter and filter_creation_days <= 0: filter_notes.append("Tickets created (No day limit)")
        else: filter_notes.append(f"Tickets updated in last {update_lookback_days} days")
        if rc_filter_applied: filter_notes.append(f"Excluding RCs: {', '.join(excluded_root_causes)}")
        metric_note += "; ".join(filter_notes) + ")"
        st.caption(metric_note)
        col1, col2, col3 = st.columns(3); # ... (Display metrics from st.session_state.metrics) ...
        col1.metric(f"Tickets Included", f"{st.session_state.metrics.get('total_tickets', 0):,}")
        col2.metric("Currently 'Open' Status", f"{st.session_state.metrics.get('open_tickets', 'N/A'):,}" if st.session_state.metrics.get('open_tickets') != "N/A" else "N/A", help=f"Custom Status IDs: {OPEN_CUSTOM_STATUS_IDS}")
        med_res_bh = st.session_state.metrics.get('med_res_bh'); avg_res_bh = st.session_state.metrics.get('avg_res_bh')
        col3.metric("Median Resolution (BHrs)", f"{med_res_bh:.1f}" if pd.notna(med_res_bh) else "N/A", help="Mon-Fri, 9am-8pm ET.")
        if pd.notna(avg_res_bh): col3.caption(f"Average (BH): {avg_res_bh:.1f} hrs")

        # --- Display Visualizations (Read figures from session state) ---
        st.divider(); st.subheader("Visualizations")
        plot_note_parts = []; # ... build plot_note_parts ... ; if plot_note_parts: st.caption(f"({'; '.join(plot_note_parts)})")
        if creation_filter_applied: plot_note_parts.append(f"Filtered by Creation Date")
        if rc_filter_applied: plot_note_parts.append(f"Excluding RCs from Distribution plot")
        if plot_note_parts: st.caption(f"(Plots respect filters as noted)")

        col_viz1, col_viz2 = st.columns(2); # Display plots from st.session_state.figures
        with col_viz1: st.markdown("##### Tickets by Status"); fig = st.session_state.figures.get('status_plot');
        if fig: st.pyplot(fig)
        st.markdown("##### Resolution Time Distribution (Business Hours)"); fig = st.session_state.figures.get('res_dist_plot');
        if fig: st.pyplot(fig)
        with col_viz2: st.markdown("##### Tickets Created Over Time"); fig = st.session_state.figures.get('daily_plot');
        if fig: st.pyplot(fig)
        st.markdown("##### Internal vs External Requesters"); fig = st.session_state.figures.get('requester_plot');
        if fig: st.pyplot(fig)
        st.divider(); st.subheader("Median Resolution Time by Root Cause (Business Hours)")
        if creation_filter_applied: st.caption(f"(Based on tickets created in last {filter_creation_days} days)")
        fig = st.session_state.figures.get('root_cause_plot');
        if fig: st.pyplot(fig)
        else: st.info("Insufficient data for Root Cause plot.")
        st.divider(); st.subheader("Age of Tickets Currently in 'Engineering' Status")
        fig = st.session_state.figures.get('eng_age_plot');
        if fig: st.pyplot(fig)


        # --- Data Tables (Use session state data) ---
        st.divider()
        with st.expander("View Filtered Ticket Data Details"):
             display_df = st.session_state.get('data_analysis', pd.DataFrame()) # Use df from state
             table_caption = "Showing tickets "; # ... (build caption) ... ; st.caption(table_caption)
             if creation_filter_applied: table_caption += f"created in last {filter_creation_days} days."
             else: table_caption += f"updated in last {update_lookback_days} days."
             table_caption += f" (Total: {display_df.shape[0]} rows)"
             st.caption(table_caption)
             # Removed table debug section for final version
             cols_to_show = ['id', 'subject', 'status', 'custom_status_id', 'priority', 'type','requester_type', 'root_cause', 'created_at', 'solved_at_derived','resolution_time_business_hours', 'resolution_time_calendar_hours']
             final_cols_to_show_in_table = [col for col in cols_to_show if col in display_df.columns] # Check against display_df
             st.dataframe(display_df[final_cols_to_show_in_table], use_container_width=True, hide_index=True)

        # Raw data expanders need adjustment if raw data isn't stored/passed correctly
        with st.expander("View Raw Fetched Ticket Data (JSON sample)"):
             # Try accessing from state if stored, else use local var (might be outdated)
             raw_tickets_to_show = st.session_state.get('raw_ticket_data', None)
             if raw_tickets_to_show is None and 'raw_ticket_data' in locals():
                  raw_tickets_to_show = raw_ticket_data # Fallback if not in state
             st.json(raw_tickets_to_show[:10] if raw_tickets_to_show else "N/A - Rerun with filter change to see.")

        with st.expander("View Raw Fetched Event Data (JSON sample)"):
             raw_events_to_show = st.session_state.get('raw_event_data', None)
             if raw_events_to_show is None and 'raw_event_data' in locals():
                 raw_events_to_show = raw_event_data # Fallback if not in state
             st.json(raw_events_to_show[:10] if raw_events_to_show else "N/A - Rerun with filter change to see.")

    # --- Reset filter change flag at the end ---
    st.session_state.filters_changed = False