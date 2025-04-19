import logging
import os # Added import
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uvicorn
import time
from typing import List, Dict, Optional, Any # Added Any for broader type hinting

# Import project modules
from . import config
from . import retriever
from . import rag_pipeline

# --- Setup Logging ---
# Configure logging for FastAPI/Uvicorn if needed, or rely on RAG pipeline logging
log = logging.getLogger(__name__) # Use the same logger or configure FastAPI's

# --- Pydantic Models ---
class HealthResponse(BaseModel):
    status: str = "healthy"

class RecommendRequest(BaseModel):
    query: str = Field(..., description="Job description or natural language query for assessment recommendations.")

# Define the structure for a single assessment recommendation based on requirements
class AssessmentRecommendation(BaseModel):
    url: Optional[str] = Field(None, description="Valid URL to the assessment resource")
    adaptive_support: Optional[str] = Field(None, description="Either 'Yes' or 'No'")
    description: Optional[str] = Field(None, description="Detailed description of the assessment")
    duration: Optional[int] = Field(None, description="Duration of the assessment in minutes")
    remote_support: Optional[str] = Field(None, description="Either 'Yes' or 'No'")
    test_type: Optional[List[str]] = Field(None, description="Categories or types of the assessment")

class RecommendResponse(BaseModel):
    recommended_assessments: List[AssessmentRecommendation] = Field(
        ...,
        description="List of recommended assessments (max 10, min 0)."
    )


# --- FastAPI Lifecycle Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    log.info("API Startup: Initializing resources...")
    start_time = time.time()
    try:
        if not config.IS_CONFIG_VALID:
             log.error("API cannot start due to invalid configuration. Check logs.")
             # This won't actually stop FastAPI startup here, but logs the error.
             # Consider raising an exception if startup should halt.
        else:
             log.info("Loading embedding model...")
             retriever.load_embedding_model()
             log.info("Initializing database connection pool...")
             retriever.init_connection_pool()
             log.info("RAG pipeline dependencies initialized.")
        end_time = time.time()
        log.info(f"API Startup complete in {end_time - start_time:.2f} seconds.")
    except Exception as e:
        log.exception(f"API Startup failed: {e}")
        # Depending on severity, you might want the app to not start.
        # FastAPI doesn't have a direct way to halt startup from lifespan errors,
        # but subsequent requests will likely fail if resources aren't ready.
    yield
    # Shutdown logic
    log.info("API Shutdown: Cleaning up resources...")
    retriever.close_connection_pool()
    log.info("API Shutdown complete.")

# --- FastAPI App Initialization ---
app = FastAPI(
    title="SHL Assessment Recommendation API",
    description="Recommends SHL assessments based on natural language queries or job descriptions using RAG.",
    version="1.0.0",
    lifespan=lifespan # Use the lifespan context manager
)

# --- API Endpoints ---

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Status"],
    summary="Health Check",
    description="Provides a simple status check to verify the API is running and healthy."
)
async def health_check():
    """Returns a status message indicating the API is healthy."""
    # Could add checks here for DB connection, model loading status etc.
    # For now, just confirms the API endpoint is reachable.
    return HealthResponse(status="healthy")

@app.get("/_ah/live", include_in_schema=False)
async def live_check():
    """App Engine Flex liveness check."""
    return JSONResponse(content={"status": "ok"})

@app.get("/_ah/ready", include_in_schema=False)
async def ready_check():
    """App Engine Flex readiness check."""
    # You could add more complex checks here if needed, e.g., DB connectivity
    return JSONResponse(content={"status": "ok"})


