import json
from typing import List, Dict

# --- Constants ---
MAX_RECOMMENDATIONS = 10 # Align with project requirements

# --- Prompt Template for Assessment Recommendation ---

# Note: The exact structure of metadata within the chunks is important here.
# We assume the metadata dictionary retrieved from the DB contains keys like:
# 'solution_name', 'url', 'adaptive_support', 'description', 'duration',
# 'remote_support', 'test_type' (or keys from which these can be reliably extracted).
# If the keys are different, this prompt (especially the context formatting)
# and the RAG pipeline logic will need adjustment.

RECOMMENDATION_PROMPT_TEMPLATE = """
**Task:** You are an AI assistant helping hiring managers find relevant SHL assessments. Your goal is to recommend SHL assessments based on the user's query and the provided context documents.

**Instructions:**
1.  Analyze the user's **Query** to understand their requirements (e.g., role, skills, duration constraints).
2.  Review the **Context Documents** provided below. These are chunks of text describing various SHL assessments, along with their metadata.
3.  Identify the assessments from the context that best match the user's query.
4.  Generate a list of recommended assessments (maximum {max_recommendations}).
5.  Format the output **strictly** as a JSON object containing a single key "recommended_assessments". This key should hold a list of JSON objects, where each object represents one recommended assessment.
6.  Each assessment object **must** include the following keys with accurate information extracted *only* from the provided context documents:
    *   `url`: (String) The direct URL to the assessment page.
    *   `adaptive_support`: (String) "Yes" or "No".
    *   `description`: (String) A concise description of the assessment.
    *   `duration`: (Integer) The assessment duration in minutes.
    *   `remote_support`: (String) "Yes" or "No".
    *   `test_type`: (List of Strings) The categories or types of the assessment.
7.  If the context does not contain enough information to fill a required field for a relevant assessment (e.g., duration is missing), try to infer it reasonably if possible, otherwise omit that specific assessment from the recommendations. Do not invent information.
8.  If no relevant assessments are found in the context, return an empty list: `{{"recommended_assessments": []}}`
9.  Base your recommendations *solely* on the provided context documents. Do not use any external knowledge.

**Query:**
{query}

**Context Documents:**
--- START OF CONTEXT ---
{context}
--- END OF CONTEXT ---

**Output (JSON Object):**
"""

def format_context_for_prompt(retrieved_chunks: List[Dict]) -> str:
    """Formats the retrieved chunks into a string suitable for the prompt context."""
    context_str = ""
    for i, chunk in enumerate(retrieved_chunks):
        context_str += f"--- Document {i+1} ---\n"
        # Extract relevant info from metadata, handling potential missing keys gracefully
        metadata = chunk.get('metadata', {})
        context_str += f"Chunk ID: {chunk.get('chunk_id', 'N/A')}\n"
        context_str += f"Solution Name: {metadata.get('solution_name', 'N/A')}\n" # Assuming 'solution_name' exists
        context_str += f"URL: {metadata.get('url', 'N/A')}\n"
        context_str += f"Adaptive Support: {metadata.get('adaptive_support', 'N/A')}\n"
        context_str += f"Remote Support: {metadata.get('remote_support', 'N/A')}\n"
        context_str += f"Duration (minutes): {metadata.get('duration', 'N/A')}\n"
        context_str += f"Test Type: {json.dumps(metadata.get('test_type', []))}\n" # Assuming test_type is a list
        context_str += f"Description/Text: {chunk.get('chunk_text', 'N/A')}\n"
        context_str += "---\n"
    return context_str.strip()

def get_recommendation_prompt(query: str, retrieved_chunks: List[Dict]) -> str:
    """Builds the full prompt string for the Gemini model."""
    formatted_context = format_context_for_prompt(retrieved_chunks)
    prompt = RECOMMENDATION_PROMPT_TEMPLATE.format(
        max_recommendations=MAX_RECOMMENDATIONS,
        query=query,
        context=formatted_context
    )
    return prompt

# --- Example Usage ---
if __name__ == "__main__":
    print("Running prompt_templates.py example...")
    example_query = "I need a test for Python skills, preferably under 30 minutes."
    example_chunks = [
        {
            'chunk_id': 'py1',
            'chunk_text': 'SHL Python Test assesses Python programming skills including syntax, data structures, and common libraries. Suitable for entry-level developers.',
            'metadata': {
                'solution_name': 'Python Test (New)',
                'url': 'https://www.shl.com/solutions/products/product-catalog/view/python-new/',
                'adaptive_support': 'No',
                'description': 'Multi-choice test that measures the knowledge of Python programming, databases, modules and library. For developers.',
                'duration': 11,
                'remote_support': 'Yes',
                'test_type': ['Knowledge & Skills', 'Technology']
            },
            'distance': 0.15
        },
        {
            'chunk_id': 'java1',
            'chunk_text': 'Core Java assessment for experienced developers. Covers advanced topics like concurrency and frameworks.',
            'metadata': {
                'solution_name': 'Core Java Advanced',
                'url': 'https://www.shl.com/solutions/products/product-catalog/view/core-java-advanced-level-new/',
                'adaptive_support': 'Yes',
                'description': 'Assesses advanced Java programming concepts.',
                'duration': 45,
                'remote_support': 'Yes',
                'test_type': ['Knowledge & Skills', 'Technology']
            },
            'distance': 0.85
        }
    ]

    full_prompt = get_recommendation_prompt(example_query, example_chunks)
    print("\n--- Example Prompt ---")
    print(full_prompt)
    print("--------------------\n")

    print("Expected JSON structure hint:")
    expected_structure = {
        "recommended_assessments": [
            {
                "url": "https://www.shl.com/solutions/products/product-catalog/view/python-new/",
                "adaptive_support": "No",
                "description": "Multi-choice test that measures the knowledge of Python programming, databases, modules and library. For developers.",
                "duration": 11,
                "remote_support": "Yes",
                "test_type": ["Knowledge & Skills", "Technology"]
            }
            # Potentially more assessments if relevant
        ]
    }
    print(json.dumps(expected_structure, indent=2))
