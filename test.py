# -*- coding: utf-8 -*-
"""
Tests a locally downloaded fine-tuned Sentence Transformer model.

1. Loads the model from a specified path.
2. Uses MPS (Apple Silicon GPU) if available, otherwise CPU.
3. Encodes sample sentences relevant to the fine-tuning domain (SHL).
4. Calculates and prints cosine similarity scores between sentence pairs.
"""

import torch
from sentence_transformers import SentenceTransformer, util
from pathlib import Path
import logging
import time

# --- Configuration ---
# *** IMPORTANT: Set this to the correct path to your model folder ***
# Assumes the script is run from the directory *containing* the model folder
MODEL_PATH = Path("shl_finetuned_mpnet_model_H100")

# Sample sentences/queries relevant to the SHL domain
SENTENCES = [
    # 0: A typical user query
    "cognitive ability test for graduate roles",
    # 1: A relevant document snippet (positive example)
    "Verify G+ Ability Test: Measures general mental ability for graduate and entry-level positions. Includes verbal, numerical, and logical reasoning. Takes 37 minutes.",
    # 2: A somewhat related but different assessment (should be less similar than 1)
    "The Occupational Personality Questionnaire (OPQ32) assesses behavioral styles relevant to workplace performance across 32 dimensions.",
    # 3: An unrelated SHL concept
    "SHL provides assessment solutions for talent acquisition and development.",
    # 4: A completely unrelated sentence
    "The quick brown fox jumps over the lazy dog.",
]

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Main Test Function ---
def test_model(model_path: Path):
    """Loads and tests the Sentence Transformer model."""

    log.info(f"Attempting to load model from: {model_path.resolve()}")

    if not model_path.exists() or not model_path.is_dir():
        log.error(f"Model directory not found at '{model_path.resolve()}'.")
        log.error("Please ensure the path is correct and the model files are present.")
        return

    # --- Determine Device ---
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
        log.warning("MPS not available/built. Falling back to CPU. Encoding might be slower.")
    log.info(f"Using device: {device.type}")

    # --- Load Model ---
    try:
        start_time = time.time()
        model = SentenceTransformer(str(model_path), device=device.type)
        load_time = time.time() - start_time
        log.info(f"Successfully loaded model '{model_path.name}' in {load_time:.2f} seconds.")
        log.info(f"Model loaded onto device: {model.device}") # Verify device placement
    except Exception as e:
        log.error(f"Failed to load the model from '{model_path.resolve()}': {e}", exc_info=True)
        return

    # --- Encode Sentences ---
    log.info("Encoding sample sentences...")
    try:
        start_time = time.time()
        # Ensure model is on the correct device before encoding
        model.to(device)
        embeddings = model.encode(SENTENCES, convert_to_tensor=True, show_progress_bar=False)
        encode_time = time.time() - start_time
        log.info(f"Successfully encoded {len(SENTENCES)} sentences in {encode_time:.2f} seconds.")
        log.info(f"Embedding dimensions: {embeddings.shape}") # Should be 768 for mpnet
    except Exception as e:
        log.error(f"Failed to encode sentences: {e}", exc_info=True)
        return

    # --- Calculate and Print Similarities ---
    log.info("\n--- Cosine Similarity Scores ---")
    log.info("(Higher score means more similar according to the model)")

    # Compare Query (0) with others
    print("-" * 20)
    log.info(f"Comparing Query (0) with others:")
    log.info(f"  Query:    '{SENTENCES[0]}'")
    log.info(f"  Positive: '{SENTENCES[1]}'")
    log.info(f"  Negative: '{SENTENCES[2]}'")
    log.info(f"  Unrelated:'{SENTENCES[4]}'")
    print("-" * 20)

    try:
        cos_sim_0_1 = util.cos_sim(embeddings[0], embeddings[1]).item()
        cos_sim_0_2 = util.cos_sim(embeddings[0], embeddings[2]).item()
        cos_sim_0_3 = util.cos_sim(embeddings[0], embeddings[3]).item()
        cos_sim_0_4 = util.cos_sim(embeddings[0], embeddings[4]).item()

        log.info(f"Query (0) vs Positive Doc (1): {cos_sim_0_1:.4f} <-- EXPECT HIGHEST")
        log.info(f"Query (0) vs Negative Doc (2): {cos_sim_0_2:.4f}")
        log.info(f"Query (0) vs Related Concept (3): {cos_sim_0_3:.4f}") # Should be lower than 1, maybe higher than 2
        log.info(f"Query (0) vs Unrelated (4):   {cos_sim_0_4:.4f} <-- EXPECT LOWEST")
        print("-" * 20)

        # Optional: Compare Positive (1) with others
        log.info(f"Comparing Positive Doc (1) with others:")
        cos_sim_1_2 = util.cos_sim(embeddings[1], embeddings[2]).item()
        cos_sim_1_4 = util.cos_sim(embeddings[1], embeddings[4]).item()
        log.info(f"Positive (1) vs Negative (2): {cos_sim_1_2:.4f}")
        log.info(f"Positive (1) vs Unrelated (4): {cos_sim_1_4:.4f}")
        print("-" * 20)

        # --- Basic Check ---
        if cos_sim_0_1 > cos_sim_0_2 and cos_sim_0_1 > cos_sim_0_4:
            log.info("Basic check PASSED: Query is more similar to the positive document than to the negative and unrelated ones.")
        else:
            log.warning("Basic check FAILED: Query similarity to positive document is NOT the highest among comparisons. Model might need further tuning or data review.")

    except Exception as e:
        log.error(f"Failed to calculate or print similarities: {e}", exc_info=True)


# --- Run the Test ---
if __name__ == "__main__":
    test_model(MODEL_PATH)