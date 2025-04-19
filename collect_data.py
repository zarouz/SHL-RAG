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
CSV_FILENAME = "shl_individual_solutions_data.csv"
PDF_FOLDER = "pdfs_individual"
REQUEST_DELAY = 1 # Seconds between requests
REQUEST_TIMEOUT = 30 # Seconds for requests to complete
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
TARGET_TABLE_HEADING_TEXT = "Individual Test Solutions" # Text to identify the correct table section

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Helper Function to Sanitize Filenames ---
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

# --- Helper Function to Download PDF ---
def download_pdf(pdf_url, folder, session):
    """Downloads a PDF from a URL into the specified folder using a session."""
    pdf_filename = None
    local_filepath = None
    try:
        log.info(f"  Attempting to download PDF: {pdf_url}")
        time.sleep(REQUEST_DELAY)
        response = session.get(pdf_url, stream=True, timeout=60, headers=HEADERS, allow_redirects=True)
        response.raise_for_status()

        content_disposition = response.headers.get('content-disposition')
        if content_disposition:
            filenames = re.findall(r'filename\*=(?:UTF-8\'\')?([^;]+)|filename="([^"]+)"', content_disposition, flags=re.IGNORECASE)
            if filenames:
                utf8_filename, quoted_filename = filenames[0]
                raw_filename = utf8_filename if utf8_filename else quoted_filename
                if raw_filename:
                    raw_filename = raw_filename.strip().strip('"')
                    try:
                        pdf_filename = unquote(raw_filename, encoding='utf-8', errors='strict')
                    except UnicodeDecodeError:
                        log.warning(f"    UTF-8 decode failed for filename '{raw_filename}', trying latin-1.")
                        try:
                            pdf_filename = unquote(raw_filename, encoding='latin-1')
                        except Exception as decode_err:
                             log.error(f"    Could not decode filename '{raw_filename}' with latin-1: {decode_err}")
                             pdf_filename = None

        if not pdf_filename:
            parsed_url = urlparse(pdf_url)
            path_part = unquote(parsed_url.path)
            if path_part and path_part != '/':
                pdf_filename = os.path.basename(path_part)
            if not pdf_filename or '.' not in pdf_filename :
                 pdf_filename = f"downloaded_pdf_{int(time.time())}.pdf"
                 log.warning(f"    Could not derive filename from header or URL path for {pdf_url}. Using generic name: {pdf_filename}")

        filename_base = pdf_filename.split('?')[0].split('#')[0]
        if not filename_base.lower().endswith('.pdf'):
             pdf_filename = filename_base + ".pdf"
        else:
             pdf_filename = filename_base

        pdf_filename = sanitize_filename(pdf_filename)
        local_filepath = os.path.join(folder, pdf_filename)

        log.info(f"  Saving PDF as: {local_filepath}")
        with open(local_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info(f"  Successfully downloaded {pdf_filename}")
        return local_filepath

    except requests.exceptions.Timeout:
        log.error(f"  Error: Timeout downloading {pdf_url}")
    except requests.exceptions.SSLError as ssl_err:
        log.error(f"  Error: SSL error downloading {pdf_url}: {ssl_err}")
    except requests.exceptions.RequestException as e:
        log.error(f"  Error downloading {pdf_url}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
    except OSError as e:
        log.error(f"  OS Error saving PDF {pdf_filename} (check permissions/path validity): {e}")
    except Exception as e:
        log.error(f"  An unexpected error occurred during download of {pdf_url}: {e}", exc_info=True)
    return None

# --- Function to Scrape a Single Detail Page ---
def scrape_detail_page(detail_url, session):
    """Scrapes PDF links from a single product detail page."""
    pdf_links = []
    try:
        log.info(f" Visiting detail page: {detail_url}")
        time.sleep(REQUEST_DELAY)
        response = session.get(detail_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        possible_headers = soup.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'p'],
                                         string=lambda t: t and "download" in t.strip().lower())
        download_section = None
        if possible_headers:
            log.info(f"   Found {len(possible_headers)} potential 'Downloads' related elements.")
            for header in possible_headers:
                 log.debug(f"    - Checking element: <{header.name}> {header.get_text(strip=True)}")
                 current_element = header
                 search_depth = 0
                 found_container = False
                 while current_element and search_depth < 5:
                     sibling = current_element.find_next_sibling(['div', 'ul', 'p', 'section', 'article'])
                     if sibling:
                         pdf_anchor = sibling.find('a', href=lambda href: href and isinstance(href, str) and href.lower().endswith('.pdf'))
                         if pdf_anchor:
                             download_section = sibling
                             log.info(f"   Found likely download section after <{header.name}>: <{sibling.name}>")
                             found_container = True
                             break
                         current_element = sibling
                     else:
                          if current_element.parent:
                             current_element = current_element.parent
                          else:
                             break
                     search_depth += 1
                 if found_container:
                     break

            if not download_section:
                 log.warning(f"   Could not find a specific container after 'Downloads' headers. Searching common content areas.")
                 download_section = soup.find('main') or soup.find('article') or soup.find('div', id='content') or soup.find('div', class_='content') or soup.find('body') or soup
                 if not download_section:
                    log.warning(f"   No main content area found either. Searching entire page for PDFs.")
                    download_section = soup

        else:
            log.warning(f"  'Downloads' section header not identified on {detail_url}. Searching entire page.")
            download_section = soup

        if download_section:
             links = download_section.find_all('a', href=lambda href: href and isinstance(href, str) and href.lower().strip().endswith('.pdf'))
             unique_links = set()
             for link in links:
                href = link.get('href', '').strip()
                if href:
                    absolute_pdf_url = urljoin(detail_url, href)
                    if absolute_pdf_url.startswith('http'):
                        if absolute_pdf_url not in unique_links:
                            pdf_links.append(absolute_pdf_url)
                            unique_links.add(absolute_pdf_url)
                            log.info(f"   Found PDF link: {absolute_pdf_url}")
                    else:
                        log.debug(f"    Skipping non-http link: {absolute_pdf_url}")


        if not pdf_links:
             log.warning(f"  No PDF download links found on {detail_url}")

    except requests.exceptions.Timeout:
        log.error(f" Error: Timeout accessing detail page {detail_url}")
    except requests.exceptions.RequestException as e:
        log.error(f" Error accessing detail page {detail_url}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
    except Exception as e:
        log.error(f" Error parsing detail page {detail_url}: {e}", exc_info=True)

    return pdf_links

# --- Main Scraping Logic ---
def scrape_shl_catalog_multi_page(start_url, url_template_with_params, items_per_page, max_pages, pdf_folder, csv_filename, target_heading_text):
    """Scrapes SHL catalog across multiple pages FOR A SPECIFIC TABLE, visits detail pages, downloads PDFs."""
    log.info(f"Starting SHL Catalog Scrape for tables related to '{target_heading_text}'...")
    os.makedirs(pdf_folder, exist_ok=True)
    all_solutions_data = []
    processed_detail_urls = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        for page_num in range(1, max_pages + 1):
            if page_num == 1:
                current_url = start_url
            else:
                start_index = (page_num - 1) * items_per_page
                current_url = url_template_with_params.format(start_index)

            log.info(f"\n--- Scraping Catalog Page {page_num}: {current_url} ---")
            try:
                time.sleep(REQUEST_DELAY)
                response = session.get(current_url, timeout=REQUEST_TIMEOUT)
                debug_filename = f"debug_page_{page_num}.html"
                try:
                    with open(debug_filename, "w", encoding="utf-8") as f_debug:
                        f_debug.write(response.text)
                    log.info(f"  Saved full HTML of page {page_num} to {debug_filename} for inspection.")
                except Exception as save_err:
                    log.error(f"  Could not save debug HTML for page {page_num}: {save_err}")

                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')

                # --- Find the SPECIFIC "Individual Test Solutions" table ---
                individual_solutions_table = None

                # Revised Strategy: Find the <th> with the text, then find its parent <table>
                heading_th = soup.find('th', class_='custom__table-heading__title', # Be more specific with class
                                       string=re.compile(r'\s*' + re.escape(target_heading_text) + r'\s*', re.IGNORECASE))

                if heading_th:
                    log.info(f"  Found potential heading element: <{heading_th.name}> containing text '{heading_th.get_text(strip=True)}'")
                    # Navigate upwards to find the parent table
                    parent_table = heading_th.find_parent('table')
                    if parent_table:
                        individual_solutions_table = parent_table
                        log.info("  Found parent table by navigating up from the heading <th>.")
                    else:
                        log.warning("  Found heading <th> but could not find its parent <table>.")
                else:
                     log.warning(f"  Heading '{target_heading_text}' not found within a 'th.custom__table-heading__title'.")
                     # Fallback: Keep the container search as a last resort
                     table_wrapper = soup.find('div', class_='custom__table-wrapper')
                     if table_wrapper:
                         log.info("  Fallback: Found '.custom__table-wrapper'. Searching for table within it.")
                         potential_table = table_wrapper.find('table')
                         if potential_table:
                             # Check if this specific table *contains* the target heading th
                             heading_in_table = potential_table.find('th', class_='custom__table-heading__title',
                                                                     string=re.compile(r'\s*' + re.escape(target_heading_text) + r'\s*', re.IGNORECASE))
                             if heading_in_table:
                                 individual_solutions_table = potential_table
                                 log.info(f"  Fallback: Found target table inside '.custom__table-wrapper' (contains target heading).")
                             else:
                                 log.warning(" Fallback: Found table in wrapper, but it does not contain the target heading <th>.")
                         else:
                             log.warning(" Fallback: '.custom__table-wrapper' did not contain a table.")
                     else:
                        log.warning(" Fallback: '.custom__table-wrapper' not found on the page either.")


                # --- Final Check and Processing ---
                if not individual_solutions_table:
                    log.error(f"  ERROR: Could not find the table associated with '{target_heading_text}' on page {page_num} ({current_url}). Check debug_page_{page_num}.html. Skipping page.")
                    continue
                else:
                     log.info(f"  Successfully identified table for '{target_heading_text}'.")

                # --- Process Rows ---
                rows = individual_solutions_table.find_all('tr')
                if len(rows) <= 1:
                    log.warning(f"  Table for '{target_heading_text}' found on page {page_num}, but contains no data rows.")
                    continue

                log.info(f"  Processing {len(rows)-1} solutions from '{target_heading_text}' table...")
                for row_index, row in enumerate(rows[1:], start=1): # Skip header row
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        try:
                            solution_cell = cells[0]
                            solution_link_tag = solution_cell.find('a', href=True)

                            if not solution_link_tag:
                                log.warning(f"  Skipping row {row_index} - No link found in first cell: {solution_cell.get_text(strip=True)}")
                                continue

                            solution_name = solution_link_tag.get_text(strip=True)
                            relative_detail_url = solution_link_tag['href']
                            absolute_detail_url = urljoin(BASE_URL, relative_detail_url)

                            if absolute_detail_url in processed_detail_urls:
                                log.info(f"  Skipping already processed solution: {solution_name} ({absolute_detail_url})")
                                continue

                            remote_testing_cell = cells[1]
                            adaptive_irt_cell = cells[2]
                            test_type_cell = cells[3]

                            remote_testing = "Yes" if remote_testing_cell.find('span', class_='catalogue__circle') else "No"
                            adaptive_irt = "Yes" if adaptive_irt_cell.find('span', class_='catalogue__circle') else "No"

                            key_spans = test_type_cell.find_all('span', class_='product-catalogue__key')
                            test_type_codes = ' '.join(span.get_text(strip=True) for span in key_spans)

                            log.info(f"  Found Individual Solution: {solution_name}")
                            log.debug(f"    Detail URL: {absolute_detail_url}")
                            log.debug(f"    Remote: {remote_testing}, Adaptive: {adaptive_irt}, Types: '{test_type_codes}'")

                            solution_data = {
                                'Solution Name': solution_name,
                                'Detail URL': absolute_detail_url,
                                'Remote Testing': remote_testing,
                                'Adaptive/IRT': adaptive_irt,
                                'Test Type Codes': test_type_codes,
                                'PDF Links': [],
                                'Downloaded PDF Paths': []
                            }
                            all_solutions_data.append(solution_data)
                            processed_detail_urls.add(absolute_detail_url)

                        except Exception as e:
                            log.error(f"  Error processing row {row_index} in '{target_heading_text}' table on page {page_num}: {e}", exc_info=True)
                            continue
                    else:
                         log.warning(f"  Skipping row {row_index} in '{target_heading_text}' table on page {page_num} due to unexpected cell count: {len(cells)}. Row content: {row.get_text(strip=True)}")

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


        log.info(f"\n--- Finished scraping catalog pages. Found {len(all_solutions_data)} unique '{target_heading_text}'. ---")

        # --- Step 2: Scrape Detail Pages and Download PDFs ---
        log.info("\n--- Starting Detail Page Scraping and PDF Downloads ---")
        final_data_for_csv = []

        for i, solution in enumerate(all_solutions_data):
             log.info(f"\nProcessing detail page {i+1}/{len(all_solutions_data)} for: {solution['Solution Name']}")
             detail_url = solution['Detail URL']
             pdf_urls_on_page = scrape_detail_page(detail_url, session)
             solution['PDF Links'] = pdf_urls_on_page

             downloaded_pdf_paths = []
             if pdf_urls_on_page:
                 log.info(f" Found {len(pdf_urls_on_page)} unique PDF links. Attempting downloads...")
                 for pdf_url in pdf_urls_on_page:
                     local_path = download_pdf(pdf_url, pdf_folder, session)
                     if local_path:
                         downloaded_pdf_paths.append(os.path.abspath(local_path))
             else:
                 log.info(" No PDFs found or downloadable for this solution.")

             final_data_for_csv.append({
                 'Solution Name': solution['Solution Name'],
                 'Remote Testing': solution['Remote Testing'],
                 'Adaptive/IRT': solution['Adaptive/IRT'],
                 'Test Type': solution['Test Type Codes'],
                 'PDF Paths': "; ".join(downloaded_pdf_paths) if downloaded_pdf_paths else "N/A"
             })

    # --- Step 3: Write data to CSV ---
    if final_data_for_csv:
        log.info(f"\nWriting {len(final_data_for_csv)} records to {csv_filename}...")
        headers = ['Solution Name', 'Remote Testing', 'Adaptive/IRT', 'Test Type', 'PDF Paths']
        try:
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(final_data_for_csv)
            log.info(f"Scraping complete. Data saved to {csv_filename}")
            log.info(f"Downloaded PDFs are in the '{os.path.abspath(pdf_folder)}' directory.")
        except IOError as e:
            log.critical(f"CRITICAL ERROR writing to CSV file {csv_filename}: {e}", exc_info=True)
        except Exception as e:
             log.critical(f"CRITICAL UNEXPECTED ERROR during CSV writing: {e}", exc_info=True)

    else:
        log.warning(f"\nNo data from '{target_heading_text}' was successfully scraped to write to CSV.")


# --- Run the Scraper ---
if __name__ == "__main__":
    scrape_shl_catalog_multi_page(
        CATALOG_START_URL,
        CATALOG_URL_TEMPLATE_WITH_PARAMS,
        ITEMS_PER_PAGE,
        MAX_PAGES,
        PDF_FOLDER,
        CSV_FILENAME,
        TARGET_TABLE_HEADING_TEXT
    )