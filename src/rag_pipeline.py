import google.generativeai as genai
import logging
import json
import re # Added for URL detection
from typing import List, Dict, Optional, Any
import psycopg2 # Added to handle potential database errors
import google.generativeai.types as genai_types # Added for function calling types

# Import project modules
from . import config
from . import retriever
from . import prompt_templates
from . import web_utils # Added for URL extraction function

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Configure Gemini API ---
def configure_gemini():
    """Configures the Google Generative AI client."""
    if not config.GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not found in configuration. Cannot configure Gemini.")
        raise ValueError("Missing GEMINI_API_KEY")
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        log.info("Google Generative AI client configured successfully.")
    except Exception as e:
        log.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
        raise

# --- Define Function Tool for Gemini ---
extract_text_tool = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name='extract_text_from_url',
            description='Fetches the main text content from a given web URL.',
            # Define parameters using OpenAPI schema format (dictionary)
            parameters={
                'type': 'object', # Use lowercase 'object'
                'properties': {
                    'url': {
                        'type': 'string', # Use lowercase 'string'
                        'description': "The URL to fetch content from."
                    }
                },
                'required': ['url']
            }
        )
    ]
)

# --- Initialize Gemini Model ---
# Note: Tools are now passed directly to generate_content when needed, not during model init.
def get_gemini_model(model_name: str = config.GEMINI_MODEL_NAME):
    """Initializes and returns the Gemini generative model."""
    try:
        # Configure safety settings to be less restrictive if needed,
        # but be mindful of API policies. Start with defaults.
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        model = genai.GenerativeModel(
            model_name,
            safety_settings=safety_settings, # Apply default safety settings
            generation_config=genai.types.GenerationConfig(
                # Ensure the output is JSON for the *final* recommendation step
                # For intermediate steps like function calling, default response type is fine.
                # response_mime_type="application/json", # Set this only for the final call
                # Adjust temperature for creativity vs. factuality (lower is more factual)
                temperature=0.1,
                 # max_output_tokens=... # Set if needed
            )
        )
        log.info(f"Gemini model '{model_name}' initialized.")
        return model
    except Exception as e:
        log.error(f"Failed to initialize Gemini model: {e}", exc_info=True)
        raise

# --- Helper Function to Check for URL ---
def is_url(text: str) -> bool:
    """Checks if a string looks like a valid HTTP/HTTPS URL."""
    # Simple regex check for http:// or https:// at the start
    return bool(re.match(r'^https?://\S+$', text))

