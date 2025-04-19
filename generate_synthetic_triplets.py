# -*- coding: utf-8 -*-
import json
import random
import os
import logging
import time
import re
from dotenv import load_dotenv
import google.generativeai as genai # Use the specific import

# Load environment variables from .env file
load_dotenv()

# --- LLM Configuration ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
# *** Use the specified Gemini 1.5 Flash model ***
# Note: Changed LLM_MODEL_NAME back to 1.5-flash as 2.0-flash doesn't exist yet.
LLM_MODEL_NAME = 'gemini-2.0-flash'
LLM_PROVIDER = "gemini" # Keep for clarity if needed elsewhere

# --- Script Configuration ---
INPUT_JSONL = "processed_shl_chunks.jsonl" # Assumes 'languages' key in metadata
OUTPUT_JSONL = "finetuning_triplets_v2_english.jsonl" # New output name
NUM_QUERIES_PER_ASSESSMENT = 10
TARGET_TRIPLET_COUNT = 10000 # Adjust as needed
MAX_LLM_RETRIES = 3
LLM_RETRY_DELAY = 5 # seconds
TARGET_LANGUAGE = 'en' # Focus on English triplets

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- LLM Interaction Function ---
def call_llm(prompt):
    """Sends a prompt to the configured LLM and returns the text response."""
    log.debug(f"Sending prompt to LLM ({LLM_MODEL_NAME})...")
    if not GOOGLE_API_KEY:
        log.error("GOOGLE_API_KEY not configured.")
        return None

    retries = 0
    while retries < MAX_LLM_RETRIES:
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel(LLM_MODEL_NAME)
            # Configure safety settings to be less restrictive if appropriate,
            # but be aware of the implications. Test default first.
            # safety_settings = [
            #     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            #     {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            #     {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            #     {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            # ]
            # response = model.generate_content(prompt, safety_settings=safety_settings)
            response = model.generate_content(prompt) # Use default safety first

            # Enhanced check for valid response content
            if response.parts:
                # Accessing text safely
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0] # Assuming one candidate usually
                    if candidate.content and candidate.content.parts:
                         # Ensure part has text attribute
                         if hasattr(candidate.content.parts[0], 'text'):
                            response_text = candidate.content.parts[0].text
                            log.debug(f"LLM Response received (first 100 chars): {response_text[:100]}")
                            return response_text.strip()
                         else:
                            log.warning(f"LLM ({LLM_MODEL_NAME}) response part missing 'text' attribute.")
                            raise Exception("Part missing text") # Force retry
                    else:
                         log.warning(f"LLM ({LLM_MODEL_NAME}) response candidate has no content/parts. Prompt Feedback: {response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'}")
                         raise Exception("Empty candidate content") # Force retry
                else:
                    log.warning(f"LLM ({LLM_MODEL_NAME}) response has no candidates. Prompt Feedback: {response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'}")
                    raise Exception("No candidates in response") # Force retry

            else:
                # Check for blocks
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                    log.warning(f"LLM ({LLM_MODEL_NAME}) call blocked. Reason: {response.prompt_feedback.block_reason}. Prompt: {prompt[:100]}...")
                else:
                    log.warning(f"LLM ({LLM_MODEL_NAME}) returned no parts (unknown reason). Prompt Feedback: {response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'}. Prompt: {prompt[:100]}...")
                raise Exception("Blocked or empty response") # Force retry

        except Exception as e:
            retries += 1
            log.warning(f"LLM call failed (Attempt {retries}/{MAX_LLM_RETRIES}): {e}. Retrying in {LLM_RETRY_DELAY}s...")
            if retries >= MAX_LLM_RETRIES:
                log.error(f"LLM call failed after {MAX_LLM_RETRIES} attempts for prompt: {prompt[:100]}...")
                return None # Indicate failure
            time.sleep(LLM_RETRY_DELAY + random.uniform(0, 1)) # Add jitter
    return None


# --- Helper Functions ---

