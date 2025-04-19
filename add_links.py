# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import csv
import os
from urllib.parse import urljoin, urlparse, unquote
import time
import re # For cleaning filenames
import logging

# --- Configuration ---
BASE_URL = "https://www.shl.com"
CATALOG_START_URL = "https://www.shl.com/solutions/products/product-catalog/"
# Corrected URL template based on observed site behavior (?start=...)
ITEMS_PER_PAGE = 12 # Deduced from start=12 for page 2
CATALOG_URL_TEMPLATE_WITH_PARAMS = "https://www.shl.com/solutions/products/product-catalog/?start={}&type=1&type=1"
MAX_PAGES = 32 # As identified from the website's pagination
CSV_FILENAME_LINKS = "shl_individual_solutions_links.csv" # New CSV file
REQUEST_DELAY = 1 # Seconds between requests
REQUEST_TIMEOUT = 30 # Seconds for requests to complete
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
TARGET_TABLE_HEADING_TEXT = "Individual Test Solutions" # Text to identify the correct table section

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Main Scraping Logic ---
def scrape_solution_links(start_url, url_template_with_params, items_per_page, max_pages, csv_filename, target_heading_text):
    """Scrapes SHL catalog across multiple pages FOR A SPECIFIC TABLE, extracting solution names and links."""
    log.info(f"Starting SHL Catalog Scrape for links related to '{target_heading_text}'...")
    all_solutions_links = []
    processed_detail_urls = set() # Keep track to avoid duplicates if items appear on multiple pages briefly

    with requests.Session() as session:
        session.headers.update(HEADERS)

        # --- Scrape Main Catalog Pages for the target table ---
        for page_num in range(1, max_pages + 1):
            # --- Correct URL Generation ---
            if page_num == 1:
                current_url = start_url
            else:
                start_index = (page_num - 1) * items_per_page
                current_url = url_template_with_params.format(start_index)
            # -----------------------------

            log.info(f"\n--- Scraping Catalog Page {page_num}: {current_url} ---")
            try:
                time.sleep(REQUEST_DELAY)
                response = session.get(current_url, timeout=REQUEST_TIMEOUT)

                # Optional: Save debug HTML if issues persist
                # debug_filename = f"debug_links_page_{page_num}.html"
                # try:
                #     with open(debug_filename, "w", encoding="utf-8") as f_debug:
                #         f_debug.write(response.text)
                #     log.info(f"  Saved full HTML of page {page_num} to {debug_filename} for inspection.")
                # except Exception as save_err:
                #     log.error(f"  Could not save debug HTML for page {page_num}: {save_err}")

                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')

                # --- Find the SPECIFIC "Individual Test Solutions" table ---
                # Strategy: Find all tables, then check their headers for the target text
                individual_solutions_table = None
                all_tables = soup.find_all('table')
                log.debug(f"  Found {len(all_tables)} table(s) on page {page_num}.")

                for table in all_tables:
                    # Find the header row (typically the first row)
                    header_row = table.find('tr')
                    if not header_row:
                        continue

                    # Find the specific header cell likely containing the title
                    # Using the class identified from debug HTML
                    title_header = header_row.find('th', class_='custom__table-heading__title')

                    if title_header:
                        header_text = title_header.get_text(strip=True)
                        # Use regex for case-insensitive match and ignore extra whitespace
                        if re.search(r'\s*' + re.escape(target_heading_text) + r'\s*', header_text, re.IGNORECASE):
                            individual_solutions_table = table
                            log.info(f"  Found target table with heading '{header_text}' in its <th>.")
                            break # Found the correct table
                    else:
                        log.debug("  Table found, but no <th class='custom__table-heading__title'> in header row.")


                if not individual_solutions_table:
                    log.error(f"  ERROR: Could not find the table associated with '{target_heading_text}' on page {page_num} ({current_url}). Skipping page.")
                    continue # Skip this page
                else:
                     log.info(f"  Successfully identified table for '{target_heading_text}'.")


                # --- Process ONLY the rows from the identified table ---
                # Use find_all on the table itself, skipping the first row (header)
                rows = individual_solutions_table.find_all('tr')[1:] # Skip header row more directly

                if not rows:
                    log.warning(f"  Table for '{target_heading_text}' found on page {page_num}, but contains no data rows.")
                    continue

                log.info(f"  Processing {len(rows)} solutions from '{target_heading_text}' table...")
                for row_index, row in enumerate(rows, start=1):
                    # Ensure it's a data row (contains <td>, not <th>)
                    cells = row.find_all('td')
                    if not cells:
                        log.warning(f"  Skipping row {row_index} as it contains no <td> cells (might be another header/footer row).")
                        continue

                    if len(cells) >= 1: # Need at least the first cell for name and link
                        try:
                            solution_cell = cells[0]
                            solution_link_tag = solution_cell.find('a', href=True)

                            if not solution_link_tag:
                                log.warning(f"  Skipping row {row_index} - No link found in first cell: {solution_cell.get_text(strip=True)}")
                                continue

                            solution_name = solution_link_tag.get_text(strip=True)
                            relative_detail_url = solution_link_tag['href']
                            absolute_detail_url = urljoin(BASE_URL, relative_detail_url)

                            # Avoid duplicates across pagination
                            if absolute_detail_url in processed_detail_urls:
                                log.info(f"  Skipping already processed solution link: {solution_name} ({absolute_detail_url})")
                                continue

                            log.info(f"  Found Solution: '{solution_name}', Link: '{absolute_detail_url}'")

                            solution_link_data = {
                                'Solution Name': solution_name,
                                'Detail URL': absolute_detail_url,
                            }
                            all_solutions_links.append(solution_link_data)
                            processed_detail_urls.add(absolute_detail_url)

                        except Exception as e:
                            log.error(f"  Error processing row {row_index} in '{target_heading_text}' table on page {page_num}: {e}", exc_info=True)
                            continue # Skip this row on error
                    else:
                         log.warning(f"  Skipping row {row_index} in '{target_heading_text}' table on page {page_num} due to insufficient cell count (<1). Row content: {row.get_text(strip=True)}")

            except requests.exceptions.Timeout:
                log.error(f" Error: Timeout fetching catalog page {page_num} ({current_url})")
                continue
            except requests.exceptions.RequestException as e:
                log.error(f" Error fetching catalog page {page_num} ({current_url}): {e}")
                if hasattr(e, 'response') and e.response is not None:
                    log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
                continue
            except Exception as e:
                log.error(f" Error parsing catalog page {page_num} ({current_url}): {e}", exc_info=True)
                continue

        log.info(f"\n--- Finished scraping catalog pages. Found {len(all_solutions_links)} unique solution links for '{target_heading_text}'. ---")


    # --- Write data to CSV ---
    if all_solutions_links:
        log.info(f"\nWriting {len(all_solutions_links)} records to {csv_filename}...")
        headers = ['Solution Name', 'Detail URL']
        try:
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(all_solutions_links)
            log.info(f"Scraping complete. Solution links saved to {csv_filename}")
        except IOError as e:
            log.critical(f"CRITICAL ERROR writing to CSV file {csv_filename}: {e}", exc_info=True)
        except Exception as e:
             log.critical(f"CRITICAL UNEXPECTED ERROR during CSV writing: {e}", exc_info=True)

    else:
        log.warning(f"\nNo solution links from '{target_heading_text}' were successfully scraped to write to CSV.")


# --- Run the Scraper ---
if __name__ == "__main__":
    scrape_solution_links(
        CATALOG_START_URL,
        CATALOG_URL_TEMPLATE_WITH_PARAMS,
        ITEMS_PER_PAGE,
        MAX_PAGES,
        CSV_FILENAME_LINKS, # Use the new filename
        TARGET_TABLE_HEADING_TEXT
    )