# --- RAG Pipeline Function ---
def get_recommendations(original_query: str) -> Optional[Dict]:
    """
    Executes the RAG pipeline: handle input type (URL/text), embed content,
    retrieve chunks, generate recommendations using the original query context.

    Args:
        original_query: The user's input string (query, JD, or URL).

    Returns:
        A dictionary containing the 'recommended_assessments' list,
        or None if a critical error occurs during the process.
        The list will be empty if no relevant assessments are found.
    """
    if not original_query:
        log.warning("Received empty query.")
        return {"recommended_assessments": []}

    gemini_model = None
    text_to_embed = original_query # Default to using the original query text

    try:
        # --- Step 1: Handle Input Type (URL or Text) ---
        if is_url(original_query):
            log.info(f"Input detected as URL: {original_query}")
            try:
                # Configure and initialize model for function calling
                configure_gemini()
                gemini_model = get_gemini_model() # Use default model

                # First call: Ask Gemini to use the tool
                log.info("Asking Gemini to call URL extraction tool...")
                prompt_for_tool = f"Please extract the main text content from this URL: {original_query}"
                first_response = gemini_model.generate_content(
                    prompt_for_tool,
                    tools=[extract_text_tool]
                )

                # Check if Gemini wants to call the function
                if not first_response.candidates[0].content.parts or \
                   not first_response.candidates[0].content.parts[0].function_call:
                    log.error("Gemini did not return a function call as expected.")
                    # Fallback: Use the URL itself as text? Or return error?
                    # For now, let's try embedding the URL string itself as a fallback.
                    log.warning("Falling back to using the URL string itself for embedding.")
                    text_to_embed = original_query
                else:
                    function_call = first_response.candidates[0].content.parts[0].function_call
                    if function_call.name != "extract_text_from_url":
                        log.error(f"Gemini called unexpected function: {function_call.name}")
                        text_to_embed = original_query # Fallback
                    else:
                        url_to_fetch = function_call.args['url']
                        log.info(f"Gemini requested extraction for URL: {url_to_fetch}")

                        # Execute the actual Python function
                        extracted_content = web_utils.extract_text_from_url(url_to_fetch)

                        # Prepare the function response for Gemini
                        function_response_part = genai_types.Part(
                            function_response=genai_types.FunctionResponse(
                                name='extract_text_from_url',
                                response={'content': extracted_content} # Send result back as dict
                            )
                        )

                        # Second call: Send the function result back to Gemini
                        log.info("Sending extracted content back to Gemini...")
                        second_response = gemini_model.generate_content(
                            [first_response.candidates[0].content, function_response_part] # History + Function Result
                        )

                        # Get the final text from Gemini's response
                        if hasattr(second_response, 'text'):
                            processed_text = second_response.text
                            log.info("Received processed text from Gemini after function call.")
                            # Check if the extraction failed (our function returns "Error: ...")
                            if processed_text.startswith("Error:"):
                                log.error(f"URL extraction failed: {processed_text}")
                                # Fallback to original URL string if extraction failed
                                text_to_embed = original_query
                            else:
                                text_to_embed = processed_text # Use the successfully extracted text
                        else:
                            log.error("Could not get final text from Gemini after function call.")
                            text_to_embed = original_query # Fallback

            except Exception as e:
                log.error(f"Error during URL processing with Gemini function calling: {e}", exc_info=True)
                # Fallback to using the original URL string if function calling fails
                text_to_embed = original_query
        else:
            log.info("Input is treated as text (Query/JD).")
            text_to_embed = original_query # Already set as default

        # --- Step 2: Generate Embedding for the Determined Text ---
        log.info(f"Generating embedding for text: '{text_to_embed[:100]}...'")
        query_embedding = retriever.generate_embedding(text_to_embed)
        if not query_embedding:
            log.error("Failed to generate embedding for the input text.")
            return None # Indicate processing error

        # --- Step 3: Retrieve Relevant Chunks ---
        log.info(f"Searching for top {config.TOP_K_RETRIEVAL} similar chunks...")
        retrieved_chunks = retriever.search_similar_chunks(query_embedding, top_k=config.TOP_K_RETRIEVAL)
        if not retrieved_chunks:
            log.info("No relevant chunks found in the database for the query.")
            return {"recommended_assessments": []}
        log.info(f"Retrieved {len(retrieved_chunks)} chunks.")
        # --- Log retrieved chunks for debugging ---
        try:
            log.info("--- Retrieved Chunks (Cloud Env Debug) ---")
            for i, chunk in enumerate(retrieved_chunks):
                 log.info(f"Chunk {i+1} ID: {chunk.get('chunk_id', 'N/A')}, Distance: {chunk.get('distance', 'N/A'):.4f}")
                 log.info(f"  Metadata: {json.dumps(chunk.get('metadata', {}))}")
                 log.info(f"  Text: {chunk.get('chunk_text', '')[:200]}...") # Log snippet
            log.info("-----------------------------------------")
        except Exception as log_e:
            log.warning(f"Error logging retrieved chunks: {log_e}")
        # --- End Log retrieved chunks ---

        # --- Step 4: Build Final Prompt for LLM ---
        # Use the *original_query* for context in the final prompt, along with retrieved chunks
        log.info("Building final prompt for Gemini model...")
        final_prompt = prompt_templates.get_recommendation_prompt(original_query, retrieved_chunks)
        # log.debug(f"Generated Final Prompt:\n{final_prompt}")

        # --- Step 5: Call Gemini API for Final Recommendation ---
        log.info(f"Calling Gemini model '{config.GEMINI_MODEL_NAME}' for final recommendations...")
        # Ensure configured, get model instance (without tools this time)
        configure_gemini()
        # Re-initialize model specifically for JSON output
        final_gemini_model = genai.GenerativeModel(
             config.GEMINI_MODEL_NAME,
             safety_settings=get_gemini_model()._safety_settings, # Reuse safety settings from default model
             generation_config=genai.types.GenerationConfig(
                 response_mime_type="application/json", # Request JSON output
                 temperature=0.1
             )
         )

        final_response = final_gemini_model.generate_content(final_prompt) # No tools needed here

        # --- Step 6: Process Final Response ---
        log.info("Received final recommendation response from Gemini.")
        # Accessing the text content
        if hasattr(final_response, 'text'):
            response_text = final_response.text
            log.debug(f"Gemini Raw Final Response Text:\n{response_text}")
        else:
             try:
                 response_text = final_response.parts[0].text
                 log.debug(f"Gemini Raw Final Response Text (from parts):\n{response_text}")
             except (AttributeError, IndexError, TypeError) as e:
                 log.error(f"Could not extract text from Gemini final response object: {final_response}. Error: {e}")
                 try:
                     log.warning(f"Gemini final generation safety feedback: {final_response.prompt_feedback}")
                 except AttributeError:
                     pass
                 return None

        # Clean potential markdown artifacts if JSON mime type wasn't perfectly enforced
        if response_text.startswith("```json"):
            response_text = response_text.strip("```json").strip("`").strip()

        # Parse the final JSON response
        try:
            recommendations_json = json.loads(response_text)
            if "recommended_assessments" not in recommendations_json or not isinstance(recommendations_json["recommended_assessments"], list):
                log.error(f"Final Gemini response JSON is missing 'recommended_assessments' list: {response_text}")
                return None
            log.info(f"Successfully parsed final recommendations. Found {len(recommendations_json['recommended_assessments'])} items.")
            return recommendations_json

        except json.JSONDecodeError as e:
            log.error(f"Failed to decode final JSON response from Gemini: {e}")
            log.error(f"Invalid final JSON string received: {response_text}")
            return None
        except Exception as e:
             log.error(f"Unexpected error processing final Gemini response: {e}", exc_info=True)
             return None

    # --- Catch specific exceptions from different stages ---
    except FileNotFoundError as e:
         log.error(f"Initialization failed (e.g., model not found): {e}")
         return None
    except ValueError as e: # Includes config errors like missing API key
         log.error(f"Configuration or value error: {e}")
         return None
    except psycopg2.Error as e:
         log.error(f"Database error during RAG pipeline: {e}")
         return None
    except genai_types.BlockedPromptException as e:
         log.error(f"Gemini API call failed due to blocked prompt: {e}")
         return None
    except genai_types.StopCandidateException as e:
         log.error(f"Gemini API call failed due to stop candidate: {e}")
         return None
    except Exception as e: # Catch-all for unexpected errors
        log.error(f"An unexpected error occurred in the RAG pipeline: {e}", exc_info=True)
        return None