# ** CORRECTED load_processed_chunks **
# Checks metadata['languages'] (plural) and filters based on list content
def load_processed_chunks(jsonl_file, target_language='en'):
    """Loads chunk data, filtering by target language stored in the 'languages' list within metadata."""
    chunks = []
    log.info(f"Loading and filtering chunks for language '{target_language}' from {jsonl_file}...")
    lines_read = 0
    invalid_json = 0
    missing_lang_key = 0 # Count chunks missing the 'languages' key entirely
    empty_lang_list = 0  # Count chunks where 'languages' list is empty
    lang_mismatch = 0
    lang_match_count = 0
    try:
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                lines_read += 1
                try:
                    data = json.loads(line)
                    metadata = data.get('metadata', {})

                    # --- CORRECTED Language Filtering Logic ---
                    # 1. Get the list associated with the 'languages' (plural) key
                    langs_list = metadata.get('languages')

                    # 2. Check if the key exists and the list is not empty or None
                    if langs_list and isinstance(langs_list, list):
                        # 3. Check if any language string in the list indicates English
                        #    (case-insensitive check for 'english')
                        is_target_language = any(target_language in lang.lower() for lang in langs_list if isinstance(lang, str))

                        if is_target_language:
                            if data.get('chunk_text'): # Ensure text exists
                                chunks.append(data)
                                lang_match_count += 1
                            else:
                                log.debug(f"Skipping chunk with no text: {metadata.get('solution_name', 'N/A')}")
                        else:
                            # This chunk has a language list, but not the target language
                            lang_mismatch += 1
                            # Optional: Log the languages found if debugging mismatch
                            # log.debug(f"Language mismatch for {metadata.get('solution_name', 'N/A')}. Found: {langs_list}")

                    elif isinstance(langs_list, list) and not langs_list:
                        # 'languages' key exists but the list is empty
                        empty_lang_list += 1
                        log.debug(f"Chunk has empty 'languages' list: {metadata.get('solution_name', 'N/A')}. Skipping.")
                    else:
                        # 'languages' key is missing or not a list
                        missing_lang_key += 1
                        log.warning(f"Chunk missing 'languages' key or not a list: {metadata.get('solution_name', 'N/A')}. Skipping.")
                    # ------------------------------------------

                except json.JSONDecodeError:
                    log.warning(f"Skipping invalid JSON line in {jsonl_file}: {line.strip()}")
                    invalid_json += 1

        log.info(f"Read {lines_read} lines. Loaded {len(chunks)} chunks matching language '{target_language}'.")
        if missing_lang_key > 0: log.warning(f"Skipped {missing_lang_key} chunks missing 'languages' key or not a list.")
        if empty_lang_list > 0: log.warning(f"Skipped {empty_lang_list} chunks with an empty 'languages' list.")
        if lang_mismatch > 0: log.warning(f"Skipped {lang_mismatch} chunks with non-target language(s).")
        if invalid_json > 0: log.warning(f"Skipped {invalid_json} invalid JSON lines.")

        if not chunks:
            log.error(f"No chunks found for target language '{target_language}'. Check input file and preprocessing steps.")
            return None
        return chunks
    except FileNotFoundError:
        log.critical(f"CRITICAL: Input chunk file not found: {jsonl_file}")
        return None
    except Exception as e:
        log.critical(f"CRITICAL: Error loading chunk file {jsonl_file}: {e}", exc_info=True)
        return None

# ** CORRECTED get_core_info_chunk **
# Removed the incorrect internal check for singular 'language' key
def get_core_info_chunk(solution_name, all_english_chunks):
    """Finds the English core_info chunk for a specific solution."""
    for chunk in all_english_chunks:
        # Trust that all_english_chunks is already filtered
        if chunk['metadata']['solution_name'] == solution_name and \
           chunk['metadata']['source_type'] == 'core_info':
            return chunk
    # Log warning if not found (optional, can be verbose)
    # log.warning(f"Could not find English core_info chunk for solution: {solution_name}")
    return None

