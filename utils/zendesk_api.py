# utils/zendesk_api.py

import requests
import time
import os
import json
import pandas as pd
import streamlit as st
# --- V V V --- Import the specific error --- V V V ---
from streamlit.errors import StreamlitSecretNotFoundError

# Global variables
ZEN_AUTH = None
ZEN_BASE_URL = None

# --- V V V --- FUNCTION WITH TRY/EXCEPT BLOCK FOR SECRETS --- V V V ---
def configure_api_client():
    """
    Sets up global authentication tuple and base URL.
    Tries st.secrets first (for cloud), then falls back to os.getenv (for local .env).
    Handles StreamlitSecretNotFoundError gracefully for local runs without secrets.toml.
    Returns True on success, False on failure (and stops Streamlit).
    """
    global ZEN_AUTH, ZEN_BASE_URL

    # Avoid reconfiguring if already done in the same run
    if ZEN_AUTH is not None and ZEN_BASE_URL is not None:
        return True

    subdomain_secret = None
    email_secret = None
    api_token_secret = None

    # Try getting credentials from Streamlit secrets first
    try:
        subdomain_secret = st.secrets.get("ZENDESK_SUBDOMAIN")
        email_secret = st.secrets.get("ZENDESK_EMAIL")
        api_token_secret = st.secrets.get("ZENDESK_API_TOKEN")
        # If any secret exists, assume we might be in cloud or user has secrets.toml
        # if any([subdomain_secret, email_secret, api_token_secret]):
             # print("INFO: Attempted to read Zendesk credentials from Streamlit secrets.") # Optional Debug
    except StreamlitSecretNotFoundError:
        # This specific error means secrets.toml wasn't found locally. Safe to ignore.
        print("INFO: secrets.toml not found for Zendesk credentials, checking environment variables (.env).") # Optional Debug
        pass # Ignore the error, proceed to check env vars
    except Exception as e:
         # Catch other potential errors accessing st.secrets
         st.warning(f"An unexpected error occurred while accessing Streamlit secrets for Zendesk creds: {e}")
         pass # Still try os.getenv

    # Get credentials from environment variables (loaded from .env by load_dotenv() in dashboard.py)
    subdomain_env = os.getenv("ZENDESK_SUBDOMAIN")
    email_env = os.getenv("ZENDESK_EMAIL")
    api_token_env = os.getenv("ZENDESK_API_TOKEN")

    # Prioritize secrets if they were found (not None), otherwise use environment variables
    subdomain = subdomain_secret if subdomain_secret is not None else subdomain_env
    email = email_secret if email_secret is not None else email_env
    api_token = api_token_secret if api_token_secret is not None else api_token_env

    # Validate that we ended up with all necessary credentials
    if not all([subdomain, email, api_token]):
        st.error("Configuration Error: Zendesk API credentials (ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN) could not be found in Streamlit secrets or local .env file. Please check your configuration.")
        st.stop() # Stop app execution if critical configuration is missing
        return False # Indicate failure

    # Configure the global variables used by other API functions
    ZEN_AUTH = (f"{email}/token", api_token)
    ZEN_BASE_URL = f"https://{subdomain}.zendesk.com/api/v2"

    # print("Zendesk API client configured successfully.") # Optional Debug
    return True # Indicate successful configuration
# --- ^ ^ ^ --- END OF FUNCTION WITH TRY/EXCEPT --- ^ ^ ^ ---


@st.cache_data(ttl=600) # Cache for 10 minutes
def fetch_recent_tickets_cached(start_time_unix):
    """
    Fetches tickets updated since start_time_unix using the incremental export API (Cursor).
    """
    if not configure_api_client(): return [] # Ensure client is configured

    tickets = []
    endpoint = f"{ZEN_BASE_URL}/incremental/tickets/cursor.json" # Using cursor endpoint for tickets
    params = {'start_time': start_time_unix}
    page_count = 0; max_pages = 100; total_fetched = 0
    progress_bar = st.progress(0, text=f"Fetching tickets...")
    progress_value = 0.0

    while endpoint and page_count < max_pages:
        response = None
        progress_value = min(1.0, page_count / max_pages if max_pages > 0 else 0) # Update progress value before try
        try:
            response = requests.get(endpoint, params=params, auth=ZEN_AUTH, timeout=30)
            response.raise_for_status()
            data = response.json()
            page_tickets = data.get('tickets', [])
            tickets.extend(page_tickets); total_fetched += len(page_tickets)
            progress_value = min(1.0, (page_count + 1) / max_pages if max_pages > 0 else 1.0) # Update after fetch
            current_progress_text = f"Fetching tickets... (Page {page_count + 1}, Total: {total_fetched:,})"
            progress_bar.progress(progress_value, text=current_progress_text)
            if data.get('end_of_stream', True):
                 final_text = f"Ticket fetch complete. Total: {total_fetched:,}"
                 progress_bar.progress(1.0, text=final_text)
                 endpoint = None
            else:
                endpoint = data.get('after_url'); params = {} # Cursor uses after_url
                if not endpoint:
                    st.warning("API error: Missing 'after_url'. Stopping ticket fetch.")
                    progress_bar.progress(1.0, text=f"Incomplete ticket fetch (missing next URL). Total: {total_fetched:,}")
                    endpoint = None
            page_count += 1; time.sleep(0.5)
        except Exception as e: # Simplified error handling
            st.error(f"Error fetching tickets (Page {page_count+1}): {e}")
            progress_bar.progress(progress_value, text=f"Error fetching tickets page {page_count + 1}. Total: {total_fetched:,}")
            endpoint = None # Stop on error

    # Final progress update logic
    final_progress = 1.0 if endpoint is None else progress_value
    final_text = f"Ticket fetch complete. Total: {total_fetched:,}"
    if page_count == max_pages and endpoint:
         st.warning(f"Max pages ({max_pages}) reached fetching tickets."); final_text = f"Max pages reached fetching tickets. Total: {total_fetched:,}"
    elif total_fetched == 0 and page_count == 0 and endpoint is None: # Check if it stopped before starting
        final_text = "No tickets found or fetch failed immediately."
    elif endpoint is None and total_fetched == 0 : # Check if loop finished but no tickets
         final_text = "No tickets found for the selected period."

    # Ensure progress bar reaches 1.0 unless max pages hit with more data possible
    if endpoint is None: final_progress = 1.0
    progress_bar.progress(final_progress, text=final_text)

    return tickets


