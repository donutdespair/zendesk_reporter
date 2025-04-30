# utils/zendesk_api.py

import requests
import time
import os
import json
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError # Keep import just in case, though we aim to avoid calling it

# Global variables
ZEN_AUTH = None
ZEN_BASE_URL = None

# --- V V V --- UPDATED configure_api_client with conditional check --- V V V ---
def configure_api_client():
    """
    Sets up global authentication tuple and base URL.
    Checks for Streamlit secrets file existence. Uses st.secrets if found (cloud),
    otherwise uses os.getenv (local .env).
    Returns True on success, False on failure (and stops Streamlit).
    """
    global ZEN_AUTH, ZEN_BASE_URL
    if ZEN_AUTH is not None and ZEN_BASE_URL is not None: return True # Avoid reconfiguring

    subdomain = None
    email = None
    api_token = None

    # Check if Streamlit secrets file exists (common on SCC, less likely locally unless created)
    # Look in standard project location first, then global user location.
    secrets_path_project = os.path.join(".streamlit", "secrets.toml")
    secrets_path_global = os.path.expanduser("~/.streamlit/secrets.toml")
    use_st_secrets = os.path.exists(secrets_path_project) or os.path.exists(secrets_path_global)

    if use_st_secrets:
        print("INFO: Found Streamlit secrets file. Attempting to read Zendesk credentials from st.secrets.")
        try:
            subdomain = st.secrets.get("ZENDESK_SUBDOMAIN")
            email = st.secrets.get("ZENDESK_EMAIL")
            api_token = st.secrets.get("ZENDESK_API_TOKEN")
            # Check if keys actually exist within the secrets
            if not all([subdomain, email, api_token]):
                 st.warning("One or more Zendesk keys missing from Streamlit secrets file. Will check .env.")
                 # Allow fallback by not setting keys if missing
                 subdomain = subdomain or None # Ensure None if empty string/missing
                 email = email or None
                 api_token = api_token or None
        except Exception as e:
            # Catch other errors reading secrets
            st.warning(f"Error reading Streamlit secrets for Zendesk: {e}. Will check .env.")
            subdomain = None; email = None; api_token = None # Ensure fallback
    else:
        print("INFO: Streamlit secrets file not found. Reading Zendesk credentials from environment variables (.env).")
        # Fallback directly to environment variables if secrets file doesn't exist
        pass # Variables will be fetched below using os.getenv

    # Use environment variables if secrets didn't provide all values
    if not subdomain: subdomain = os.getenv("ZENDESK_SUBDOMAIN")
    if not email: email = os.getenv("ZENDESK_EMAIL")
    if not api_token: api_token = os.getenv("ZENDESK_API_TOKEN")

    # Final validation
    if not all([subdomain, email, api_token]):
        st.error("Configuration Error: Zendesk API credentials could not be found in Streamlit secrets OR .env file.")
        st.stop(); return False

    ZEN_AUTH = (f"{email}/token", api_token)
    ZEN_BASE_URL = f"https://{subdomain}.zendesk.com/api/v2"
    print("Zendesk API client configured successfully.")
    return True
# --- ^ ^ ^ --- END UPDATED configure_api_client --- ^ ^ ^ ---