# ** CORRECTED get_pdf_chunks **
# Removed the incorrect internal check for singular 'language' key
def get_pdf_chunks(solution_name, all_english_chunks):
    """Finds all English PDF chunks for a specific solution."""
    # Trust that all_english_chunks is already filtered
    return [chunk for chunk in all_english_chunks
            if chunk['metadata']['solution_name'] == solution_name and
               chunk['metadata']['source_type'] != 'core_info']

# ** CORRECTED get_relevant_negative_chunk **
# Removed the incorrect internal check for singular 'language' key
# Added safe access for metadata keys
def get_relevant_negative_chunk(exclude_solution_name, positive_test_type, all_english_chunks):
    """
    Gets a random English chunk from a DIFFERENT solution.
    Tries to find one with the same 'Test Type' for harder negatives.
    Falls back to any other English chunk if same-type is not found.
    """
    potential_negatives = [
        chunk for chunk in all_english_chunks
        # Safely access solution name from metadata
        if chunk.get('metadata', {}).get('solution_name') != exclude_solution_name
        # Trust that all_english_chunks is already filtered for language
    ]

    if not potential_negatives:
        log.warning(f"No other English solutions found to select a negative for '{exclude_solution_name}'.")
        return None

    # Try for same Test Type negative (if positive_test_type is known and valid)
    # Ensure positive_test_type is a valid string before comparing
    if positive_test_type and isinstance(positive_test_type, str) and positive_test_type != 'N/A':
        same_type_negatives = [
            chunk for chunk in potential_negatives
            # Safely get 'Test Type' from negative chunk metadata
            if chunk.get('metadata', {}).get('Test Type') == positive_test_type
        ]
        if same_type_negatives:
            log.debug(f"Selecting negative with matching Test Type '{positive_test_type}' for excluded '{exclude_solution_name}'.")
            return random.choice(same_type_negatives)
        else:
            log.debug(f"No negatives with Test Type '{positive_test_type}' found for {exclude_solution_name}. Falling back to any other English solution.")

    # Fallback: choose any chunk from a different English solution
    # Add check to prevent error if potential_negatives is empty (shouldn't happen after initial check, but safe)
    if potential_negatives:
        return random.choice(potential_negatives)
    else:
        # This case should ideally not be reached due to the check at the start
        log.error(f"Potential negatives list became empty unexpectedly for '{exclude_solution_name}'.")
        return None


def parse_llm_query_response(response_text):
    """Parses numbered list of queries from LLM response."""
    if not response_text:
        return []
    queries = []
    # More robust regex to handle variations like "1.", "1)", "  1. " etc.
    # It captures the text after the number and separator.
    for line in response_text.splitlines():
        match = re.match(r'^\s*\d+\s*[.)]\s*(.*)', line)
        if match:
            query = match.group(1).strip()
            # Further cleanups: remove potential quotes if LLM wrapped queries
            query = query.strip('\'"')
            if query:
                 queries.append(query)
    # Fallback if no numbered items found but there's content
    if not queries and response_text.strip():
        log.warning("LLM response did not seem to be a numbered list. Treating each non-empty line as a query.")
        queries = [line.strip().strip('\'"') for line in response_text.splitlines() if line.strip()]
    return queries

