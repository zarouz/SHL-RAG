import torch
from sentence_transformers import SentenceTransformer
import psycopg2
import psycopg2.pool # Explicitly import the pool submodule
from psycopg2.extras import RealDictCursor # Return results as dictionaries
from pgvector.psycopg2 import register_vector
import logging
import time # Needed for sleep
import json
import os # Added for path operations
import zipfile # Added for unzipping
import tempfile # Added for temporary directory
import shutil # Added for cleanup
from pathlib import Path # Added for path manipulation
from typing import List, Dict, Optional, Tuple

# Import configuration variables
from . import config

# Attempt to import GCS library, handle optional import
try:
    from google.cloud import storage
    GCS_ENABLED = True
except ImportError:
    storage = None
    GCS_ENABLED = False
    logging.warning("google-cloud-storage library not found. GCS model loading disabled.")

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Global Variables ---
# Initialize model and device later in a function to handle potential errors
model = None
device = None
# Initialize model and device later in a function to handle potential errors
model = None
device = None
db_connection_pool = None # Using a pool for potentially concurrent requests in API

# --- Helper Function to Determine Device ---
def get_device():
    """Determines the best available device (cuda, mps, cpu)."""
    global device
    # Check only once
    if device:
        return device

    # Auto-detect best available device: CUDA > MPS > CPU
    if torch.cuda.is_available():
        device = torch.device("cuda")
        log.info("CUDA is available. Using CUDA device.")
    elif torch.backends.mps.is_available() and torch.backends.mps.is_built():
        device = torch.device("mps")
        log.info("CUDA not available, but MPS is. Using MPS device.")
    else:
        device = torch.device("cpu")
        log.info("CUDA and MPS not available. Falling back to CPU device.")

    log.info(f"Selected device: {device.type}")
    return device

# --- Helper Function to Load Model (Now loads directly from local path) ---
def load_embedding_model():
    """
    Loads the Sentence Transformer model directly from the local path
    specified in config.MODEL_PATH. Assumes the model files are deployed
    alongside the application code.
    """
    global model
    if model:
        log.info("Model already loaded.")
        return model

    model_load_path = config.MODEL_PATH

    log.info(f"Loading model from local filesystem path: {model_load_path}")
    if not model_load_path.exists():
        log.error(f"Local model directory not found at '{model_load_path}'. Cannot proceed.")
        # Log details about where it looked relative to the script
        log.error(f"Looked relative to config.py parent dir: {config.project_root}")
        log.error(f"Current working directory during load attempt: {os.getcwd()}")
        raise FileNotFoundError(f"Local model directory not found: {model_load_path}")

    # --- Load the SentenceTransformer model ---
    log.info(f"Loading SentenceTransformer model from: {model_load_path}")
    try:
        current_device = get_device()
        model = SentenceTransformer(str(model_load_path), device=current_device.type)
        log.info(f"Model loaded successfully onto {model.device} from {model_load_path}.")

        # Verify model dimension
        if model.get_sentence_embedding_dimension() != config.EMBEDDING_DIMENSION:
            log.error(f"Model dimension mismatch! Model reports {model.get_sentence_embedding_dimension()} but config expects {config.EMBEDDING_DIMENSION}.")
            raise ValueError("Model dimension mismatch")

        return model
    except Exception as e:
        log.error(f"Failed to load SentenceTransformer model from {model_load_path}: {e}", exc_info=True)
