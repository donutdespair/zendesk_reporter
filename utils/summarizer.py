# utils/summarizer.py
import google.generativeai as genai
from dotenv import load_dotenv
import os
import streamlit as st
# --- Import the specific error ---
from streamlit.errors import StreamlitSecretNotFoundError

# --- Global Variables for Gemini Client ---
GEMINI_API_KEY = None
gemini_model = None
gemini_configured = False # Flag to track configuration status

# --- Corrected Configuration Logic ---
def configure_gemini():
    """Configures the Gemini client using secrets or env vars."""
    global GEMINI_API_KEY, gemini_model, gemini_configured
    if gemini_configured: return True # Avoid re-configuring

    gemini_key_secret = None
    try: gemini_key_secret = st.secrets.get("GEMINI_API_KEY")
    except StreamlitSecretNotFoundError: pass
    except AttributeError: pass
    except Exception as e: st.warning(f"Error accessing secrets for Gemini: {e}")

    gemini_key_env = os.getenv("GEMINI_API_KEY")
    GEMINI_API_KEY = gemini_key_secret if gemini_key_secret is not None else gemini_key_env

    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            # --- MODEL SELECTION ---
            # Using flash for speed, uncomment pro for potentially more detail
            gemini_model = genai.GenerativeModel("gemini-1.5-flash")
            # gemini_model = genai.GenerativeModel("gemini-1.5-pro") # <-- Option for more robust model
            # --- END MODEL SELECTION ---
            gemini_configured = True
            print("Gemini API configured successfully.")
            return True
        except Exception as e:
            print(f"ERROR: Failed to configure Google Gemini API client: {e}")
            gemini_configured = False
            return False
    else:
        print("WARN: GEMINI_API_KEY could not be found.")
        gemini_configured = False
        return False

# Initial configuration attempt (safe to call even if already configured)
configure_gemini()

def summarize_text(text_to_summarize):
    """Summarizes the provided text using the configured Google Gemini model."""
    if not gemini_configured or not gemini_model:
        if not configure_gemini(): # Attempt re-configuration
             return "Error: Gemini API is not configured. Check API Key/Configuration."

    if not text_to_summarize or not text_to_summarize.strip():
        return "Error: No text provided to summarize."

    print(f"Sending text (length: {len(text_to_summarize)}) to Gemini for summarization...")
    try:
        # --- V V V --- UPDATED, MORE DETAILED PROMPT --- V V V ---
        prompt = f"""Generate a comprehensive summary of the following support ticket conversation thread. Your summary should clearly state:
1.  The initial problem or question reported by the requester.
2.  The key troubleshooting steps taken or main points discussed between the participants.
3.  The final resolution, outcome, or the current status if still ongoing.
Please write in clear, complete sentences and provide sufficient detail to understand the ticket's history and conclusion. Avoid overly brief or vague statements. Ignore standard email signatures or repeated pleasantries.

Conversation Text:
---
{text_to_summarize}
---

Comprehensive Summary:"""
        # --- ^ ^ ^ --- UPDATED, MORE DETAILED PROMPT --- ^ ^ ^ ---

        response = gemini_model.generate_content(prompt)

        # ... (Response checking logic remains the same) ...
        if hasattr(response, 'candidates') and response.candidates:
             candidate = response.candidates[0]
             if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and candidate.content.parts: pass
             else:
                  finish_reason = getattr(candidate, 'finish_reason', None); safety_info = getattr(candidate, 'safety_ratings', [])
                  print(f"WARN: Gemini stopped. Reason: {finish_reason}. Safety: {safety_info}"); return f"Error: Content generation stopped (Reason: {finish_reason})."
        elif hasattr(response, 'prompt_feedback') and hasattr(response.prompt_feedback, 'block_reason'): block_reason = response.prompt_feedback.block_reason; print(f"WARN: Gemini prompt blocked: {block_reason}"); return f"Error: Prompt blocked (Reason: {block_reason})."
        else: print(f"WARN: Unexpected Gemini response: {response}"); return "Error: Invalid response structure."

        # Safely extract text
        if hasattr(response, 'text'): return response.text
        else:
             try: return "".join(part.text for part in response.candidates[0].content.parts)
             except Exception: return "Error: Could not extract text parts."

    except Exception as e:
        error_message = f"Error during summarization: {type(e).__name__} - {e}"
        print(f"ERROR: {error_message}")
        return error_message