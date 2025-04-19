# # -*- coding: utf-8 -*-
# import requests
# from bs4 import BeautifulSoup
# import csv
# import os
# from urllib.parse import urljoin, urlparse, unquote
# import time
# import re # For cleaning filenames and extracting data
# import logging

# # --- Configuration ---
# BASE_URL = "https://www.shl.com"
# CATALOG_START_URL = "https://www.shl.com/solutions/products/product-catalog/"
# # Corrected URL template based on observed site behavior (?start=...)
# ITEMS_PER_PAGE = 12 # Deduced from start=12 for page 2
# CATALOG_URL_TEMPLATE_WITH_PARAMS = "https://www.shl.com/solutions/products/product-catalog/?start={}&type=1&type=1"
# MAX_PAGES = 32 # As identified from the website's pagination
# CSV_FILENAME = "shl_individual_solutions_data_full.csv" # Updated filename
# PDF_FOLDER = "pdfs_individual"
# REQUEST_DELAY = 1 # Seconds between requests
# REQUEST_TIMEOUT = 30 # Seconds for requests to complete
# HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
# TARGET_TABLE_HEADING_TEXT = "Individual Test Solutions" # Text to identify the correct table section

# # --- Setup Logging ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# log = logging.getLogger(__name__)

# # --- Helper Function to Sanitize Filenames ---
# # (sanitize_filename function remains the same as before)
# def sanitize_filename(filename):
#     """Removes invalid characters and shortens long filenames."""
#     sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
#     sanitized = sanitized.replace(' ', '_')
#     max_len = 150
#     if len(sanitized) > max_len:
#         name, ext = os.path.splitext(sanitized)
#         ext = ext[:10] if len(ext) > 10 else ext
#         name = name[:max_len - len(ext) -1]
#         sanitized = name + ext
#     sanitized = sanitized.strip('._ ')
#     if not sanitized:
#         sanitized = f"sanitized_file_{int(time.time())}"
#     return sanitized

# # --- Helper Function to Download PDF ---
# # (download_pdf function remains the same as before)
# def download_pdf(pdf_url, folder, session):
#     """Downloads a PDF from a URL into the specified folder using a session."""
#     pdf_filename = None
#     local_filepath = None
#     try:
#         log.info(f"  Attempting to download PDF: {pdf_url}")
#         time.sleep(REQUEST_DELAY)
#         response = session.get(pdf_url, stream=True, timeout=60, headers=HEADERS, allow_redirects=True)
#         response.raise_for_status()
#         content_disposition = response.headers.get('content-disposition')
#         if content_disposition:
#             filenames = re.findall(r'filename\*=(?:UTF-8\'\')?([^;]+)|filename="([^"]+)"', content_disposition, flags=re.IGNORECASE)
#             if filenames:
#                 utf8_filename, quoted_filename = filenames[0]
#                 raw_filename = utf8_filename if utf8_filename else quoted_filename
#                 if raw_filename:
#                     raw_filename = raw_filename.strip().strip('"')
#                     try:
#                         pdf_filename = unquote(raw_filename, encoding='utf-8', errors='strict')
#                     except UnicodeDecodeError:
#                         log.warning(f"    UTF-8 decode failed for filename '{raw_filename}', trying latin-1.")
#                         try:
#                             pdf_filename = unquote(raw_filename, encoding='latin-1')
#                         except Exception as decode_err:
#                              log.error(f"    Could not decode filename '{raw_filename}' with latin-1: {decode_err}")
#                              pdf_filename = None
#         if not pdf_filename:
#             parsed_url = urlparse(pdf_url)
#             path_part = unquote(parsed_url.path)
#             if path_part and path_part != '/':
#                 pdf_filename = os.path.basename(path_part)
#             if not pdf_filename or '.' not in pdf_filename :
#                  pdf_filename = f"downloaded_pdf_{int(time.time())}.pdf"
#                  log.warning(f"    Could not derive filename from header or URL path for {pdf_url}. Using generic name: {pdf_filename}")
#         filename_base = pdf_filename.split('?')[0].split('#')[0]
#         if not filename_base.lower().endswith('.pdf'):
#              pdf_filename = filename_base + ".pdf"
#         else:
#              pdf_filename = filename_base
#         pdf_filename = sanitize_filename(pdf_filename)
#         local_filepath = os.path.join(folder, pdf_filename)
#         log.info(f"  Saving PDF as: {local_filepath}")
#         with open(local_filepath, 'wb') as f:
#             for chunk in response.iter_content(chunk_size=8192):
#                 f.write(chunk)
#         log.info(f"  Successfully downloaded {pdf_filename}")
#         return local_filepath
#     except requests.exceptions.Timeout:
#         log.error(f"  Error: Timeout downloading {pdf_url}")
#     except requests.exceptions.SSLError as ssl_err:
#         log.error(f"  Error: SSL error downloading {pdf_url}: {ssl_err}")
#     except requests.exceptions.RequestException as e:
#         log.error(f"  Error downloading {pdf_url}: {e}")
#         if hasattr(e, 'response') and e.response is not None:
#             log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
#     except OSError as e:
#         log.error(f"  OS Error saving PDF {pdf_filename} (check permissions/path validity): {e}")
#     except Exception as e:
#         log.error(f"  An unexpected error occurred during download of {pdf_url}: {e}", exc_info=True)
#     return None