# --- Example Usage (for testing) ---
if __name__ == "__main__":
    if not config.IS_CONFIG_VALID:
        log.error("Configuration is invalid. Cannot run RAG pipeline example.")
    else:
        log.info("Running rag_pipeline.py example...")
        try:
            # Initialize dependencies (retriever handles its own init)
            retriever.load_embedding_model()
            retriever.init_connection_pool()

            # Example queries
            test_queries = [
                "I am hiring for Java developers who can also collaborate effectively with my business teams. Looking for an assessment(s) that can be completed in 40 minutes.",
                "https://jobs.lever.co/openai/653a7ccc-936a-4d79-9f61-116f69575d00", # Example URL
                "Looking to hire mid-level professionals who are proficient in Python, SQL and Java Script. Need an assessment package that can test all skills with max duration of 60 minutes.",
                "I am hiring for an analyst and wants applications to screen using Cognitive and personality tests, what options are available within 45 mins."
            ]

            for test_query in test_queries:
                log.info(f"\n--- Testing Query ---\n{test_query}\n--------------------")
                recommendations = get_recommendations(test_query)

                print("\n--- RAG Pipeline Result ---")
                if recommendations is not None:
                    print(json.dumps(recommendations, indent=2))
                else:
                    print("RAG pipeline failed to produce recommendations for this query.")
                print("-------------------------\n")

        except Exception as e:
            log.error(f"An error occurred during the RAG pipeline example run: {e}", exc_info=True)
        finally:
            # Clean up retriever resources
            retriever.close_connection_pool()
            log.info("RAG pipeline example finished.")
