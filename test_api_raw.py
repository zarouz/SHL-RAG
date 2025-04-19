import requests
import json

# --- Configuration ---
API_ENDPOINT = "http://127.0.0.1:8001/recommend_raw" # Ensure this matches your running API host/port

# --- Choose a Test Query ---
# Option 1: Natural Language Query
# test_query = "I need assessments for a senior software engineer role focusing on Python and cloud technologies."

# Option 2: Job Description Text (example snippet)
# test_query = """
# We are seeking a highly motivated Senior Software Engineer to join our dynamic team.
# Responsibilities include designing, developing, and maintaining scalable software solutions.
# Must have strong proficiency in Python, experience with AWS or GCP, and excellent problem-solving skills.
# """

# Option 3: URL (ensure the URL is accessible and contains relevant text)
test_query = "https://jobs.lever.co/openai/653a7ccc-936a-4d79-9f61-116f69575d00" # Example URL

# --- Prepare Request ---
payload = {"query": test_query}

print(f"Sending query to: {API_ENDPOINT}")
print(f"Query: {test_query[:100]}...") # Print start of query

# --- Send Request ---
try:
    response = requests.post(API_ENDPOINT, json=payload, timeout=90) # Increased timeout for RAG + URL fetch

    print(f"\nStatus Code: {response.status_code}")

    # Check if the request was successful
    if response.status_code == 200:
        try:
            # Try to parse the JSON response
            response_json = response.json()
            print("\n--- Raw API Response (JSON) ---")
            print(json.dumps(response_json, indent=2))
            print("-----------------------------")
        except json.JSONDecodeError:
            print("\nError: Failed to decode JSON response from API.")
            print("Raw Response Text:")
            print(response.text)
    else:
        # Print error details if available
        print("\nError: API request failed.")
        try:
            error_details = response.json()
            print("Error Details (JSON):")
            print(json.dumps(error_details, indent=2))
        except json.JSONDecodeError:
            print("Raw Error Response Text:")
            print(response.text)

except requests.exceptions.Timeout:
    print("\nError: Request timed out. The API might be busy or taking too long.")
except requests.exceptions.ConnectionError:
    print(f"\nError: Could not connect to the API at {API_ENDPOINT}. Is the server running?")
except requests.exceptions.RequestException as e:
    print(f"\nError: An unexpected error occurred during the request: {e}")
