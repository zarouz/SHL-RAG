import streamlit as st
import requests
import json
import pandas as pd
import logging
import os

# --- API Endpoint Configuration ---
# Read API location from environment variable (set during deployment or locally)
# This should be the FULL base URL of the API service
# e.g., https://api-service-....run.app when deployed
# or http://127.0.0.1:8001 for local development
API_BASE_URL = os.getenv('API_HOST_URL', 'http://127.0.0.1:8001') # Default for local dev

RECOMMEND_ENDPOINT = f"{API_BASE_URL}/recommend"
HEALTH_ENDPOINT = f"{API_BASE_URL}/health"
# --- Setup Logging ---
# Initialize logging BEFORE first use
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

log.info(f"Connecting to API at: {API_BASE_URL}") # Log the determined API URL

# --- Test Type Mapping ---
TEST_TYPE_MAP = {
    "A": "Ability & Aptitude",
    "B": "Biodata & Situational",
    "C": "Competencies",
    "D": "Development & 360",
    "E": "Assessment Exercises",
    "K": "Knowledge & Skills",
    "P": "Personality & Behavior",
    "S": "Simulations"
}

# --- Helper Functions ---
def map_test_types(type_codes: list) -> str:
    """Maps test type codes to their full descriptions."""
    if not type_codes or not isinstance(type_codes, list):
        return "N/A"
    descriptions = [TEST_TYPE_MAP.get(code, code) for code in type_codes] # Use code itself if not found
    return ", ".join(descriptions)

def check_api_health():
    """Checks if the backend API is reachable."""
    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=5) # 5 second timeout
        if response.status_code == 200 and response.json().get("status") == "healthy":
            return True
        else:
            log.warning(f"API health check failed. Status: {response.status_code}, Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        log.error(f"API health check failed: Could not connect to {HEALTH_ENDPOINT}. Error: {e}")
        return False

def get_recommendations_from_api(query: str):
    """Calls the backend API to get recommendations."""
    payload = {"query": query}
    try:
        response = requests.post(RECOMMEND_ENDPOINT, json=payload, timeout=60) # 60 second timeout for RAG
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Check if response content type is JSON
        if 'application/json' in response.headers.get('Content-Type', ''):
             return response.json()
        else:
             log.error(f"API response was not JSON. Content-Type: {response.headers.get('Content-Type')}. Response text: {response.text[:500]}")
             st.error(f"Received non-JSON response from the API: {response.text[:200]}...")
             return None

    except requests.exceptions.HTTPError as http_err:
        log.error(f"HTTP error occurred: {http_err} - Response: {response.text}")
        st.error(f"Failed to get recommendations. API returned error {response.status_code}: {response.text}")
        return None
    except requests.exceptions.ConnectionError as conn_err:
        log.error(f"Connection error occurred: {conn_err}")
        st.error(f"Could not connect to the recommendation API at {RECOMMEND_ENDPOINT}. Is the backend running?")
        return None
    except requests.exceptions.Timeout as timeout_err:
        log.error(f"Request timed out: {timeout_err}")
        st.error("The request to the recommendation API timed out. The backend might be busy.")
        return None
    except requests.exceptions.RequestException as req_err:
        log.error(f"An unexpected error occurred during API request: {req_err}")
        st.error(f"An unexpected error occurred while contacting the API: {req_err}")
        return None
    except json.JSONDecodeError as json_err:
         log.error(f"Failed to decode JSON response: {json_err}. Response text: {response.text[:500]}")
         st.error(f"Failed to parse the API response: {response.text[:200]}...")
         return None


# --- Streamlit App Layout ---

st.set_page_config(page_title="SHL Assessment Recommender", layout="wide")

st.title("🧠 SHL Assessment Recommendation System")
st.caption("Enter a job description or query to find relevant SHL assessments.")

# --- API Health Check ---
with st.spinner("Checking backend API status..."):
    is_healthy = check_api_health()

if not is_healthy:
    st.error(f"The backend API at {API_BASE_URL} is not responding. Please ensure the FastAPI server (`src/api.py`) is running.")
    st.stop() # Stop execution if API is down
else:
    st.success(f"Backend API is healthy at {API_BASE_URL}")

st.divider()

# --- User Input ---
query = st.text_area(
    "Enter your query or job description:",
    height=150,
    placeholder="e.g., 'Looking for assessments for mid-level Python developers proficient in SQL and JavaScript, max duration 60 minutes.'"
)

# --- Submit Button ---
if st.button("Get Recommendations", type="primary"):
    if not query:
        st.warning("Please enter a query or job description.")
    else:
        with st.spinner("Finding relevant assessments... This may take a moment."):
            results = get_recommendations_from_api(query)

        st.divider()

        # --- Display Results ---
        if results and "recommended_assessments" in results:
            recommendations = results["recommended_assessments"]
            st.subheader(f"Top {len(recommendations)} Recommendations:")

            if not recommendations:
                st.info("No relevant assessments found for your query based on the available data.")
            else:
                # Prepare data for display (e.g., in a table)
                display_data = []
                for i, rec in enumerate(recommendations):
                    display_data.append({
                        "Rank": i + 1,
                        # Extract name from URL or metadata if available, otherwise use URL
                        "Assessment": f"[{rec.get('url', 'N/A').split('/')[-2] if rec.get('url') else 'Unknown'}]({rec.get('url', '#')})",
                        "Description": rec.get('description', 'N/A'),
                        "Duration (min)": rec.get('duration', 'N/A'),
                        "Test Type(s)": map_test_types(rec.get('test_type')), # Apply mapping here
                        "Remote": rec.get('remote_support', 'N/A'),
                        "Adaptive": rec.get('adaptive_support', 'N/A'),
                        "URL": rec.get('url', 'N/A') # Keep raw URL for potential copy/paste
                    })

                df = pd.DataFrame(display_data)

                # Display as Markdown table for clickable links
                st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

                # Optional: Display raw JSON response for debugging
                with st.expander("Show Raw JSON Response"):
                    st.json(results)

        else:
            # Error messages are handled within get_recommendations_from_api
            st.info("Could not retrieve recommendations. Please check the error message above or the backend logs.")

# --- Footer ---
st.divider()