@app.post(
    "/recommend",
    response_model=RecommendResponse,
    tags=["Recommendations"],
    summary="Get Assessment Recommendations",
    description="Accepts a job description or natural language query and returns relevant SHL assessments.",
    status_code=status.HTTP_200_OK
)
async def recommend_assessments(request: RecommendRequest):
    """
    Takes a query and returns recommended assessments using the RAG pipeline.
    """
    start_time = time.time()
    log.info(f"Received recommendation request for query: '{request.query[:100]}...'")

    if not config.IS_CONFIG_VALID:
        log.error("Recommendation endpoint called but configuration is invalid.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration is invalid. Please check server logs."
        )

    try:
        # Call the RAG pipeline
        result = rag_pipeline.get_recommendations(request.query)

        if result is None:
            # This indicates an internal error during the RAG process
            log.error(f"RAG pipeline failed for query: {request.query}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate recommendations due to an internal server error."
            )

        # Validate and return the result
        # The RAG pipeline should return the correct structure, but Pydantic handles validation
        response_data = RecommendResponse(**result)
        end_time = time.time()
        log.info(f"Recommendation request processed in {end_time - start_time:.2f} seconds. Found {len(response_data.recommended_assessments)} recommendations.")
        return response_data

    except HTTPException as http_exc:
        # Re-raise HTTPExceptions directly
        raise http_exc
    except Exception as e:
        log.exception(f"Unexpected error processing recommendation request for query '{request.query}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {e}"
        )


@app.post(
    "/recommend_raw",
    # No response_model specified to return raw dictionary/JSON
    tags=["Recommendations"],
    summary="Get Raw Assessment Recommendations",
    description="Accepts a query and returns the raw JSON/dictionary output from the RAG pipeline.",
    status_code=status.HTTP_200_OK
)
async def recommend_assessments_raw(request: RecommendRequest) -> Dict[str, Any]:
    """
    Takes a query and returns the raw dictionary result from the RAG pipeline.
    Suitable for programmatic consumption where the exact structure might vary
    or where the consumer handles validation.
    """
    start_time = time.time()
    log.info(f"Received raw recommendation request for query: '{request.query[:100]}...'")

    if not config.IS_CONFIG_VALID:
        log.error("Raw recommendation endpoint called but configuration is invalid.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration is invalid. Please check server logs."
        )

    try:
        # Call the RAG pipeline
        result = rag_pipeline.get_recommendations(request.query)

        if result is None:
            # This indicates an internal error during the RAG process
            log.error(f"RAG pipeline failed for raw query: {request.query}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate recommendations due to an internal server error."
            )

        # Return the raw dictionary result directly
        end_time = time.time()
        log.info(f"Raw recommendation request processed in {end_time - start_time:.2f} seconds.")
        # FastAPI automatically converts dict to JSON response
        return result

    except HTTPException as http_exc:
        # Re-raise HTTPExceptions directly
        raise http_exc
    except Exception as e:
        log.exception(f"Unexpected error processing raw recommendation request for query '{request.query}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {e}"
        )


# --- Add Exception Handler for Generic Errors ---
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled exception for request {request.url}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"An internal server error occurred: {exc}"},
    )


# --- Main Block for Running with Uvicorn ---
if __name__ == "__main__":
    print("Starting FastAPI server with Uvicorn...")
    # Use os.getenv to get the port, falling back to config if not set
    port_to_use = int(os.getenv("PORT", config.API_PORT))
    print(f"Access the API at http://{config.API_HOST}:{port_to_use}")
    print(f"Swagger UI available at http://{config.API_HOST}:{port_to_use}/docs")

    # Ensure config is valid before trying to run
    if not config.IS_CONFIG_VALID:
         print("\n--- FATAL ERROR ---")
         print("Configuration is invalid. Cannot start API server.")
         print("Please check errors printed during configuration loading and fix your .env file.")
         print("-------------------\n")
    else:
        uvicorn.run(
            "src.api:app", # Point to the FastAPI app instance
            host=config.API_HOST, # Should be "0.0.0.0"
            # Use PORT environment variable provided by Cloud Run, fallback to config.API_PORT
            port=port_to_use,
            reload=True, # Enable auto-reload for development (consider disabling in production)
            log_level="info" # Set uvicorn log level
        )
