#storing embeddings, once per machine

# -*- coding: utf-8 -*-
"""
Connects to PostgreSQL, creates table (if needed), generates embeddings
for document chunks using a fine-tuned Sentence Transformer, and stores them
in the database with the pgvector extension.
"""

import torch
from sentence_transformers import SentenceTransformer
from pathlib import Path
import logging
import time
import json
import os
# Remove direct load_dotenv from here, rely on config.py
# from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_batch # For efficient batch insertion
from pgvector.psycopg2 import register_vector # Import pgvector adapter
import numpy as np # Needed by pgvector adapter
from src import config # Import the central config module

# --- Configuration ---
# REMOVED: load_dotenv() - Handled by config.py

# Model Configuration
MODEL_PATH = config.MODEL_PATH # Use path from config
EMBEDDING_DIMENSION = config.EMBEDDING_DIMENSION # Use dimension from config

# Data Configuration
CORPUS_FILE = config.CORPUS_FILE # Use corpus file path from config

# Database Configuration (Fetched from config module)
DB_NAME = config.DB_NAME
DB_USER = config.DB_USER
DB_PASSWORD = config.DB_PASSWORD
DB_HOST = config.DB_HOST
DB_PORT = config.DB_PORT
print(f"DEBUG: Using DB_PASSWORD from config: '{DB_PASSWORD}' (Type: {type(DB_PASSWORD)})") # Adjusted debug print