# # --- Function to Scrape a Single Detail Page for Text and PDFs ---
# def scrape_detail_page(detail_url, session):
#     """Scrapes specified details and PDF links from a single product detail page."""
#     details = {
#         'Description': 'N/A',
#         'Job Levels': 'N/A',
#         'Languages': 'N/A',
#         'Assessment Length': 'N/A',
#         'PDF Links': []
#     }
#     try:
#         log.info(f" Visiting detail page: {detail_url}")
#         time.sleep(REQUEST_DELAY)
#         response = session.get(detail_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
#         response.raise_for_status()
#         soup = BeautifulSoup(response.content, 'html.parser')

#         # --- Extract Description ---
#         # Strategy: Look for the first paragraph after the main h1 title
#         h1_tag = soup.find('h1')
#         if h1_tag:
#             first_p_after_h1 = h1_tag.find_next('p')
#             if first_p_after_h1 and first_p_after_h1.get_text(strip=True):
#                 details['Description'] = first_p_after_h1.get_text(strip=True)
#                 log.info(f"   Found Description: '{details['Description'][:50]}...'") # Log snippet
#         if details['Description'] == 'N/A':
#              log.warning("   Could not find Description using h1+p strategy.")

#         # --- Extract Job Levels, Languages, Assessment Length ---
#         # Strategy: Find specific labels (often in <strong> or similar) and get the text of the *next sibling*
#         labels_to_find = {
#             "Job level(s)": "Job Levels",
#             "Language(s)": "Languages",
#             "Approximate Completion Time in minutes": "Assessment Length",
#             "Completion Time": "Assessment Length", # Alternative label
#             "Assessment length": "Assessment Length" # Alternative label
#         }

#         # Search within a common content area first if possible
#         content_area = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup.find('body') or soup

#         for label_text, detail_key in labels_to_find.items():
#             # Find label using case-insensitive regex search within likely tags
#             label_tag = content_area.find(['strong', 'b', 'p', 'div', 'dt'],
#                                          string=re.compile(r'\s*' + re.escape(label_text) + r'\s*:?\s*', re.IGNORECASE))

#             if label_tag:
#                 # Find the immediate next sibling text or element content
#                 next_content = None
#                 next_sibling = label_tag.find_next_sibling()
#                 if next_sibling:
#                     next_content = next_sibling.get_text(strip=True)
#                 # Sometimes the value is inside the *same* tag as the label (e.g., <p><strong>Label:</strong> Value</p>)
#                 # or the parent tag contains the value after the label tag
#                 elif label_tag.parent and label_tag.next_sibling and isinstance(label_tag.next_sibling, str):
#                      next_content = label_tag.next_sibling.strip() # Get text node after the strong tag
#                 elif label_tag.parent:
#                      # Try getting all text from parent, remove label text
#                      parent_text = label_tag.parent.get_text(separator=' ', strip=True)
#                      label_actual_text = label_tag.get_text(strip=True)
#                      potential_value = parent_text.replace(label_actual_text, '').strip(': ')
#                      if potential_value:
#                          next_content = potential_value


