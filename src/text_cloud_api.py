import requests
import json

# URL of your deployed API service
api_url = "https://api-service-jekqxlmhva-uc.a.run.app/recommend"

# Job Description to test
job_description = "Looking to hire mid-level professionals who are proficient in Python, SQL and Java Script. Need an assessment package that can test all skills with max duration of 60 minutes."

# Data payload for the POST request
payload = {
    "query": job_description
}

print(f"Sending POST request to: {api_url}")
print(f"With data: {json.dumps(payload)}")

try:
    # Send the POST request
    response = requests.post(api_url, json=payload)

    # Raise an exception if the request was unsuccessful (e.g., 4xx or 5xx errors)
    response.raise_for_status()

    # Print the JSON response from the API
    print("\n--- API Response ---")
    print(json.dumps(response.json(), indent=2))
    print("--------------------\n")

except requests.exceptions.RequestException as e:
    print(f"\n--- Error ---")
    print(f"Request failed: {e}")
    # Print response body if available, even on error
    if hasattr(e, 'response') and e.response is not None:
        print(f"Response status code: {e.response.status_code}")
        try:
            print(f"Response body: {e.response.text}")
        except Exception:
            print("Could not read response body.")
    print("-------------\n")

except json.JSONDecodeError:
    print("\n--- Error ---")
    print("Failed to decode JSON response from the API.")
    print(f"Response status code: {response.status_code}")
    print(f"Response text: {response.text}")
    print("-------------\n")