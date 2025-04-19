# -*- coding: utf-8 -*-
"""
Fine-tunes a Sentence Transformer model using triplet data for information retrieval.

Loads pre-generated triplets (anchor, positive, negative) and a corpus of text chunks.
Trains the model using MultipleNegativesRankingLoss. Includes functionality for
evaluation during training using InformationRetrievalEvaluator.
"""

import json
import logging
import math
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# Third-party libraries
import torch
from sentence_transformers import SentenceTransformer, InputExample, losses, evaluation
from sentence_transformers.evaluation import InformationRetrievalEvaluator, SimilarityFunction
from torch.utils.data import DataLoader

# --- Configuration ---

# Model Configuration
# BASE_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2" # 768 dimensions
BASE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2" # 384 dimensions

# File Paths (Using pathlib for better path handling)
# NOTE: INPUT_TRIPLET_FILE comes from the *previous* script's output
INPUT_TRIPLET_FILE = Path("finetuning_triplets_v2_english.jsonl")
# NOTE: PROCESSED_CHUNKS_FILE is needed for the evaluator's corpus
PROCESSED_CHUNKS_FILE = Path("processed_shl_chunks.jsonl")
OUTPUT_MODEL_DIR = Path("shl_finetuned_model_with_eval")
CHECKPOINT_SAVE_DIR = Path("shl_finetuned_checkpoints")

# Training Parameters
TRAIN_BATCH_SIZE = 4  # Adjust based on GPU/MPS memory (e.g., 4, 8, 16)
NUM_EPOCHS = 2        # Start with 1-2 for testing, increase for full training
LEARNING_RATE = 2e-5
# Max sequence length for the transformer model.
# If None, uses the model's default. If set, truncates/pads sequences.
# Ensure this value is appropriate for the chosen BASE_MODEL_NAME.
MAX_SEQ_LENGTH: Optional[int] = 384 # Example: align with MiniLM's typical usage

# Evaluation Parameters
VALIDATION_SPLIT_PERCENTAGE = 0.05 # Use 5% of triplets for validation (min 50 samples)
MIN_VALIDATION_SAMPLES = 50
# Evaluate N times per epoch. Set to 0 or None to disable evaluation during training.
EVALUATION_STEPS_PER_EPOCH: Optional[int] = 4
# Similarity function for InformationRetrievalEvaluator
IR_EVAL_SIMILARITY_FUNCTION = SimilarityFunction.COSINE

# Device Configuration
# Set to False to force CPU if MPS/CUDA causes issues or is unavailable.
# The script will automatically detect MPS or CUDA if available and USE_ACCELERATED_DEVICE is True.
USE_ACCELERATED_DEVICE = True

# --- Constants ---
CHUNK_TEXT_KEY = 'chunk_text' # Key for text content in chunk JSONL

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Type Aliases ---
TripletData = List[str] # [anchor, positive, negative]
CorpusDict = Dict[str, str] # {doc_id: doc_text}
QueriesDict = Dict[str, str] # {query_id: query_text}
RelevantDocsDict = Dict[str, set[str]] # {query_id: {relevant_doc_id_1, ...}}

# --- Helper: Check Accelerate ---
try:
    import accelerate
    log.info(f"Accelerate library found (version {accelerate.__version__}).")
except ImportError:
    log.warning("Accelerate library not found (pip install accelerate). Training might be less efficient.")

# --- Data Loading ---

def load_triplets(triplet_file: Path) -> Optional[List[TripletData]]:
    """Loads triplets from a JSON Lines file."""
    log.info(f"Loading triplets from {triplet_file}...")
    all_triplets: List[TripletData] = []
    line_count = 0
    invalid_count = 0
    try:
        with triplet_file.open('r', encoding='utf-8') as f:
            for line in f:
                line_count += 1
                try:
                    triplet = json.loads(line)
                    # Validate format: list of 3 non-empty strings
                    if (isinstance(triplet, list) and
                        len(triplet) == 3 and
                        all(isinstance(t, str) and t.strip() for t in triplet)):
                        all_triplets.append([t.strip() for t in triplet]) # Add stripped text
                    else:
                        invalid_count += 1
                        log.warning(f"Skipping invalid triplet line {line_count}: Incorrect format or empty element(s). Content: {line.strip()}")
                except json.JSONDecodeError:
                    invalid_count += 1
                    log.warning(f"Skipping invalid JSON line {line_count} in {triplet_file}: {line.strip()}")
                except Exception as e:
                    invalid_count += 1
                    log.warning(f"Error processing triplet line {line_count} in {triplet_file}: {e}")

        log.info(f"Read {line_count} lines from {triplet_file}.")
        log.info(f"Loaded {len(all_triplets)} valid triplets.")
        if invalid_count > 0:
            log.warning(f"Skipped {invalid_count} invalid or problematic triplet lines.")

        if not all_triplets:
            log.error("No valid triplets were loaded. Cannot proceed.")
            return None
        return all_triplets

    except FileNotFoundError:
        log.critical(f"CRITICAL: Triplet file not found: {triplet_file}")
        return None
    except Exception as e:
        log.critical(f"CRITICAL: Error loading triplet file {triplet_file}: {e}", exc_info=True)
        return None