#                 if next_content:
#                     # Clean up common artifacts like trailing commas or periods
#                     cleaned_content = next_content.strip(',. ')
#                     details[detail_key] = cleaned_content
#                     log.info(f"   Found {detail_key}: '{cleaned_content}'")
#                     # Stop searching for other labels for the same detail key if found
#                     if detail_key == "Assessment Length":
#                          break # Found assessment length, stop looking for alternatives
#                 else:
#                     log.warning(f"   Found label '{label_text}' but couldn't extract value.")
#             # else:
#                 # log.debug(f"   Label '{label_text}' not found.") # Optional: reduce log noise

#         if details['Job Levels'] == 'N/A': log.warning("   Job Levels not found.")
#         if details['Languages'] == 'N/A': log.warning("   Languages not found.")
#         if details['Assessment Length'] == 'N/A': log.warning("   Assessment Length not found.")

#         # --- Extract PDF Links (Re-using previous logic) ---
#         # Find the "Downloads" section/header robustly
#         possible_headers = soup.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'p'],
#                                          string=lambda t: t and "download" in t.strip().lower())
#         download_section = None
#         if possible_headers:
#             log.debug(f"   Found {len(possible_headers)} potential 'Downloads' related elements.")
#             for header in possible_headers:
#                  current_element = header
#                  search_depth = 0
#                  found_container = False
#                  while current_element and search_depth < 5:
#                      sibling = current_element.find_next_sibling(['div', 'ul', 'p', 'section', 'article'])
#                      if sibling:
#                          pdf_anchor = sibling.find('a', href=lambda href: href and isinstance(href, str) and href.lower().endswith('.pdf'))
#                          if pdf_anchor:
#                              download_section = sibling
#                              log.debug(f"   Found likely download section after <{header.name}>: <{sibling.name}>")
#                              found_container = True
#                              break
#                          current_element = sibling
#                      else:
#                           if current_element.parent:
#                              current_element = current_element.parent
#                           else:
#                              break
#                      search_depth += 1
#                  if found_container:
#                      break
#             if not download_section:
#                  log.debug(f"   Could not find a specific container after 'Downloads' headers. Searching common content areas.")
#                  download_section = soup.find('main') or soup.find('article') or soup.find('div', id='content') or soup.find('div', class_='content') or soup.find('body') or soup

#         else:
#             log.warning(f"  'Downloads' section header not identified on {detail_url}. Searching entire page.")
#             download_section = soup

#         if download_section:
#              links = download_section.find_all('a', href=lambda href: href and isinstance(href, str) and href.lower().strip().endswith('.pdf'))
#              unique_links = set()
#              for link in links:
#                 href = link.get('href', '').strip()
#                 if href:
#                     absolute_pdf_url = urljoin(detail_url, href)
#                     if absolute_pdf_url.startswith('http'):
#                         if absolute_pdf_url not in unique_links:
#                             details['PDF Links'].append(absolute_pdf_url)
#                             unique_links.add(absolute_pdf_url)
#                             log.info(f"   Found PDF link: {absolute_pdf_url}")
#                     else:
#                         log.debug(f"    Skipping non-http link: {absolute_pdf_url}")

#         if not details['PDF Links']:
#              log.warning(f"  No PDF download links found on {detail_url}")

#     except requests.exceptions.Timeout:
#         log.error(f" Error: Timeout accessing detail page {detail_url}")
#     except requests.exceptions.RequestException as e:
#         log.error(f" Error accessing detail page {detail_url}: {e}")
#         if hasattr(e, 'response') and e.response is not None:
#             log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
#     except Exception as e:
#         log.error(f" Error parsing detail page {detail_url}: {e}", exc_info=True)

#     return details

# # --- Main Scraping Logic ---
# def scrape_shl_catalog_multi_page(start_url, url_template_with_params, items_per_page, max_pages, pdf_folder, csv_filename, target_heading_text):
#     """Scrapes SHL catalog, visits detail pages for more info, downloads PDFs."""
#     log.info(f"Starting SHL Catalog Scrape for '{target_heading_text}' including details...")
#     os.makedirs(pdf_folder, exist_ok=True)
#     all_solutions_data = []
#     processed_detail_urls = set()

