import pandas as pd
import os
import logging

# --- Configuration ---
FILE1_BASIC_DATA = "shl_individual_solutions_data.csv"
FILE2_LINKS = "shl_individual_solutions_links.csv"
FILE3_DETAILS = "shl_solution_additional_details_v2.csv"
OUTPUT_MERGED_FILE = "shl_solutions_merged_final.csv"
KEY_COLUMN = "Solution Name" # The column to join on

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Main Merging Logic ---
def merge_solution_csvs(file1, file2, file3, output_file, key_col):
    """Merges three CSV files based on a common key column."""
    log.info("Starting CSV merge process...")

    # Check if input files exist
    if not os.path.exists(file1):
        log.critical(f"CRITICAL ERROR: Input file not found: {file1}")
        return
    if not os.path.exists(file2):
        log.critical(f"CRITICAL ERROR: Input file not found: {file2}")
        return
    if not os.path.exists(file3):
        log.critical(f"CRITICAL ERROR: Input file not found: {file3}")
        return

    try:
        # Read CSVs into pandas DataFrames
        log.info(f"Reading {file1}...")
        df_basic = pd.read_csv(file1)
        log.info(f"Read {len(df_basic)} rows from {file1}. Columns: {list(df_basic.columns)}")
        if key_col not in df_basic.columns:
            log.critical(f"Key column '{key_col}' not found in {file1}")
            return

        log.info(f"Reading {file2}...")
        df_links = pd.read_csv(file2)
        log.info(f"Read {len(df_links)} rows from {file2}. Columns: {list(df_links.columns)}")
        if key_col not in df_links.columns:
            log.critical(f"Key column '{key_col}' not found in {file2}")
            return
        # Keep only key and Detail URL if other columns exist
        if 'Detail URL' in df_links.columns:
             df_links = df_links[[key_col, 'Detail URL']]
        else:
             log.critical(f"'Detail URL' column not found in {file2}")
             return


        log.info(f"Reading {file3}...")
        df_details = pd.read_csv(file3)
        log.info(f"Read {len(df_details)} rows from {file3}. Columns: {list(df_details.columns)}")
        if key_col not in df_details.columns:
            log.critical(f"Key column '{key_col}' not found in {file3}")
            return


        # --- Perform Merges ---
        # Merge basic data with links
        log.info(f"Merging '{file1}' and '{file2}' on '{key_col}'...")
        # Using 'outer' merge initially to see if any rows don't match across files
        merged_df_1 = pd.merge(df_basic, df_links, on=key_col, how='outer', indicator=True)

        # Check merge results (optional but helpful)
        merge_counts = merged_df_1['_merge'].value_counts()
        log.info(f"Merge 1 results: {merge_counts}")
        if 'left_only' in merge_counts or 'right_only' in merge_counts:
            log.warning(f"Found solutions present in only one of the first two files. Check data consistency.")
            # You might want to inspect merged_df_1[merged_df_1['_merge'] != 'both'] here

        merged_df_1 = merged_df_1.drop(columns=['_merge']) # Remove the indicator column


        # Merge the result with details
        log.info(f"Merging intermediate result with '{file3}' on '{key_col}'...")
        df_merged_final = pd.merge(merged_df_1, df_details, on=key_col, how='outer', indicator=True)

        # Check final merge results
        final_merge_counts = df_merged_final['_merge'].value_counts()
        log.info(f"Merge 2 results: {final_merge_counts}")
        if 'left_only' in final_merge_counts or 'right_only' in final_merge_counts:
             log.warning(f"Found solutions present in only the first two files or only the details file. Check data consistency.")

        df_merged_final = df_merged_final.drop(columns=['_merge']) # Remove indicator


        # Handle potential NaN values introduced by outer merge (replace with 'N/A')
        df_merged_final.fillna('N/A', inplace=True)

        # --- Define final column order ---
        final_columns = [
            'Solution Name',
            'Description',
            'Job Levels',
            'Languages',
            'Assessment Length',
            'Remote Testing',
            'Adaptive/IRT',
            'Test Type',
            'Detail URL',
            'PDF Paths'
        ]
        # Filter out any columns that might not exist if a merge failed partially (though outer should prevent this)
        existing_final_columns = [col for col in final_columns if col in df_merged_final.columns]

        # Reindex DataFrame with the desired column order
        df_output = df_merged_final[existing_final_columns]

        # --- Write the final merged CSV ---
        log.info(f"Writing {len(df_output)} rows to {output_file}...")
        df_output.to_csv(output_file, index=False, encoding='utf-8')
        log.info(f"Successfully merged data to {output_file}")

    except FileNotFoundError as e:
        log.critical(f"CRITICAL ERROR: File not found during read: {e}")
    except KeyError as e:
         log.critical(f"CRITICAL ERROR: Column key error during merge (likely missing '{key_col}' or other expected column): {e}")
    except Exception as e:
        log.critical(f"CRITICAL ERROR during merge process: {e}", exc_info=True)


# --- Run the Merge ---
if __name__ == "__main__":
    merge_solution_csvs(
        FILE1_BASIC_DATA,
        FILE2_LINKS,
        FILE3_DETAILS,
        OUTPUT_MERGED_FILE,
        KEY_COLUMN
    )