# --- fetch_recent_tickets_cached function (No changes needed from last version) ---
@st.cache_data(ttl=600)
def fetch_recent_tickets_cached(start_time_unix):
    # ... (Function code remains the same) ...
    if not configure_api_client(): return []
    tickets = []; endpoint = f"{ZEN_BASE_URL}/incremental/tickets/cursor.json"; params = {'start_time': start_time_unix}
    page_count = 0; max_pages = 100; total_fetched = 0; progress_bar = st.progress(0, text=f"Fetching tickets..."); progress_value = 0.0
    while endpoint and page_count < max_pages:
        response = None; progress_value = min(1.0, page_count / max_pages if max_pages > 0 else 0)
        try:
            response = requests.get(endpoint, params=params, auth=ZEN_AUTH, timeout=30); response.raise_for_status()
            data = response.json(); page_tickets = data.get('tickets', []); tickets.extend(page_tickets); total_fetched += len(page_tickets)
            progress_value = min(1.0, (page_count + 1) / max_pages if max_pages > 0 else 1.0); current_progress_text = f"Fetching tickets... (Page {page_count + 1}, Total: {total_fetched:,})"; progress_bar.progress(progress_value, text=current_progress_text)
            if data.get('end_of_stream', True): final_text = f"Ticket fetch complete. Total: {total_fetched:,}"; endpoint = None
            else: endpoint = data.get('after_url'); params = {};
            if not endpoint and not data.get('end_of_stream', True): st.warning("API error: Missing 'after_url'."); final_text = f"Incomplete fetch. Total: {total_fetched:,}"; endpoint = None
            page_count += 1; time.sleep(0.5)
        except Exception as e: st.error(f"Error fetching tickets (Page {page_count+1}): {e}"); final_text = f"Error fetching tickets page {page_count + 1}."; endpoint = None
    final_progress = 1.0 if endpoint is None else progress_value;
    if 'final_text' not in locals(): final_text = f"Ticket fetch complete. Total: {total_fetched:,}"
    if page_count == max_pages and endpoint: st.warning(f"Max pages ({max_pages}) reached tickets."); final_text = f"Max pages reached tickets. Total: {total_fetched:,}"
    elif total_fetched == 0 and endpoint is None: final_text = "No tickets found."
    if endpoint is None: final_progress = 1.0; progress_bar.progress(final_progress, text=final_text)
    return tickets

# --- fetch_recent_ticket_events_cached function (No changes needed from last version) ---
@st.cache_data(ttl=600)
def fetch_recent_ticket_events_cached(start_time_unix):
    # ... (Function code remains the same) ...
    if not configure_api_client(): return []
    ticket_events = []; endpoint = f"{ZEN_BASE_URL}/incremental/ticket_events.json"; params = {'start_time': start_time_unix, 'include': 'comment_events'}
    page_count = 0; max_pages = 200; total_fetched = 0; event_progress_bar = st.progress(0, text="Fetching ticket events..."); progress_value = 0.0
    while endpoint and page_count < max_pages:
        response = None; progress_value = min(1.0, page_count / max_pages if max_pages > 0 else 0)
        try:
            current_params = params if page_count == 0 else {}; response = requests.get(endpoint, params=current_params, auth=ZEN_AUTH, timeout=45); response.raise_for_status()
            data = response.json(); page_events = data.get('ticket_events', []); ticket_events.extend(page_events); total_fetched += len(page_events)
            progress_value = min(1.0, (page_count + 1) / max_pages if max_pages > 0 else 1.0); current_progress_text = f"Fetching ticket events... (Page {page_count + 1}, Total: {total_fetched:,})"; event_progress_bar.progress(progress_value, text=current_progress_text)
            is_end = data.get('end_of_stream', False); next_page_url = data.get('next_page')
            if is_end or next_page_url is None: final_text = f"Event fetch complete. Total: {total_fetched:,}"; endpoint = None
            else: endpoint = next_page_url
            page_count += 1; time.sleep(0.5)
        except Exception as e: st.error(f"Error fetching events (Page {page_count+1}): {e}"); final_text = f"Error fetching events page {page_count + 1}."; endpoint = None
    final_progress = 1.0 if endpoint is None else progress_value;
    if 'final_text' not in locals(): final_text = f"Event fetch complete. Total: {total_fetched:,}"
    if page_count == max_pages and endpoint: st.warning(f"Max pages ({max_pages}) reached events."); final_text = f"Max pages reached events. Total: {total_fetched:,}"
    elif total_fetched == 0 and endpoint is None: final_text = "No events found."
    if endpoint is None: final_progress = 1.0; event_progress_bar.progress(final_progress, text=final_text)
    return ticket_events