def summarize_core_info(core_chunk_text, max_len=200):
     """Creates a concise summary string from the structured core_info chunk text."""
     summary_parts = []
     data = {}
     # Basic parsing - adjust regex/logic if format varies significantly
     lines = core_chunk_text.split('\n')
     for line in lines:
         if ':' in line:
            try:
                key, value = line.split(':', 1)
                data[key.strip()] = value.strip()
            except ValueError:
                 log.debug(f"Skipping line in core info summarization (no colon?): {line}")
                 continue # Skip lines without a colon

     # Build summary
     if data.get('Solution Name'):
         summary_parts.append(f"Assessment: {data['Solution Name']}.")
     # Try to get the first sentence/part of the description more reliably
     desc = data.get('Description', '')
     if desc:
         # Remove potential '\r' and take text before the first period if found
         first_sentence_match = re.match(r"^(.*?)(?:\.|\r|\n|$)", desc.replace('\r',''))
         if first_sentence_match:
             desc_part = first_sentence_match.group(1).strip()
             if desc_part: # Ensure it's not empty
                 summary_parts.append(f"Description: {desc_part[:max_len]}{'...' if len(desc_part) > max_len else '.'}")

     if data.get('Job Levels') and data['Job Levels'] != 'N/A':
          summary_parts.append(f"Levels: {data['Job Levels']}.")
     # Safely access 'Test Type' which might be a list in metadata, but string in chunk text
     test_type_val = data.get('Test Type')
     if test_type_val and test_type_val != 'N/A':
          summary_parts.append(f"Type: {str(test_type_val)}.") # Ensure it's string
     # Handle potential 'nan' or non-numeric Assessment Length
     length_val = data.get('Assessment Length (minutes)')
     if length_val:
        try:
            # Attempt to convert to float/int, ignore if fails or is NaN
            length_num = float(length_val)
            if not pd.isna(length_num): # Requires pandas import if using pd.isna
                 summary_parts.append(f"Duration: ~{int(length_num)} min.")
        except (ValueError, TypeError):
            # If conversion fails or it's not a number-like string, ignore safely
            pass

     summary = " ".join(summary_parts)
     # Fallback if no parts were added, use beginning of original text
     return summary if summary else core_chunk_text[:max_len]

# Optional: Add pandas import if using pd.isna in summarize_core_info
try:
    import pandas as pd
except ImportError:
    log.warning("Pandas not found. Summarization might not handle 'nan' duration robustly.")
    # Define a simple fallback isnan if pandas is not available
    def isnan(x):
        try:
            return x != x # Works for float('nan')
        except TypeError:
            return False
    pd = type('obj', (object,), {'isna': isnan})() # Mock pd.isna