#     with requests.Session() as session:
#         session.headers.update(HEADERS)

#         # --- Step 1: Scrape Main Catalog Pages for the target table ---
#         for page_num in range(1, max_pages + 1):
#             if page_num == 1:
#                 current_url = start_url
#             else:
#                 start_index = (page_num - 1) * items_per_page
#                 current_url = url_template_with_params.format(start_index)

#             log.info(f"\n--- Scraping Catalog Page {page_num}: {current_url} ---")
#             try:
#                 time.sleep(REQUEST_DELAY)
#                 response = session.get(current_url, timeout=REQUEST_TIMEOUT)
#                 # Save HTML for debugging table finding if needed
#                 # debug_filename = f"debug_page_{page_num}.html"
#                 # try:
#                 #     with open(debug_filename, "w", encoding="utf-8") as f_debug: f_debug.write(response.text)
#                 #     log.info(f"  Saved HTML of page {page_num} to {debug_filename}")
#                 # except Exception as save_err: log.error(f"  Could not save debug HTML for page {page_num}: {save_err}")

#                 response.raise_for_status()
#                 soup = BeautifulSoup(response.content, 'html.parser')

#                 # --- Find the SPECIFIC "Individual Test Solutions" table ---
#                 individual_solutions_table = None
#                 all_tables = soup.find_all('table')
#                 log.debug(f"  Found {len(all_tables)} table(s) on page {page_num}.")
#                 for table in all_tables:
#                     header_row = table.find('tr')
#                     if not header_row: continue
#                     title_header = header_row.find('th', class_='custom__table-heading__title')
#                     if title_header:
#                         header_text = title_header.get_text(strip=True)
#                         if re.search(r'\s*' + re.escape(target_heading_text) + r'\s*', header_text, re.IGNORECASE):
#                             individual_solutions_table = table
#                             log.info(f"  Found target table with heading '{header_text}' in its <th>.")
#                             break
#                 # -----------------------------------------------------------

#                 if not individual_solutions_table:
#                     log.error(f"  ERROR: Could not find the table associated with '{target_heading_text}' on page {page_num} ({current_url}). Skipping page.")
#                     continue
#                 else:
#                     log.info(f"  Successfully identified table for '{target_heading_text}'.")

#                 # --- Process Rows ---
#                 rows = individual_solutions_table.find_all('tr')[1:]
#                 if not rows:
#                     log.warning(f"  Table found on page {page_num}, but no data rows.")
#                     continue

#                 log.info(f"  Processing {len(rows)} solutions from table...")
#                 for row_index, row in enumerate(rows, start=1):
#                     cells = row.find_all('td')
#                     if len(cells) < 4: # Need at least 4 cells from main table
#                         log.warning(f"  Skipping row {row_index} due to insufficient cell count ({len(cells)} < 4).")
#                         continue

#                     try:
#                         solution_cell = cells[0]
#                         solution_link_tag = solution_cell.find('a', href=True)
#                         if not solution_link_tag:
#                             log.warning(f"  Skipping row {row_index} - No link in first cell.")
#                             continue

#                         solution_name = solution_link_tag.get_text(strip=True)
#                         relative_detail_url = solution_link_tag['href']
#                         absolute_detail_url = urljoin(BASE_URL, relative_detail_url)

#                         if absolute_detail_url in processed_detail_urls:
#                             log.info(f"  Skipping already processed solution: {solution_name}")
#                             continue

#                         # Extract base data from catalog row
#                         remote_testing = "Yes" if cells[1].find('span', class_='catalogue__circle') else "No"
#                         adaptive_irt = "Yes" if cells[2].find('span', class_='catalogue__circle') else "No"
#                         key_spans = cells[3].find_all('span', class_='product-catalogue__key')
#                         test_type_codes = ' '.join(span.get_text(strip=True) for span in key_spans)

#                         log.info(f"  Found Basic Info: {solution_name}")
#                         log.debug(f"    Detail URL: {absolute_detail_url}")
#                         log.debug(f"    Remote: {remote_testing}, Adaptive: {adaptive_irt}, Types: '{test_type_codes}'")