def init_connection_pool(max_retries=5, delay_seconds=2):
    """Initializes the PostgreSQL connection pool with retries, connecting via Unix socket."""
    global db_connection_pool
    if db_connection_pool:
        return db_connection_pool

    # --- Connect via Unix Socket for Cloud Run + Cloud SQL ---
    # The host is the directory containing the socket file.
    db_host_dir = f"/cloudsql/{config.CLOUD_SQL_INSTANCE_CONNECTION_NAME}"
    # Port is not used when connecting via Unix socket.

    # --- Read Password from Secret Manager Volume Mount ---
    secret_path = "/secrets/DB_PASSWORD" # Default path when mounting DB_PASSWORD secret
    try:
        with open(secret_path, 'r') as f:
            db_password = f.read().strip()
    except FileNotFoundError:
        log.error(f"Secret file not found at {secret_path}. Ensure the 'DB_PASSWORD' secret is mounted correctly in your Cloud Run service.")
        raise ValueError("DB_PASSWORD secret not found at expected path.")
    except Exception as e:
        log.error(f"Error reading secret file at {secret_path}: {e}", exc_info=True)
        raise

    # --- Validate Configuration ---
    if not all([config.DB_NAME, config.DB_USER, db_password, config.CLOUD_SQL_INSTANCE_CONNECTION_NAME]):
         log.error("Database configuration is incomplete (DB_NAME, DB_USER, DB_PASSWORD secret, CLOUD_SQL_INSTANCE_CONNECTION_NAME). Cannot initialize connection pool.")
         raise ValueError("Incomplete database configuration for Cloud Run.")

    log.info(f"Initializing connection pool for database '{config.DB_NAME}' via Unix socket at {db_host_dir}")

    for attempt in range(max_retries):
        log.info(f"Attempt {attempt + 1} of {max_retries} to initialize connection pool...")
        try:
            pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10, # Adjust max connections based on expected load
                dbname=config.DB_NAME,
                user=config.DB_USER,
                password=db_password,
                host=db_host_dir, # Use the socket directory path here
                # port is omitted when using Unix socket
                connect_timeout=5 # Add a connection timeout
            )
            # Test connection and register vector type
            conn = pool.getconn()
            register_vector(conn)
            pool.putconn(conn) # Put it back immediately after test

            log.info("Connection pool initialized and pgvector registered successfully.")
            db_connection_pool = pool # Assign to global pool only on success
            return db_connection_pool
        except psycopg2.OperationalError as e:
            log.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                log.info(f"Retrying in {delay_seconds} seconds...")
                time.sleep(delay_seconds)
            else:
                log.error("Max retries reached. Failed to initialize connection pool.")
                raise # Raise the final exception after all retries fail
        except Exception as e:
             log.error(f"Unexpected error during pool initialization attempt {attempt + 1}: {e}", exc_info=True)
             # Raise immediately on unexpected errors
             raise

    # Should not be reached if successful, but added for safety
    raise psycopg2.OperationalError("Failed to initialize connection pool after multiple retries.")

def get_db_connection():
    """Gets a connection from the pool."""
    global db_connection_pool # Use the pool again
    if not db_connection_pool:
        init_connection_pool() # Initialize if not already done
    try:
        conn = db_connection_pool.getconn()
        # Ensure vector is registered for this connection (might be redundant but safe)
        register_vector(conn)
        return conn
    except Exception as e:
        log.error(f"Failed to get connection from pool: {e}", exc_info=True)
        raise

def release_db_connection(conn):
    """Releases a connection back to the pool."""
    global db_connection_pool # Use the pool again
    if db_connection_pool and conn:
        db_connection_pool.putconn(conn)

# --- Core Retriever Functions ---
def generate_embedding(text: str) -> Optional[List[float]]:
    """Generates an embedding for the given text using the loaded model."""
    global model
    if not model:
        model = load_embedding_model() # Load if not already loaded

    if not text or not isinstance(text, str):
        log.warning("generate_embedding received empty or invalid text.")
        return None

    try:
        embedding = model.encode(
            text,
            convert_to_numpy=True, # pgvector adapter needs numpy array
            show_progress_bar=False,
            normalize_embeddings=True # Normalize for cosine similarity
        )
        return embedding.tolist() # Return as list for easier handling/JSON
    except Exception as e:
        log.error(f"Error generating embedding for text '{text[:50]}...': {e}", exc_info=True)
        return None