# --- Main Data Generation Logic (V2) ---
def generate_triplets_v2(all_english_chunks, num_queries_per, target_count):
    """Generates query-based and core-to-pdf triplets focusing on English and better negatives."""
    if not all_english_chunks:
        log.error("No English chunks loaded, cannot generate triplets.")
        return []

    triplets = []
    # Get unique solution names ONLY from the filtered English chunks
    unique_solution_names = sorted(list(set(chunk['metadata']['solution_name'] for chunk in all_english_chunks)))
    log.info(f"Found {len(unique_solution_names)} unique solutions with English chunks.")
    if not unique_solution_names:
        log.error("No unique solutions identified from the English chunks.")
        return []

    # == 1. Generate Query-Based Triplets ==
    log.info("Generating synthetic queries using LLM for English solutions...")
    query_target_pairs = []
    generated_query_count = 0
    failed_query_gen = 0
    processed_solutions_for_queries = 0
    for i, solution_name in enumerate(unique_solution_names):
        # Find the English core_info chunk for this solution
        core_chunk = get_core_info_chunk(solution_name, all_english_chunks)

        if not core_chunk:
            # This log should now be less frequent if loading works
            log.debug(f"  Skipping query generation for {solution_name} (no English core chunk found).")
            continue

        processed_solutions_for_queries += 1
        log.info(f"  Generating queries for solution {processed_solutions_for_queries}/{len(unique_solution_names)}: {solution_name}")

        # Use the refined prompt - send the full core text to LLM for context
        prompt = f"""Act as a Hiring Manager looking for SHL assessments. Based ONLY on the following assessment information:
--- ASSESSMENT START ---
{core_chunk['chunk_text']}
--- ASSESSMENT END ---

Generate {num_queries_per} diverse, realistic English search queries focused *specifically* on the details mentioned above. Create queries that:
1. Ask about specific skills explicitly mentioned (e.g., "assessment for [skill]").
2. Target the described job levels (e.g., "entry-level [assessment type] test").
3. Inquire about the assessment length (e.g., "quick test under [duration] mins for [purpose]").
4. Mention the test type codes if present (e.g., "SHL test with type [code]").
5. Combine 2-3 of the above aspects (e.g., "managerial assessment for [skill] under [duration] minutes").
6. Reflect a hiring need related to the assessment's description (e.g., "test for identifying high-potential graduates").

Output ONLY the numbered list of queries in English. Do not add commentary. Ensure queries are distinct.

Generated Queries:"""

        response_text = call_llm(prompt)
        if response_text:
            generated_queries = parse_llm_query_response(response_text)
            log.info(f"    LLM generated {len(generated_queries)} queries.")
            generated_query_count += len(generated_queries)
            for query in generated_queries:
                # Store with the core chunk for later negative selection context
                query_target_pairs.append({"query": query, "solution_name": solution_name, "core_chunk": core_chunk})
        else:
            failed_query_gen += 1
            log.error(f"    Failed to generate queries for {solution_name} after retries.")
        # Optional small delay
        # time.sleep(0.5)

    log.info(f"Generated {len(query_target_pairs)} total synthetic query-solution pairs from {processed_solutions_for_queries} solutions.")
    if failed_query_gen > 0 : log.warning(f"Failed to generate queries for {failed_query_gen} solutions.")

    log.info("Creating (Query, Positive, Negative) triplets...")
    skipped_query_triplets = 0
    query_based_count = 0
    for item in query_target_pairs:
        query = item['query']
        target_solution = item['solution_name']
        anchor_core_chunk = item['core_chunk'] # Use the core chunk associated with the query

        # Select Positive (English Only) from the target solution
        pdf_chunks = get_pdf_chunks(target_solution, all_english_chunks)
        possible_positives = [anchor_core_chunk] + pdf_chunks # Core chunk is always a possibility

        if not possible_positives:
             log.warning(f"No English positive chunks found for '{target_solution}' for query '{query}'. Skipping triplet.")
             skipped_query_triplets += 1
             continue
        positive_chunk = random.choice(possible_positives) # Randomly pick core or PDF chunk

        # Select Negative (Relevant English Negative)
        # Use test type from the *positive* chunk chosen for this triplet
        positive_test_type = positive_chunk.get('metadata', {}).get('Test Type')
        negative_chunk = get_relevant_negative_chunk(target_solution, positive_test_type, all_english_chunks)

        if not negative_chunk:
            log.warning(f"Could not find suitable English negative chunk for query '{query}' (target: {target_solution}). Skipping triplet.")
            skipped_query_triplets += 1
            continue

        # Ensure all parts are strings before adding
        triplets.append([
            str(query),
            str(positive_chunk['chunk_text']),
            str(negative_chunk['chunk_text'])
        ])
        query_based_count += 1

    log.info(f"Generated {query_based_count} query-based triplets. Skipped {skipped_query_triplets} due to missing positive/negative.")

    # == 2. Generate Core-Info-Based Triplets (Anchor = Summarized Core) ==
    log.info("Creating (Summarized Core, Positive Chunk, Negative) triplets...")
    core_based_count = 0
    skipped_core_triplets = 0
    needed_core_based = max(0, target_count - len(triplets))
    if len(unique_solution_names) == 0:
        log.warning("No unique solutions found for core-based triplet generation.")
        target_per_solution = 0
    else:
        target_per_solution = (needed_core_based // len(unique_solution_names)) + 1
    log.info(f"Aiming for approx. {needed_core_based} more core-info-based triplets ({target_per_solution} per solution).")

    processed_solutions_for_core_triplets = 0
    # Shuffle solutions to vary the order triplets are added
    shuffled_solutions = random.sample(unique_solution_names, len(unique_solution_names))

    for solution_name in shuffled_solutions:
        if len(triplets) >= target_count:
             log.info("Target triplet count reached during core-based generation.")
             break

        core_chunk = get_core_info_chunk(solution_name, all_english_chunks)
        if not core_chunk: continue # Need core chunk

        processed_solutions_for_core_triplets += 1

        # Create the summarized anchor
        summarized_anchor = summarize_core_info(core_chunk['chunk_text'])
        if not summarized_anchor:
            log.warning(f"Could not summarize core info for {solution_name}. Skipping core-based triplets.")
            continue # Skip if summarization failed

        # Potential positives: core chunk itself + its PDF chunks
        pdf_chunks = get_pdf_chunks(solution_name, all_english_chunks)
        # Ensure core chunk itself is included as a potential positive
        possible_positives = [core_chunk] + pdf_chunks
        random.shuffle(possible_positives)

        added_for_solution = 0
        for positive_chunk in possible_positives:
            # Check overall target count inside the loop
            if len(triplets) >= target_count:
                 break
            # Check per-solution target count
            if added_for_solution >= target_per_solution and target_per_solution > 0:
                 break # Stop adding for this solution if target met

            # Select Negative (Relevant English Negative)
            positive_test_type = positive_chunk.get('metadata', {}).get('Test Type')
            negative_chunk = get_relevant_negative_chunk(solution_name, positive_test_type, all_english_chunks)

            if not negative_chunk:
                log.debug(f"Could not find negative for core-based triplet {solution_name}. Skipping.")
                skipped_core_triplets += 1
                continue # Skip this specific triplet

            # Ensure all parts are strings
            triplets.append([
                str(summarized_anchor),
                str(positive_chunk['chunk_text']),
                str(negative_chunk['chunk_text'])
            ])
            core_based_count += 1
            added_for_solution += 1

        # log.debug(f"  Added {added_for_solution} core-based triplets for {solution_name}")

    log.info(f"Processed {processed_solutions_for_core_triplets} solutions for core-based triplets.")
    log.info(f"Generated {core_based_count} core-info-based triplets. Skipped {skipped_core_triplets} due to missing negatives.")
    log.info(f"Total triplets generated: {len(triplets)}")

    # Shuffle the final list
    if triplets:
        log.info("Shuffling final triplet dataset...")
        random.shuffle(triplets)

    return triplets


# --- Save Triplets ---
def save_triplets(triplets, output_file):
    """Saves the list of triplets to a JSON Lines file."""
    log.info(f"Writing {len(triplets)} triplets to {output_file}...")
    lines_written = 0
    lines_skipped = 0
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for triplet in triplets:
                # Double-check that all elements are non-empty strings
                if len(triplet) == 3 and all(isinstance(item, str) and item for item in triplet):
                    try:
                        f.write(json.dumps(triplet) + '\n')
                        lines_written += 1
                    except TypeError as e:
                         log.warning(f"JSON serialization error for triplet: {triplet}. Error: {e}. Skipping.")
                         lines_skipped += 1
                else:
                    log.warning(f"Skipping invalid or empty triplet during save: {[str(t)[:50]+'...' for t in triplet]}")
                    lines_skipped += 1
        log.info(f"Successfully saved {lines_written} triplets to {output_file}.")
        if lines_skipped > 0:
            log.warning(f"Skipped {lines_skipped} invalid/empty triplets during saving.")
    except Exception as e:
        log.critical(f"CRITICAL ERROR saving triplets to {output_file}: {e}", exc_info=True)

# --- Run the Generation ---
if __name__ == "__main__":
    # Load and filter chunks first
    all_english_chunks = load_processed_chunks(INPUT_JSONL, TARGET_LANGUAGE)

    if all_english_chunks:
        # Generate triplets using the filtered chunks
        generated_triplets = generate_triplets_v2(
            all_english_chunks,
            NUM_QUERIES_PER_ASSESSMENT,
            TARGET_TRIPLET_COUNT
        )
        if generated_triplets:
            save_triplets(generated_triplets, OUTPUT_JSONL)
        else:
            log.error("Triplet generation failed or produced no triplets.")
    else:
        log.error(f"Could not load English chunks from {INPUT_JSONL}. Aborting triplet generation.")
        log.error("Ensure the input file exists and the preprocessing step added 'languages' metadata correctly.")