#                         # --- Scrape Detail Page for More Info ---
#                         page_details = scrape_detail_page(absolute_detail_url, session)
#                         # ---------------------------------------

#                         # --- Download PDFs ---
#                         downloaded_pdf_paths = []
#                         if page_details.get('PDF Links'):
#                             log.info(f" Found {len(page_details['PDF Links'])} PDF links. Attempting downloads...")
#                             for pdf_url in page_details['PDF Links']:
#                                 local_path = download_pdf(pdf_url, pdf_folder, session)
#                                 if local_path:
#                                     downloaded_pdf_paths.append(os.path.abspath(local_path))
#                         # --------------------

#                         # Combine all data
#                         solution_data = {
#                             'Solution Name': solution_name,
#                             'Remote Testing': remote_testing,
#                             'Adaptive/IRT': adaptive_irt,
#                             'Test Type': test_type_codes, # Renamed key for consistency
#                             'Description': page_details.get('Description', 'N/A'),
#                             'Job Levels': page_details.get('Job Levels', 'N/A'),
#                             'Languages': page_details.get('Languages', 'N/A'),
#                             'Assessment Length': page_details.get('Assessment Length', 'N/A'),
#                             'PDF Paths': "; ".join(downloaded_pdf_paths) if downloaded_pdf_paths else "N/A",
#                             # Optional: Keep detail URL if needed for verification
#                             # 'Detail URL': absolute_detail_url,
#                         }
#                         all_solutions_data.append(solution_data)
#                         processed_detail_urls.add(absolute_detail_url)

#                     except Exception as e:
#                         log.error(f"  Error processing row {row_index} on page {page_num}: {e}", exc_info=True)
#                         continue

#             except requests.exceptions.Timeout:
#                 log.error(f" Error: Timeout fetching catalog page {page_num} ({current_url})")
#                 continue
#             except requests.exceptions.RequestException as e:
#                 log.error(f" Error fetching catalog page {page_num} ({current_url}): {e}")
#                 if hasattr(e, 'response') and e.response is not None:
#                     log.error(f"    Response Status: {e.response.status_code}, Reason: {e.response.reason}")
#                 continue
#             except Exception as e:
#                 log.error(f" Error parsing catalog page {page_num} ({current_url}): {e}", exc_info=True)
#                 continue

#         log.info(f"\n--- Finished scraping catalog pages. Found {len(all_solutions_data)} total solutions for '{target_heading_text}'. ---")


#     # --- Step 3: Write data to CSV ---
#     if all_solutions_data:
#         log.info(f"\nWriting {len(all_solutions_data)} records to {csv_filename}...")
#         # Define headers exactly as requested
#         headers = [
#             'Solution Name', 'Remote Testing', 'Adaptive/IRT', 'Test Type',
#             'Description', 'Job Levels', 'Languages', 'Assessment Length', 'PDF Paths'
#         ]
#         try:
#             with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
#                 writer = csv.DictWriter(csvfile, fieldnames=headers)
#                 writer.writeheader()
#                 # Write data making sure all keys exist, defaulting to 'N/A' if necessary
#                 for row_data in all_solutions_data:
#                      writer.writerow({h: row_data.get(h, 'N/A') for h in headers})

#             log.info(f"Scraping complete. Data saved to {csv_filename}")
#             log.info(f"Downloaded PDFs are in the '{os.path.abspath(pdf_folder)}' directory.")
#         except IOError as e:
#             log.critical(f"CRITICAL ERROR writing to CSV file {csv_filename}: {e}", exc_info=True)
#         except Exception as e:
#              log.critical(f"CRITICAL UNEXPECTED ERROR during CSV writing: {e}", exc_info=True)

#     else:
#         log.warning(f"\nNo data from '{target_heading_text}' was successfully scraped to write to CSV.")


# # --- Run the Scraper ---
# if __name__ == "__main__":
#     scrape_shl_catalog_multi_page(
#         CATALOG_START_URL,
#         CATALOG_URL_TEMPLATE_WITH_PARAMS,
#         ITEMS_PER_PAGE,
#         MAX_PAGES,
#         PDF_FOLDER,
#         CSV_FILENAME, # Use the updated filename
#         TARGET_TABLE_HEADING_TEXT
#     )