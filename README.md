# Zendesk Reporter Dashboard

A simple Streamlit dashboard to visualize basic Zendesk support metrics fetched via the Zendesk API. Includes basic password protection.

## Setup

1.  **Clone the repository (if applicable) or create the files as described.**
2.  **Create a Python virtual environment:**
    ```bash
    python -m venv venv
    ```
3.  **Activate the virtual environment:**
    * macOS/Linux: `source venv/bin/activate`
    * Windows: `venv\Scripts\activate`
4.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Create the `.env` file:**
    * Create a file named `.env` in the project root.
    * Add the following lines, replacing the placeholder values with your actual credentials and desired dashboard password:
      ```dotenv
      ZENDESK_SUBDOMAIN="your_subdomain"
      ZENDESK_EMAIL="your_login_email@example.com"
      ZENDESK_API_TOKEN="your_pasted_api_token"
      APP_PASSWORD="your_chosen_secure_password"
      ```
    * **IMPORTANT:** Do NOT commit this `.env` file to Git. Ensure `.env` is listed in your `.gitignore` file.

## Running Locally

Make sure your virtual environment is activated and the `.env` file is created. Then run:

```bash
streamlit run dashboard.py