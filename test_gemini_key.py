import os
import google.generativeai as genai
from dotenv import load_dotenv, find_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

def test_key():
    """Loads API key from .env and tests it with a simple Gemini request."""
    # Load environment variables from .env file
    dotenv_path = find_dotenv()
    if dotenv_path:
        log.info(f"Loading environment variables from: {dotenv_path}")
        load_dotenv(dotenv_path=dotenv_path)
    else:
        log.warning("No .env file found.")
        # Continue anyway, maybe key is in system env

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        log.error("GEMINI_API_KEY not found in environment variables (.env or system).")
        print("\nError: GEMINI_API_KEY not found in environment variables.")
        return

    log.info("Attempting to configure Google Generative AI...")
    try:
        genai.configure(api_key=api_key)
        log.info("Configuration successful.")
    except Exception as e:
        log.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
        print(f"\nError during configuration: {e}")
        return

    log.info("Initializing Gemini model (gemini-1.5-flash-latest)...")
    try:
        # Use a basic model for testing
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        log.info("Model initialized.")
    except Exception as e:
        log.error(f"Failed to initialize Gemini model: {e}", exc_info=True)
        print(f"\nError initializing model: {e}")
        return

    test_prompt = "Explain what an API key is in one sentence."
    log.info(f"Sending test prompt: '{test_prompt}'")
    print("\nSending test prompt to Gemini...")

    try:
        response = model.generate_content(test_prompt)
        log.info("Received response from Gemini.")
        # Check if response has text attribute
        if hasattr(response, 'text'):
            print("\n--- Gemini Response ---")
            print(response.text)
            print("----------------------")
            log.info("API Key appears to be valid.")
        else:
            # Check for blocked prompt or other issues
            log.warning(f"Gemini response did not contain expected text. Response object: {response}")
            try:
                 # Check safety feedback
                 feedback = response.prompt_feedback
                 log.warning(f"Prompt Feedback: {feedback}")
                 print(f"\nWarning: Prompt might have been blocked. Feedback: {feedback}")
            except AttributeError:
                 print(f"\nWarning: Received unexpected response format: {response}")

    except Exception as e:
        log.error(f"Error during Gemini API call: {e}", exc_info=True)
        print(f"\n--- Error during API call ---")
        print(f"{e}")
        print("-----------------------------")
        log.info("API Key appears to be invalid or there was another issue.")

if __name__ == "__main__":
    test_key()