@st.cache_data(ttl=600) # Cache for 10 minutes
def fetch_recent_ticket_events_cached(start_time_unix):
    """
    Fetches ticket events since start_time_unix using the time-based
    incremental ticket events export API (/api/v2/incremental/ticket_events.json)
    and handles next_page pagination.
    """
    if not configure_api_client(): return [] # Ensure client is configured

    ticket_events = []
    endpoint = f"{ZEN_BASE_URL}/incremental/ticket_events.json" # Time-based endpoint for events
    params = {'start_time': start_time_unix, 'include': 'comment_events'}
    page_count = 0; max_pages = 200; total_fetched = 0
    event_progress_bar = st.progress(0, text="Fetching ticket events...")
    progress_value = 0.0

    while endpoint and page_count < max_pages:
        response = None; progress_value = min(1.0, page_count / max_pages if max_pages > 0 else 0)
        try:
            current_params = params if page_count == 0 else {}
            response = requests.get(endpoint, params=current_params, auth=ZEN_AUTH, timeout=45)
            response.raise_for_status()
            data = response.json()
            page_events = data.get('ticket_events', [])
            ticket_events.extend(page_events); total_fetched += len(page_events)
            progress_value = min(1.0, (page_count + 1) / max_pages if max_pages > 0 else 1.0)
            current_progress_text = f"Fetching ticket events... (Page {page_count + 1}, Total: {total_fetched:,})"
            event_progress_bar.progress(progress_value, text=current_progress_text)
            is_end = data.get('end_of_stream', False); next_page_url = data.get('next_page')
            if is_end or next_page_url is None:
                final_text = f"Ticket event fetch complete. Total: {total_fetched:,}"
                event_progress_bar.progress(1.0, text=final_text); endpoint = None
            else: endpoint = next_page_url
            page_count += 1; time.sleep(0.5)
        except Exception as e: # Simplified error handling
            st.error(f"Error fetching events (Page {page_count+1}): {e}")
            event_progress_bar.progress(progress_value, text=f"Error fetching events page {page_count + 1}. Total: {total_fetched:,}")
            endpoint = None # Stop on error

    # Final progress update logic
    final_progress = 1.0 if endpoint is None else progress_value
    final_text = f"Ticket event fetch complete. Total: {total_fetched:,}"
    if page_count == max_pages and endpoint:
         st.warning(f"Max pages ({max_pages}) reached fetching events.")
         final_text = f"Max pages reached fetching events. Total: {total_fetched:,}"
    elif total_fetched == 0 and page_count == 0 and endpoint is None:
        final_text = "Ticket event fetch failed or no events found."
    elif endpoint is None and total_fetched == 0 :
         final_text = "No ticket events found for the selected period."

    if endpoint is None: final_progress = 1.0
    event_progress_bar.progress(final_progress, text=final_text)

    return ticket_events


@st.cache_data(ttl=3600) # Keep user fetch cached longer
def fetch_user_details(user_ids):
    """ Fetches user details for a list of user IDs in batches of 100. """
    if not configure_api_client(): return {}
    if not user_ids: return {}
    all_user_data = {}
    unique_ids = list(set(int(uid) for uid in user_ids if pd.notna(uid) and isinstance(uid, (int, float)) and uid > 0))
    if not unique_ids: return {}
    total_batches = (len(unique_ids) + 99) // 100
    user_progress = st.progress(0, text=f"Fetching user details...")
    current_progress = 0.0
    for i in range(0, len(unique_ids), 100):
        batch_num = i // 100 + 1; chunk_ids = unique_ids[i:i+100]
        ids_param = ",".join(map(str, chunk_ids))
        endpoint = f"{ZEN_BASE_URL}/users/show_many.json?ids={ids_param}"
        response = None; current_progress = min(1.0, batch_num / total_batches)
        try:
            user_progress_text = f"Fetching user batch {batch_num}/{total_batches}... ({len(all_user_data)} found)"
            user_progress.progress(current_progress, text=user_progress_text)
            response = requests.get(endpoint, auth=ZEN_AUTH, timeout=30); response.raise_for_status()
            data = response.json(); users = data.get('users', [])
            for user in users: all_user_data[user['id']] = {'email': user.get('email')}
            time.sleep(0.5)
        except Exception as e: st.warning(f"Error fetching user batch {batch_num}: {e}") # Simplified
    user_progress.progress(1.0, text=f"User detail fetch complete. Found: {len(all_user_data)}.")
    return all_user_data