def search_similar_chunks(query_embedding: List[float], top_k: int = config.TOP_K_RETRIEVAL) -> List[Dict]:
    """Searches the database for chunks most similar to the query embedding."""
    if not query_embedding:
        log.warning("search_similar_chunks received empty query embedding.")
        return []

    conn = None
    try:
        conn = get_db_connection()
        # Use RealDictCursor to get results as dictionaries
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Use the <=> operator for cosine distance (lower is better)
            # Ensure the embedding column name and table name match config/creation script
            query = f"""
                SELECT
                    chunk_id,
                    chunk_text,
                    metadata,
                    embedding <=> %s::vector AS distance
                FROM {config.DB_TABLE_NAME}
                ORDER BY distance ASC
                LIMIT %s;
            """
            # pgvector expects the embedding as a string representation of a list/numpy array
            # or directly as a numpy array if the adapter handles it.
            # Let's pass the list directly, psycopg2/pgvector should handle it.
            cur.execute(query, (query_embedding, top_k))
            results = cur.fetchall()
            log.info(f"Retrieved {len(results)} chunks from DB for similarity search.")
            # Convert metadata from JSON string back to dict if needed (depends on how it's stored/retrieved)
            # RealDictCursor often handles JSONB correctly
            # for res in results:
            #     if isinstance(res.get('metadata'), str):
            #         try:
            #             res['metadata'] = json.loads(res['metadata'])
            #         except json.JSONDecodeError:
            #             log.warning(f"Failed to decode metadata JSON for chunk_id {res.get('chunk_id')}")
            #             res['metadata'] = {} # Default to empty dict on error
            return results # List of dictionaries
    except psycopg2.Error as e:
        log.error(f"Database error during similarity search: {e}")
        # Attempt to rollback if connection is not in autocommit mode (pool connections usually aren't)
        if conn and not conn.autocommit:
             try:
                 conn.rollback()
             except psycopg2.Error as rb_err:
                 log.error(f"Rollback failed: {rb_err}")
        return [] # Return empty list on error
    except Exception as e:
        log.error(f"Unexpected error during similarity search: {e}", exc_info=True)
        return []
    finally:
        if conn:
            release_db_connection(conn)


# --- Cleanup Function ---
def close_connection_pool():
    """Closes all connections in the pool."""
    global db_connection_pool # Use the pool again
    if db_connection_pool:
        db_connection_pool.closeall()
        log.info("Database connection pool closed.")
        db_connection_pool = None

# --- Example Usage (for testing) ---
if __name__ == "__main__":
    if not config.IS_CONFIG_VALID:
        log.error("Configuration is invalid. Cannot run retriever example.")

    else:
        log.info("Running retriever.py example...")
        try:
            # Initialize dependencies
            load_embedding_model()
            init_connection_pool()

            # Example query
            test_query = "assessment for java developers with collaboration skills"
            log.info(f"Test Query: '{test_query}'")

            # Generate embedding
            start_time = time.time()
            query_emb = generate_embedding(test_query)
            end_time = time.time()
            log.info(f"Embedding generated in {end_time - start_time:.4f} seconds.")

            if query_emb:
                # Search for similar chunks
                start_time = time.time()
                similar_chunks = search_similar_chunks(query_emb, top_k=5)
                end_time = time.time()
                log.info(f"Database search completed in {end_time - start_time:.4f} seconds.")

                if similar_chunks:
                    print("\n--- Top 5 Similar Chunks ---")
                    for i, chunk in enumerate(similar_chunks):
                        print(f"\n{i+1}. Chunk ID: {chunk.get('chunk_id')}")
                        print(f"   Distance: {chunk.get('distance'):.4f}")
                        print(f"   Text: {chunk.get('chunk_text', '')[:150]}...") # Print snippet
                        print(f"   Metadata: {chunk.get('metadata')}") # Print metadata
                    print("---------------------------\n")
                else:
                    print("No similar chunks found.")
            else:
                print("Failed to generate query embedding.")

        except Exception as e:
            log.error(f"An error occurred during the example run: {e}", exc_info=True)
        finally:
            # Clean up
            close_connection_pool()
            log.info("Retriever example finished.")