# Embedding/Processing Configuration
BATCH_SIZE = 64 # Process N chunks at a time for encoding and DB insertion
DEVICE_PREFERENCE = config.DEVICE_PREFERENCE # Use device preference from config

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Helper Function to Load Corpus ---
def load_corpus_data(corpus_file: Path) -> list[dict]:
    """Loads data from the JSON Lines corpus file."""
    data = []
    log.info(f"Loading corpus from {corpus_file}...")
    try:
        with corpus_file.open('r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                try:
                    item = json.loads(line)
                    # Ensure essential keys exist
                    if 'chunk_text' in item and item['chunk_text'].strip():
                         # Assign a default chunk_id if missing, ensuring uniqueness might require more robust logic
                         # Using metadata['solution_name'] + index or similar might be better if IDs aren't reliable
                         default_id = f"item_{i}"
                         item['chunk_id'] = item.get('metadata', {}).get('chunk_id', default_id)
                         # Ensure metadata exists
                         item['metadata'] = item.get('metadata', {})
                         data.append(item)
                    else:
                         log.warning(f"Skipping line {i+1}: Missing or empty 'chunk_text'.")
                except json.JSONDecodeError:
                    log.warning(f"Skipping invalid JSON on line {i+1}: {line.strip()}")
        log.info(f"Loaded {len(data)} valid items from corpus.")
        return data
    except FileNotFoundError:
        log.error(f"Corpus file not found: {corpus_file}")
        return []
    except Exception as e:
        log.error(f"Error loading corpus: {e}", exc_info=True)
        return []

# --- Helper Function to Create Table ---
def create_table_if_not_exists(cursor, dimension: int):
    """Creates the embeddings table if it doesn't exist."""
    log.info("Checking if 'shl_embeddings' table exists and creating if not...")
    try:
        # Use f-string for dimension - generally safe for integer dimensions
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS shl_embeddings (
            id SERIAL PRIMARY KEY,
            chunk_id TEXT UNIQUE NOT NULL,
            chunk_text TEXT,
            metadata JSONB,
            embedding vector({dimension})
        );
        COMMENT ON COLUMN shl_embeddings.chunk_id IS 'Unique identifier linking back to the source document chunk.';
        COMMENT ON COLUMN shl_embeddings.metadata IS 'Metadata associated with the chunk (e.g., solution name, source type).';
        COMMENT ON COLUMN shl_embeddings.embedding IS '{dimension}-dimensional vector embedding from fine-tuned model.';
        """
        cursor.execute(create_table_query)
        # No commit needed here if autocommit is True
        log.info("Table 'shl_embeddings' checked/created successfully.")
    except psycopg2.Error as e:
        log.error(f"Error creating table: {e}")
        raise # Re-raise the error to be caught by the main loop

# --- Main Function ---
def embed_and_store():
    """Main function to generate and store embeddings."""

    # --- Check DB Credentials ---
    # Check if essential variables are None (meaning not set in environment/dotenv)
    # Allow empty string for password
    if DB_NAME is None or DB_USER is None or DB_PASSWORD is None:
        missing_vars = [var for var, val in [('DB_NAME', DB_NAME), ('DB_USER', DB_USER), ('DB_PASSWORD', DB_PASSWORD)] if val is None]
        log.error(f"CRITICAL: Missing database credentials in environment variables: {', '.join(missing_vars)}. Please set them in the .env file.")
        return

    # --- Determine Device ---
    if DEVICE_PREFERENCE == "cuda" and torch.cuda.is_available():
        device = torch.device("cuda")
    elif DEVICE_PREFERENCE == "mps" and torch.backends.mps.is_available() and torch.backends.mps.is_built():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
        if DEVICE_PREFERENCE in ["cuda", "mps"]:
            log.warning(f"{DEVICE_PREFERENCE} selected but not available. Falling back to CPU.")
    log.info(f"Using device: {device.type}")

    # --- Load Model ---
    if not MODEL_PATH.exists():
        log.error(f"Model directory not found at '{MODEL_PATH}'. Please ensure it exists.")
        return
    log.info(f"Loading fine-tuned model from: {MODEL_PATH}")
    try:
        model = SentenceTransformer(str(MODEL_PATH), device=device.type)
        log.info(f"Model '{MODEL_PATH.name}' loaded successfully onto {model.device}.")
        # Verify model dimension matches config
        if model.get_sentence_embedding_dimension() != EMBEDDING_DIMENSION:
            log.error(f"Model dimension mismatch! Model reports {model.get_sentence_embedding_dimension()} but config is {EMBEDDING_DIMENSION}.")
            return
    except Exception as e:
        log.error(f"Failed to load model: {e}", exc_info=True)
        return

    # --- Load Corpus Data ---
    corpus_data = load_corpus_data(CORPUS_FILE)
    if not corpus_data:
        log.error("No corpus data loaded. Exiting.")
        return

    # --- Database Connection and Operations ---
    conn = None
    cur = None
    try:
        # Explicitly use variables from the imported config module here
        log.info(f"Connecting to PostgreSQL database '{config.DB_NAME}' on {config.DB_HOST}:{config.DB_PORT}...")
        conn = psycopg2.connect(
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            host=config.DB_HOST,
            port=config.DB_PORT
        )
        conn.autocommit = True # Explicitly set autocommit mode
        cur = conn.cursor()
        log.info("Database connection successful.")

        # *** Crucial: Register the pgvector adapter ***
        # Needs to be registered *after* connection is established
        register_vector(conn)
        log.info("pgvector adapter registered with psycopg2 connection.")

        # --- Create Table If Needed ---
        create_table_if_not_exists(cur, EMBEDDING_DIMENSION)

        # --- Prepare for Batch Insertion ---
        # Upsert: Insert or update if chunk_id already exists
        insert_query = """
            INSERT INTO shl_embeddings (chunk_id, chunk_text, metadata, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO UPDATE SET
                chunk_text = EXCLUDED.chunk_text,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding;
        """
        total_processed = 0
        start_time_embedding = time.time()

        # --- Iterate, Encode, and Insert Batches ---
        log.info(f"Starting embedding generation and storage (Batch Size: {BATCH_SIZE})...")
        data_to_insert_batch = []
        for i in range(0, len(corpus_data), BATCH_SIZE):
            batch_items = corpus_data[i : i + BATCH_SIZE]
            batch_texts = [item['chunk_text'] for item in batch_items]

            if not batch_texts: continue # Skip empty batches if any

            # Generate embeddings for the batch
            batch_embeddings_np = model.encode(
                batch_texts,
                convert_to_numpy=True,
                show_progress_bar=False,
                device=device.type
            )

            # Prepare data tuples for current batch insertion
            current_batch_data = []
            for item, embedding_np in zip(batch_items, batch_embeddings_np):
                metadata_json = json.dumps(item.get('metadata', {}))
                current_batch_data.append((
                    item['chunk_id'],
                    item['chunk_text'],
                    metadata_json,
                    embedding_np # Pass the numpy array directly
                ))

            # Insert the current batch
            if current_batch_data:
                execute_batch(cur, insert_query, current_batch_data, page_size=len(current_batch_data))
                # No explicit commit needed here because autocommit is True
                total_processed += len(current_batch_data)
                log.info(f"Processed and inserted batch {i//BATCH_SIZE + 1}. Total items: {total_processed}/{len(corpus_data)}")

        end_time_embedding = time.time()
        log.info(f"Successfully processed and stored {total_processed} embeddings in {end_time_embedding - start_time_embedding:.2f} seconds.")

        # --- Optional: Create Index After Insertion (if not already done) ---
        log.info("Optionally creating HNSW index on embeddings (if it doesn't exist)...")
        index_query = f"""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS shl_embeddings_hnsw_idx
        ON shl_embeddings
        USING hnsw (embedding vector_cosine_ops);
        """
        try:
             # Setting maintenance_work_mem might require superuser privileges
             # and might not be necessary if default is sufficient.
             # Consider removing if it causes issues or isn't needed.
             # cur.execute("SET maintenance_work_mem = '2GB';") # Optional
             cur.execute(index_query)
             # No explicit commit needed here because autocommit is True
             log.info("HNSW index checked/created successfully.")
        except psycopg2.Error as e:
             # No explicit rollback needed because autocommit is True
             if "already exists" in str(e):
                 log.info("Index 'shl_embeddings_hnsw_idx' already exists.")
             # This error shouldn't happen now with autocommit=True
             elif "cannot run inside a transaction block" in str(e):
                 log.warning(f"Index creation failed unexpectedly: {e}. Autocommit might not be working as expected.")
             else:
                 log.warning(f"Could not create index (it might exist or another error occurred): {e}")


    except psycopg2.OperationalError as e:
        log.error(f"Database connection failed: {e}")
        log.error("Check DB server status and credentials in .env (DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT)")
    except psycopg2.Error as e:
        log.error(f"Database error during processing: {e}")
        # No explicit rollback needed because autocommit is True
    except Exception as e:
        log.error(f"An unexpected error occurred during embedding/storage: {e}", exc_info=True)
        # No explicit rollback needed because autocommit is True
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
            log.info("Database connection closed.")

# --- Run the Script ---
if __name__ == "__main__":
    log.info("Starting script to generate and store embeddings...")
    embed_and_store()
    log.info("Script finished.")