# --- fetch_user_details function (No changes needed from last version) ---
@st.cache_data(ttl=3600)
def fetch_user_details(user_ids):
    # ... (Function code remains the same) ...
    if not configure_api_client(): return {}
    if not user_ids: return {}
    all_user_data = {}; unique_ids = list(set(int(uid) for uid in user_ids if pd.notna(uid) and isinstance(uid, (int, float)) and uid > 0))
    if not unique_ids: return {}
    total_batches = (len(unique_ids) + 99) // 100; user_progress = st.progress(0, text=f"Fetching user details..."); current_progress = 0.0
    for i in range(0, len(unique_ids), 100): # Loop through batches
        batch_num = i // 100 + 1; chunk_ids = unique_ids[i:i+100]; ids_param = ",".join(map(str, chunk_ids)); endpoint = f"{ZEN_BASE_URL}/users/show_many.json?ids={ids_param}"; response = None; current_progress = min(1.0, batch_num / total_batches)
        try:
            user_progress_text = f"Fetching user batch {batch_num}/{total_batches}... ({len(all_user_data)} found)"; user_progress.progress(current_progress, text=user_progress_text); response = requests.get(endpoint, auth=ZEN_AUTH, timeout=30); response.raise_for_status(); data = response.json(); users = data.get('users', []);
            for user in users: all_user_data[user['id']] = {'email': user.get('email')}
        except Exception as e: st.warning(f"Error fetching user batch {batch_num}: {type(e).__name__} - {e}")
        if total_batches > 1 and batch_num < total_batches : time.sleep(0.5) # Pause between batches
    user_progress.progress(1.0, text=f"User detail fetch complete. Found: {len(all_user_data)}.")
    return all_user_data


# --- fetch_ticket_comments function (No changes needed from last version) ---
def fetch_ticket_comments(ticket_id):
    # ... (Function code remains the same) ...
    if not configure_api_client(): return None, "Error: Zendesk credentials not configured."
    if not ticket_id or not isinstance(ticket_id, int) or ticket_id <= 0: return None, "Error: Invalid Ticket ID."
    all_comments_text = []; endpoint = f"{ZEN_BASE_URL}/tickets/{ticket_id}/comments.json"; page = 1; max_pages = 20
    # print(f"Fetching comments for ticket {ticket_id}...")
    while endpoint and page <= max_pages:
        response = None
        try:
            response = requests.get(endpoint, auth=ZEN_AUTH, timeout=20)
            if response.status_code == 404: return None, f"Error: Ticket ID {ticket_id} not found or comments inaccessible."
            if response.status_code == 429: retry_after = int(response.headers.get("Retry-After", 10)); st.warning(f"Rate limit comments. Retrying after {retry_after}s..."); time.sleep(retry_after); continue
            response.raise_for_status(); data = response.json(); comments = data.get('comments', [])
            if not comments and page == 1: break
            for comment in comments: body = comment.get('plain_body', comment.get('body', ''));
            if body: all_comments_text.append(body.strip())
            endpoint = data.get('next_page'); page += 1
            if endpoint: time.sleep(0.3)
        except requests.exceptions.RequestException as e: error_msg = f"Network error comments: {e}"; print(f"ERROR: {error_msg}"); return None, error_msg
        except json.JSONDecodeError as e: error_msg = f"Error decoding comment JSON: {e}. Response: {response.text[:200] if response else 'N/A'}"; print(f"ERROR: {error_msg}"); return None, error_msg
        except Exception as e: error_msg = f"Unexpected error comments: {type(e).__name__} - {e}"; print(f"ERROR: {error_msg}"); return None, error_msg
    if page > max_pages: st.warning(f"Reached max pages ({max_pages}) fetching comments for ticket {ticket_id}.")
    if not all_comments_text: return None, f"No text comments found for ticket ID {ticket_id}."
    separator = "\n\n" + "="*20 + "\n\n"; return separator.join(all_comments_text), None