def load_corpus(chunk_file: Path) -> Optional[CorpusDict]:
    """Loads the document corpus from a JSON Lines file for the evaluator."""
    log.info(f"Loading corpus chunks from {chunk_file} for evaluator...")
    corpus: CorpusDict = {}
    chunk_id_counter = 0
    lines_read = 0
    invalid_json = 0
    missing_text = 0
    try:
        with chunk_file.open('r', encoding='utf-8') as f:
            for line in f:
                lines_read += 1
                try:
                    data = json.loads(line)
                    chunk_text = data.get(CHUNK_TEXT_KEY)
                    if chunk_text and not chunk_text.isspace():
                        # Use a simple numerical ID for the corpus dictionary
                        current_id = f"doc_{chunk_id_counter}"
                        corpus[current_id] = chunk_text.strip()
                        chunk_id_counter += 1
                    else:
                        missing_text += 1
                        log.debug(f"Skipping corpus line {lines_read}: Missing or empty '{CHUNK_TEXT_KEY}'.")
                except json.JSONDecodeError:
                    invalid_json += 1
                    log.warning(f"Skipping invalid JSON line {lines_read} in corpus file {chunk_file}: {line.strip()}")
                except Exception as e:
                    invalid_json += 1
                    log.warning(f"Error processing corpus line {lines_read} in {chunk_file}: {e}")

        log.info(f"Read {lines_read} lines from corpus file {chunk_file}.")
        log.info(f"Loaded {len(corpus)} valid documents into corpus.")
        if missing_text > 0: log.warning(f"Skipped {missing_text} corpus entries with missing/empty text.")
        if invalid_json > 0: log.warning(f"Skipped {invalid_json} invalid/problematic JSON lines in corpus file.")

        if not corpus:
            log.error("Corpus is empty after loading chunks. Evaluation will not be possible.")
            return None # Or return {} if evaluation is truly optional
        return corpus

    except FileNotFoundError:
        log.critical(f"CRITICAL: Corpus chunk file not found: {chunk_file}")
        return None
    except Exception as e:
        log.critical(f"CRITICAL: Error loading corpus chunk file {chunk_file}: {e}", exc_info=True)
        return None


# --- Evaluation Data Preparation ---

def create_ir_eval_data(
    validation_triplets: List[TripletData],
    corpus: CorpusDict
) -> Optional[Tuple[QueriesDict, RelevantDocsDict]]:
    """
    Prepares data structures required for InformationRetrievalEvaluator.
    Maps positive texts from validation triplets back to corpus document IDs.

    Args:
        validation_triplets: A list of [anchor, positive_text, negative_text] lists.
        corpus: A dictionary mapping {doc_id: doc_text}.

    Returns:
        A tuple containing (queries, relevant_docs) dictionaries, or None if
        preparation fails or yields no valid query-document mappings.
    """
    log.info("Preparing data for Information Retrieval Evaluator...")
    queries: QueriesDict = {}
    relevant_docs: RelevantDocsDict = {}

    # Create a reverse map from text to potential doc_ids for faster lookup
    # Handle potential duplicate texts mapping to multiple IDs if necessary
    text_to_ids: Dict[str, List[str]] = {}
    for doc_id, doc_text in corpus.items():
        if doc_text not in text_to_ids:
            text_to_ids[doc_text] = []
        text_to_ids[doc_text].append(doc_id)

    processed_queries = 0
    missing_pos_map_count = 0

    for i, triplet in enumerate(validation_triplets):
        anchor_text, positive_text, _ = triplet # Negative text isn't needed here
        query_id = f"q_{i}"
        queries[query_id] = anchor_text # Anchor is the query

        # Find the corpus doc ID(s) corresponding to the positive text
        # Use the pre-stripped positive_text from load_triplets
        matched_doc_ids = text_to_ids.get(positive_text)

        if matched_doc_ids:
            # Add all matching doc IDs as relevant for this query
            relevant_docs[query_id] = set(matched_doc_ids)
            processed_queries += 1
        else:
            missing_pos_map_count += 1
            log.warning(
                f"Could not find exact match in corpus for positive document text "
                f"from validation triplet {i}. Query ID: {query_id}. "
                f"Positive text snippet: '{positive_text[:100]}...'"
            )
            # Assign an empty set if the positive doc can't be found in the corpus.
            # The evaluator can handle queries with no relevant docs, but it's not ideal.
            relevant_docs[query_id] = set()

    log.info(f"Prepared evaluation data: {len(queries)} queries.")
    log.info(f"Mapped {processed_queries} queries to relevant documents in the corpus ({len(corpus)} total docs).")
    if missing_pos_map_count > 0:
        log.warning(
            f"Could not map positive documents for {missing_pos_map_count} validation triplets "
            f"back to corpus IDs. These queries will have no 'relevant' documents during evaluation."
        )

    if processed_queries == 0 and len(queries) > 0:
        log.error("Could not map *any* validation triplets to corpus documents. Evaluation is not possible.")
        return None
    elif not queries:
         log.error("No validation triplets provided to create evaluation data.")
         return None

    return queries, relevant_docs

