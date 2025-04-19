# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import csv
import os
from urllib.parse import urljoin, urlparse
import time
import re
import logging

# --- Configuration ---
INPUT_CSV_FILENAME = "shl_individual_solutions_links.csv" # Your CORRECT input file with Detail URLs
OUTPUT_CSV_FILENAME = "shl_solution_additional_details_v2.csv" # New output filename
REQUEST_DELAY = 1
REQUEST_TIMEOUT = 30
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
DEBUG_FOLDER = "debug_detail_pages_v2" # Separate debug folder

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Helper Function to Sanitize Filenames (used for debug files) ---
def sanitize_filename(filename):
    """Removes invalid characters and shortens long filenames."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = sanitized.replace(' ', '_')
    max_len = 150
    if len(sanitized) > max_len:
        name, ext = os.path.splitext(sanitized)
        ext = ext[:10] if len(ext) > 10 else ext
        name = name[:max_len - len(ext) -1]
        sanitized = name + ext
    sanitized = sanitized.strip('._ ')
    if not sanitized:
        sanitized = f"sanitized_file_{int(time.time())}"
    return sanitized

# --- Function to Scrape Detail Page for Text Info Only (Revised) ---
def scrape_detail_page_for_text(detail_url, session):
    """Scrapes specified details ONLY from a single product detail page."""
    details = {
        'Description': 'N/A',
        'Job Levels': 'N/A',
        'Languages': 'N/A',
        'Assessment Length': 'N/A',
    }
    try:
        log.info(f" Visiting detail page: {detail_url}")
        time.sleep(REQUEST_DELAY)
        response = session.get(detail_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

        # --- Save debug HTML for analysis if scraping fails ---
        os.makedirs(DEBUG_FOLDER, exist_ok=True)
        path_part = urlparse(detail_url).path.strip('/')
        safe_filename_part = sanitize_filename(path_part.split('/')[-1] or "index")
        debug_filename = os.path.join(DEBUG_FOLDER, f"debug_detail_{safe_filename_part}.html")
        try:
            with open(debug_filename, "w", encoding="utf-8") as f_debug:
                f_debug.write(response.text)
            # log.info(f"  Saved detail page HTML to {debug_filename}") # Optional: log on success
        except Exception as save_err:
            log.error(f"  Could not save debug detail HTML for {detail_url}: {save_err}")
        # --- End debug HTML saving ---

        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # --- Revised Strategy: Find Heading -> Find Next Paragraph ---
        headings_to_find = {
            "Description": "Description",
            "Job levels": "Job Levels", # Case-insensitive search handles variation
            "Languages": "Languages",
            "Assessment length": "Assessment Length" # Case-insensitive search handles variation
        }

        # Search within a common content area first if possible
        content_area = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup.find('body') or soup
        if not content_area:
            log.error("   Critical error: Could not find body tag.")
            return details # Return defaults

        for heading_text, detail_key in headings_to_find.items():
            # Find the heading tag (h1-h5) containing the text (case-insensitive)
            # Allow for slight variations in spacing/casing
            heading_tag = content_area.find(['h1', 'h2', 'h3', 'h4', 'h5'],
                                            string=re.compile(r'\s*' + re.escape(heading_text) + r'\s*', re.IGNORECASE))

            if heading_tag:
                # Find the immediately following <p> tag
                next_p = heading_tag.find_next_sibling('p')
                # If not immediate sibling, maybe a div wrapper, check next element first child
                if not next_p:
                    next_elem = heading_tag.find_next_sibling()
                    if next_elem and next_elem.find('p'):
                         next_p = next_elem.find('p') # Check inside next sibling

                if next_p:
                    value_text = next_p.get_text(strip=True)
                    if value_text:
                        # Specific cleaning for assessment length
                        if detail_key == "Assessment Length":
                             match = re.search(r'\d+', value_text) # Get first sequence of digits
                             if match:
                                 details[detail_key] = match.group(0)
                                 log.info(f"   Found {detail_key}: '{details[detail_key]}' (extracted number)")
                             else:
                                 details[detail_key] = value_text # Keep original if no number found
                                 log.warning(f"   Found {detail_key} text '{value_text}' but couldn't extract number.")
                        else:
                             details[detail_key] = value_text.strip(',.') # General cleanup
                             log.info(f"   Found {detail_key}: '{details[detail_key][:60]}...'")
                    else:
                        log.warning(f"   Found heading '{heading_text}' but next <p> was empty.")
                else:
                    log.warning(f"   Found heading '{heading_text}' but couldn't find a following <p> tag.")
            # else:
                 #log.debug(f"   Heading '{heading_text}' not found on page.") # Optional

        # Final check for missing values
        for key, value in details.items():
            if value == 'N/A':
                log.warning(f"   Could not find value for '{key}' for {detail_url}")


    except requests.exceptions.Timeout:
        log.error(f" Error: Timeout accessing detail page {detail_url}")
    except requests.exceptions.RequestException as e:
        log.error(f" Error accessing detail page {detail_url}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
    except Exception as e:
        log.error(f" Error parsing detail page {detail_url}: {e}", exc_info=True)

    # Return only the requested text details
    return {
        'Description': details['Description'],
        'Job Levels': details['Job Levels'],
        'Languages': details['Languages'],
        'Assessment Length': details['Assessment Length']
    }


# --- Main Logic ---
def process_existing_csv(input_csv, output_csv):
    """Reads URLs from input CSV, scrapes details, writes to output CSV."""
    log.info(f"Starting detail scraping process.")
    log.info(f"Reading solutions from: {input_csv}")
    log.info(f"Writing details to: {output_csv}")

    solutions_to_process = []
    try:
        with open(input_csv, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            if 'Detail URL' not in reader.fieldnames:
                 log.critical(f"CRITICAL ERROR: Input CSV '{input_csv}' must contain a 'Detail URL' column.")
                 return

            for i, row in enumerate(reader):
                solution_name = row.get('Solution Name')
                detail_url = row.get('Detail URL')

                if not solution_name:
                    log.warning(f"Skipping row {i+1} due to missing 'Solution Name': {row}")
                    continue
                if not detail_url or not detail_url.startswith('http'):
                     log.warning(f"Skipping row {i+1} for '{solution_name}' due to missing or invalid 'Detail URL': '{detail_url}'")
                     continue

                solutions_to_process.append({'Solution Name': solution_name, 'Detail URL': detail_url})

    except FileNotFoundError:
        log.critical(f"CRITICAL ERROR: Input file not found: {input_csv}")
        return
    except Exception as e:
        log.critical(f"CRITICAL ERROR reading input CSV '{input_csv}': {e}", exc_info=True)
        return

    log.info(f"Found {len(solutions_to_process)} solutions with valid URLs to process.")

    detailed_data = []
    processed_urls = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for i, solution in enumerate(solutions_to_process):
            log.info(f"\n--- Processing {i+1}/{len(solutions_to_process)}: {solution['Solution Name']} ---")
            detail_url = solution['Detail URL']

            if not detail_url.startswith('http'):
                log.error(f"Invalid URL format passed for processing: '{detail_url}'. Skipping.")
                continue

            if detail_url in processed_urls:
                log.warning(f"Skipping duplicate URL encountered during processing: {detail_url}")
                continue

            scraped_details = scrape_detail_page_for_text(detail_url, session)

            # Combine original name with scraped details
            combined_data = {
                'Solution Name': solution['Solution Name'],
                **scraped_details # Unpack the dictionary returned by the scraper
            }
            detailed_data.append(combined_data)
            processed_urls.add(detail_url)

    # --- Write data to Output CSV ---
    if detailed_data:
        log.info(f"\nWriting {len(detailed_data)} records to {output_csv}...")
        headers = ['Solution Name', 'Description', 'Job Levels', 'Languages', 'Assessment Length']
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as outfile:
                writer = csv.DictWriter(outfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(detailed_data)
            log.info(f"Detail scraping complete. Data saved to {output_csv}")
        except IOError as e:
            log.critical(f"CRITICAL ERROR writing to output CSV file {output_csv}: {e}", exc_info=True)
        except Exception as e:
             log.critical(f"CRITICAL UNEXPECTED ERROR during output CSV writing: {e}", exc_info=True)
    else:
        log.warning("\nNo detailed data was successfully scraped to write to the output CSV.")


# --- Run the Detail Scraper ---
if __name__ == "__main__":
    if not os.path.exists(INPUT_CSV_FILENAME):
        log.critical(f"Input CSV file '{INPUT_CSV_FILENAME}' not found. Please ensure it exists and is correctly named.")
    else:
        process_existing_csv(INPUT_CSV_FILENAME, OUTPUT_CSV_FILENAME)