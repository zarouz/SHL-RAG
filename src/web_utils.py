import requests
from bs4 import BeautifulSoup
import logging

log = logging.getLogger(__name__)

def extract_text_from_url(url: str) -> str:
    """
    Fetches content from a URL and extracts the main textual content.

    Args:
        url: The URL to fetch and parse.

    Returns:
        The extracted text content, or an error message if fetching/parsing fails.
    """
    log.info(f"Attempting to extract text from URL: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15) # 15 second timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Check content type - proceed only if it's likely HTML
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            log.warning(f"Content type for {url} is '{content_type}', not HTML. Skipping text extraction.")
            return f"Error: Content type is '{content_type}', not HTML."

        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()

        # Get text, strip leading/trailing whitespace, and reduce multiple newlines/spaces
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        if not text:
            log.warning(f"Could not extract meaningful text from {url} after parsing.")
            return "Error: Could not extract meaningful text from the page."

        log.info(f"Successfully extracted text from {url} (length: {len(text)}).")
        # Limit the returned text length if necessary (e.g., for token limits)
        max_length = 10000 # Example limit - adjust as needed
        if len(text) > max_length:
             log.warning(f"Extracted text from {url} truncated to {max_length} characters.")
             return text[:max_length] + "... (truncated)"
        return text

    except requests.exceptions.Timeout:
        log.error(f"Timeout occurred while fetching URL: {url}")
        return f"Error: Timeout occurred while fetching URL: {url}"
    except requests.exceptions.RequestException as e:
        log.error(f"Error fetching URL {url}: {e}", exc_info=True)
        return f"Error fetching URL: {e}"
    except Exception as e:
        log.error(f"Error parsing content from URL {url}: {e}", exc_info=True)
        return f"Error parsing content from URL: {e}"

if __name__ == '__main__':
    # Example usage for testing
    test_url = "https://streamlit.io/" # Replace with a real job description URL for better testing
    print(f"Testing URL: {test_url}")
    extracted = extract_text_from_url(test_url)
    print("\n--- Extracted Text ---")
    print(extracted)
    print("----------------------")