# --- Core Training Logic ---

def train_model():
    """Loads data, configures the model and training loop, and runs fine-tuning."""

    # --- Determine Device ---
    if USE_ACCELERATED_DEVICE:
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available() and torch.backends.mps.is_built():
            # MPS (Apple Silicon GPU) support
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
            log.warning("MPS/CUDA not available/built or disabled. Falling back to CPU. Training will be slow.")
    else:
        device = torch.device("cpu")
        log.warning("USE_ACCELERATED_DEVICE is False. Using CPU. Training will be very slow.")
    log.info(f"Using device: {device.type}")


    # --- Load Data ---
    all_triplets = load_triplets(INPUT_TRIPLET_FILE)
    if not all_triplets:
        return # Stop if triplet loading failed

    corpus = load_corpus(PROCESSED_CHUNKS_FILE)
    # Corpus is primarily for the evaluator. Training can proceed without it,
    # but evaluation cannot.

    # --- Split Data ---
    random.shuffle(all_triplets)
    num_validation = int(len(all_triplets) * VALIDATION_SPLIT_PERCENTAGE)
    # Ensure a minimum number of validation samples if possible
    num_validation = max(num_validation, min(MIN_VALIDATION_SAMPLES, len(all_triplets) // 10))
    # Ensure num_validation doesn't exceed total triplets
    num_validation = min(num_validation, len(all_triplets) -1) # Need at least 1 for training

    if num_validation <= 0 and len(all_triplets) > 0 :
         log.warning("Not enough data for validation split, proceeding without evaluation.")
         validation_triplets = []
         training_triplets = all_triplets
    elif len(all_triplets) == 0:
         log.error("No triplets available for training or validation.")
         return
    else:
        validation_triplets = all_triplets[:num_validation]
        training_triplets = all_triplets[num_validation:]

    log.info(f"Data split: {len(training_triplets)} training triplets, {len(validation_triplets)} validation triplets.")

    # Prepare training samples (positive pairs for MultipleNegativesRankingLoss)
    # InputExample format: texts=[anchor, positive]
    train_samples_mnrl = [InputExample(texts=[t[0], t[1]]) for t in training_triplets]
    log.info(f"Created {len(train_samples_mnrl)} positive pairs for MNRL training.")
    if not train_samples_mnrl:
        log.error("No training samples could be created. Check triplet data.")
        return

    # --- Prepare Evaluator (if possible) ---
    evaluator: Optional[InformationRetrievalEvaluator] = None
    if validation_triplets and corpus and EVALUATION_STEPS_PER_EPOCH is not None and EVALUATION_STEPS_PER_EPOCH > 0:
        eval_data = create_ir_eval_data(validation_triplets, corpus)
        if eval_data:
            val_queries, val_relevant_docs = eval_data
            log.info(f"Creating InformationRetrievalEvaluator with {len(val_queries)} queries.")

            # --- Find this block (around line 319) ---
            evaluator = InformationRetrievalEvaluator(
                queries=val_queries,
                corpus=corpus, # Use the full corpus loaded earlier
                relevant_docs=val_relevant_docs,
          
           
                main_score_function=IR_EVAL_SIMILARITY_FUNCTION,
  
                name='shl-validation',
                show_progress_bar=True,
                write_csv=True, # Save evaluation results to CSV
            )
            log.info(f"InformationRetrievalEvaluator created successfully using {IR_EVAL_SIMILARITY_FUNCTION.name} similarity.")
        else:
            log.warning("Could not create evaluator due to issues preparing validation data (e.g., mapping failures). Proceeding without evaluation.")
    elif not validation_triplets:
         log.warning("No validation triplets available, skipping evaluator creation.")
    elif not corpus:
         log.warning("Corpus not loaded successfully, skipping evaluator creation.")
    elif not EVALUATION_STEPS_PER_EPOCH or EVALUATION_STEPS_PER_EPOCH <= 0:
         log.info("Evaluation during training is disabled (EVALUATION_STEPS_PER_EPOCH not set or <= 0).")


    # --- Load and Configure Base Model ---
    log.info(f"Loading base model: {BASE_MODEL_NAME}...")
    try:
        model = SentenceTransformer(BASE_MODEL_NAME, device=device.type)

        # Configure max sequence length if specified
        original_max_len = model.max_seq_length
        effective_max_seq_length = original_max_len # Start with model default
        log.info(f"Model default max_seq_length: {original_max_len}")

        if MAX_SEQ_LENGTH is not None:
            if MAX_SEQ_LENGTH > 0 and MAX_SEQ_LENGTH != original_max_len:
                log.info(f"Attempting to set model max_seq_length to: {MAX_SEQ_LENGTH}")
                # Sentence Transformers allows direct setting of this attribute
                model.max_seq_length = MAX_SEQ_LENGTH
                # Verify if it changed (some models might have fixed length internally)
                if model.max_seq_length == MAX_SEQ_LENGTH:
                    effective_max_seq_length = MAX_SEQ_LENGTH
                    log.info(f"Successfully set model max_seq_length to {effective_max_seq_length}.")
                else:
                    log.warning(f"Could not change model max_seq_length to {MAX_SEQ_LENGTH}. "
                                f"Current value remains {model.max_seq_length}. Using this value.")
                    effective_max_seq_length = model.max_seq_length # Use the actual value
            elif MAX_SEQ_LENGTH <= 0:
                 log.warning(f"Invalid MAX_SEQ_LENGTH ({MAX_SEQ_LENGTH}) provided. Using model default: {original_max_len}")
            # else: MAX_SEQ_LENGTH == original_max_len, no change needed.
        else:
            log.info("MAX_SEQ_LENGTH not specified, using model default.")

    except Exception as e:
        log.critical(f"Failed to load base model '{BASE_MODEL_NAME}': {e}", exc_info=True)
        return

    # --- Prepare DataLoader and Loss ---
    log.info("Preparing DataLoader...")
    # MNRL works best with larger batch sizes if memory allows
    train_dataloader = DataLoader(train_samples_mnrl, shuffle=True, batch_size=TRAIN_BATCH_SIZE)

    log.info("Initializing MultipleNegativesRankingLoss.")
    # This loss treats all other items in a batch as negatives for a given anchor-positive pair.
    train_loss = losses.MultipleNegativesRankingLoss(model=model)

    # --- Configure Training Steps ---
    steps_per_epoch = len(train_dataloader)
    num_training_steps = steps_per_epoch * NUM_EPOCHS
    warmup_steps = math.ceil(num_training_steps * 0.10) # 10% warmup

    # Calculate evaluation steps, handle potential division by zero or invalid factor
    evaluation_steps = 0
    if evaluator and EVALUATION_STEPS_PER_EPOCH and EVALUATION_STEPS_PER_EPOCH > 0 and steps_per_epoch > 0:
        evaluation_steps = steps_per_epoch // EVALUATION_STEPS_PER_EPOCH
        evaluation_steps = max(1, evaluation_steps) # Ensure at least 1 step if eval is enabled
        log.info(f"Evaluator will run approx. every {evaluation_steps} steps.")
    elif evaluator:
        log.warning(f"Cannot determine evaluation steps (EVALUATION_STEPS_PER_EPOCH={EVALUATION_STEPS_PER_EPOCH}, steps_per_epoch={steps_per_epoch}). Evaluation might not run as intended.")


    # --- Log Final Configuration ---
    log.info("--- Training Configuration ---")
    log.info(f"Base Model: {BASE_MODEL_NAME}")
    log.info(f"Device: {device.type}")
    log.info(f"Num Epochs: {NUM_EPOCHS}")
    log.info(f"Train Batch Size: {TRAIN_BATCH_SIZE}")
    log.info(f"Learning Rate: {LEARNING_RATE}")
    log.info(f"Effective Max Sequence Length: {effective_max_seq_length}")
    log.info(f"Total Training Steps: {num_training_steps}")
    log.info(f"Warmup Steps: {warmup_steps}")
    log.info(f"Input Triplets File: {INPUT_TRIPLET_FILE}")
    log.info(f"Output Model Path: {OUTPUT_MODEL_DIR}")
    log.info(f"Checkpoint Path: {CHECKPOINT_SAVE_DIR}")
    log.info(f"Evaluator Enabled: {'Yes' if evaluator else 'No'}")
    if evaluator:
        log.info(f"Evaluation Steps: {evaluation_steps}")
        log.info(f"Validation Split: {VALIDATION_SPLIT_PERCENTAGE*100:.1f}% ({len(validation_triplets)} samples)")
        log.info(f"Corpus Size for Eval: {len(corpus) if corpus else 'N/A'}")
        log.info(f"IR Eval Similarity: {IR_EVAL_SIMILARITY_FUNCTION.name}")
    log.info("-----------------------------")

    # --- Start Fine-Tuning ---
    start_time = datetime.now()
    log.info(f"Starting model fine-tuning at {start_time.strftime('%Y-%m-%d %H:%M:%S')}...")

    try:
        # Ensure output directories exist
        OUTPUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_SAVE_DIR.mkdir(parents=True, exist_ok=True)

        # Configure checkpoint saving strategy based on evaluation
        checkpoint_save_steps = evaluation_steps if evaluator and evaluation_steps > 0 else 0
        # If eval is disabled or steps are 0, don't save checkpoints based on steps during fit()
        # You might save at the end of epochs instead if desired, or just rely on the final save.
        if checkpoint_save_steps == 0:
            log.info("Checkpoint saving based on evaluation steps is disabled.")
            # Set a very large number to effectively disable step-based checkpointing in fit()
            # Rely on epoch-end saving or final model save.
            checkpoint_save_steps = num_training_steps + 1 # Ensure it's never reached


        model.fit(train_objectives=[(train_dataloader, train_loss)],
                  epochs=NUM_EPOCHS,
                  optimizer_params={'lr': LEARNING_RATE},
                  warmup_steps=warmup_steps,
                  output_path=str(OUTPUT_MODEL_DIR), # fit expects string path
                  checkpoint_path=str(CHECKPOINT_SAVE_DIR), # fit expects string path
                  checkpoint_save_steps=checkpoint_save_steps,
                  checkpoint_save_total_limit=3, # Keep last 3 checkpoints
                  evaluator=evaluator, # Pass the evaluator object
                  evaluation_steps=evaluation_steps, # Steps between evaluations
                  show_progress_bar=True,
                  # Consider use_amp=True if on CUDA and want potential speedup/memory saving,
                  # but test stability. MPS support for AMP can be experimental.
                  use_amp=False #(device.type == 'cuda') # Example: enable only for CUDA
                  )

        end_time = datetime.now()
        training_duration = end_time - start_time
        log.info(f"Fine-tuning complete at {end_time.strftime('%Y-%m-%d %H:%M:%S')}.")
        log.info(f"Total training time: {str(training_duration).split('.')[0]}") # H:MM:SS format
        log.info(f"Best model saved to: {OUTPUT_MODEL_DIR}")

    except RuntimeError as e:
        # Catch specific memory errors
        if "allocate" in str(e).lower() or "out of memory" in str(e).lower():
            log.critical(
                f"CRITICAL: Out of Memory Error during training on device '{device.type}'. "
                f"Try reducing 'TRAIN_BATCH_SIZE' (currently {TRAIN_BATCH_SIZE}). "
                f"If using MPS, ensure PyTorch is up-to-date."
             )
        elif "mps" in str(e).lower() and "datatype" in str(e).lower():
             log.critical(
                 f"CRITICAL: MPS backend error, possibly type mismatch during training. "
                 f"Ensure PyTorch version is compatible with your macOS/hardware. "
                 f"Consider disabling MPS (USE_ACCELERATED_DEVICE=False) or reporting bug to PyTorch. Error: {e}"
             )
        else:
            log.critical(f"CRITICAL: Runtime error during training: {e}", exc_info=True)
    except Exception as e:
        log.critical(f"CRITICAL: An unexpected error occurred during training: {e}", exc_info=True)


# --- Run the Training ---
if __name__ == "__main__":
    log.info("Starting fine-tuning script...")
    train_model()
    log.info("Fine-tuning script finished.")