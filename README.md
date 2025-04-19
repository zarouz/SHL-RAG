# SHL Assessment Recommendation System (RAG)

[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run)

This repository contains the code for an AI-powered system that recommends relevant SHL assessments based on user queries (like job descriptions or natural language questions). It utilizes a Retrieval-Augmented Generation (RAG) approach, combining information retrieval from a specialized vector database with the generative capabilities of Google's Gemini large language model.

The system consists of a FastAPI backend API and a Streamlit frontend, designed to be deployed as separate microservices on Google Cloud Run.

## Features

- **RAG Pipeline:** Employs Retrieval-Augmented Generation to provide contextually relevant assessment recommendations.
- **FastAPI Backend (`api-service`):** Handles core logic, RAG pipeline execution, database interaction, and embedding generation.
- **Streamlit Frontend (`frontend-service`):** Provides an interactive web interface for users to input queries and view recommendations.
- **Vector Database:** Uses PostgreSQL with the `pgvector` extension to store and efficiently search assessment text embeddings.
- **Sentence Transformers:** Leverages fine-tuned Sentence Transformer models for generating high-quality text embeddings.
- **Google Gemini:** Utilizes the Gemini Pro API for generating final recommendations based on retrieved context and extracting information from URLs.
- **Cloud Run Deployment:** Designed for easy deployment as containerized microservices on Google Cloud Run.
- **Cloud SQL Integration:** Connects securely to a Cloud SQL PostgreSQL instance via the Cloud SQL Auth Proxy.
- **Secret Management:** Uses Google Secret Manager for secure handling of sensitive credentials like API keys and database passwords.
- **Containerization:** Includes Dockerfiles (`Dockerfile.api`, `Dockerfile.frontend`) for building service images.
- **Cloud Build Integration:** Provides `cloudbuild-*.yaml` files for automated container builds on Google Cloud Build.
- **Data Preparation Scripts:** Includes scripts for web scraping SHL assessment data, processing text, generating embeddings, and creating fine-tuning data (optional).

## Architecture

The system is designed as two separate microservices deployed on Google Cloud Run:

1.  **`api-service` (FastAPI):**

    - Exposes REST endpoints (`/health`, `/recommend`).
    - Receives user queries.
    - Handles URL input by fetching and extracting text content using Gemini function calling.
    - Generates an embedding for the input query/text.
    - Queries the Cloud SQL/pgvector database to retrieve relevant assessment text chunks.
    - Constructs a prompt with the query and retrieved context.
    - Calls the Gemini API to generate final recommendations in JSON format.
    - Connects to Cloud SQL via the Cloud SQL Auth Proxy sidecar.
    - Loads secrets (DB Password, Gemini Key) from Secret Manager.

2.  **`frontend-service` (Streamlit):**
    - Provides a user-friendly web interface.
    - Takes user input (query or job description text/URL).
    - Calls the `/recommend` endpoint of the `api-service`.
    - Displays the returned assessment recommendations in a structured format.

## Technology Stack

- **Backend:** Python, FastAPI, Uvicorn
- **Frontend:** Python, Streamlit
- **LLM:** Google Gemini API (gemini-1.5-flash-latest)
- **Embeddings:** Sentence Transformers (fine-tuned `all-MiniLM-L6-v2` or `all-mpnet-base-v2`)
- **Database:** Google Cloud SQL (PostgreSQL) with `pgvector` extension
- **Deployment:** Google Cloud Run, Docker, Google Cloud Build
- **Secrets:** Google Secret Manager
- **Libraries:** `google-generativeai`, `psycopg2-binary`, `pgvector`, `requests`, `beautifulsoup4`, `pandas`, `numpy`, `python-dotenv`, `torch`

## Setup & Configuration

### Prerequisites

- Google Cloud SDK (`gcloud`) installed and authenticated.
- Docker installed.
- Python 3.11+ and `pip` installed.
- Git installed.
- A Google Cloud Project with Billing enabled.
- A Google Cloud SQL for PostgreSQL instance created (ensure the `pgvector` extension is enabled). See [Cloud SQL Docs](https://cloud.google.com/sql/docs/postgres/create-instance).
- An Artifact Registry repository created (Docker format). See [Artifact Registry Docs](https://cloud.google.com/artifact-registry/docs/repositories/create-repos#create).

### 1. Clone Repository

```bash
git clone https://github.com/zarouz/SHL-RAG.git
cd SHL-RAG
```

### 2. Enable Google Cloud APIs

Enable the necessary APIs in your Google Cloud project:

```bash
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    iam.googleapis.com \
    iamcredentials.googleapis.com # Needed for testing/token creation later if using advanced tests
```

### 3. Configure Environment Variables & Secrets

This project uses environment variables for configuration. A `.env` file is recommended for local development. For Cloud Run deployment, environment variables and secrets are configured directly during deployment.

**a) Create `.env` file (for Local Development):**

Create a file named `.env` in the project root directory. **Do not commit this file to Git.** Add the following variables:

```dotenv
# .env file

# Gemini API Key
GEMINI_API_KEY="your_gemini_api_key"

# Database Credentials (for LOCAL connection - NOT for Cloud Run Proxy)
DB_NAME="your_local_or_remote_db_name"
DB_USER="your_local_or_remote_db_user"
DB_PASSWORD="your_local_or_remote_db_password" # Use quotes if password has special chars
DB_HOST="localhost" # Or your remote DB host IP/DNS if not using local proxy/tunnel
DB_PORT="5432"      # Or your remote DB port

# Optional: GCS details if loading model from GCS (primarily for older App Engine style)
# GCS_MODEL_BUCKET="your_gcs_bucket_name"
# GCS_MODEL_BLOB_NAME="path/to/your/model.zip"
```

**b) Configure Secrets in Google Secret Manager (for Cloud Run):**

Store sensitive values like your database password and Gemini API key in Secret Manager.

```bash
# Store DB Password (replace with your actual password)
echo "YOUR_DB_PASSWORD_HERE" | gcloud secrets create shl-rag-db-password --data-file=- --project=<your-project-id>

# Store Gemini API Key (replace with your actual key)
echo "YOUR_GEMINI_API_KEY_HERE" | gcloud secrets create shl-rag-gemini-key --data-file=- --project=<your-project-id>
```

Grant Access: The Cloud Run service needs permission to access these secrets. When deploying, Cloud Run typically uses the Compute Engine default service account (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) unless you specify a different one. Grant this service account the "Secret Manager Secret Accessor" role for both secrets:

```bash
PROJECT_NUMBER=$(gcloud projects describe <your-project-id> --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant access to DB password secret
gcloud secrets add-iam-policy-binding shl-rag-db-password \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=<your-project-id>

# Grant access to Gemini API key secret
gcloud secrets add-iam-policy-binding shl-rag-gemini-key \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=<your-project-id>
```

_(Replace `<your-project-id>`)_

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Prepare Vector Database

Ensure Cloud SQL Instance is Ready: Your PostgreSQL instance must be running and have the `pgvector` extension enabled. You can enable it via the `gcloud` command or SQL client:

```sql
-- Connect to your database using psql or Cloud Shell
CREATE EXTENSION IF NOT EXISTS vector;
```

Populate Embeddings: The vector database needs to be populated with embeddings generated from the processed assessment data (`processed_shl_chunks.jsonl`). The `create_store_embeddings.py` script handles this.

**Important:** This script requires connecting to your database. For local execution connecting to Cloud SQL, you might need to use the Cloud SQL Auth Proxy or configure firewall rules for direct connection (less secure). Ensure your `.env` file has the correct credentials for the connection method you choose.

Run the script:

```bash
python create_store_embeddings.py
```

_(This can take some time depending on the corpus size and your machine's capabilities.)_

### 6. Prepare Fine-Tuned Model (Optional)

The repository includes scripts (`generate_synthetic_triplets.py`, `finetune_embedder.py`) to fine-tune a Sentence Transformer model for better retrieval performance on this specific dataset. A pre-fine-tuned model (`shl_finetuned_mpnet_model_H100` or similar) should ideally be present in the repository. If not, you would need to run these scripts, which require significant compute resources (GPU recommended) and setup (like obtaining LLM access for triplet generation).

## Local Development

Ensure your `.env` file is configured correctly for local database access.

### 1. Run API Service

```bash
# Make sure your .env file is present and configured for local DB access
uvicorn src.api:app --reload --host 0.0.0.0 --port 8080
```

The API will be available at `http://localhost:8080`. The Swagger UI documentation is at `http://localhost:8080/docs`.

### 2. Run Frontend Service

In a separate terminal:

```bash
# The frontend expects the API to be running at http://127.0.0.1:8080 by default (see src/app.py)
streamlit run src/app.py --server.port 8501
```

The frontend will be available at `http://localhost:8501`.

## Deployment to Google Cloud Run

These steps deploy the API and Frontend as two separate Cloud Run services.

### Prerequisites

- You have completed the Setup steps (APIs enabled, Artifact Registry repo created, Secrets created and access granted, `gcloud`/Docker configured).
- You know your Cloud SQL Instance Connection Name (e.g., `your-project-id:your-region:your-instance-name`).
- You have authorized Docker to push to your Artifact Registry:
  ```bash
  gcloud auth configure-docker <your-region>-docker.pkg.dev
  ```
  _(Replace `<your-region>` with the region of your Artifact Registry, e.g., `us-central1`)_

### 1. Build Container Images using Cloud Build

Build both service images and push them to your Artifact Registry.

```bash
# Set environment variables for build (replace placeholders)
export GCP_PROJECT="<your-project-id>"
export AR_REGION="<your-artifact-registry-region>" # e.g., us-central1
export AR_REPO="<your-artifact-registry-repo-name>" # e.g., gae-flexible or shl-rag-repo

# Build API image
gcloud builds submit --config cloudbuild-api.yaml \
  --substitutions=_LOCATION=$AR_REGION,_REPOSITORY=$AR_REPO \
  --project=$GCP_PROJECT

# Build Frontend image
gcloud builds submit --config cloudbuild-frontend.yaml \
  --substitutions=_LOCATION=$AR_REGION,_REPOSITORY=$AR_REPO \
  --project=$GCP_PROJECT
```

_(Note: The provided `cloudbuild-_.yaml` files need slight modification to use substitutions for registry location and repository name, or you can hardcode your values directly in the YAML files before running.)\*

Example Modified `cloudbuild-api.yaml` using substitutions:

```yaml
# cloudbuild-api.yaml
steps:
  - name: "gcr.io/cloud-builders/docker"
    args:
      [
        "build",
        "-t",
        "${_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${_REPOSITORY}/api-service:latest",
        "-f",
        "Dockerfile.api",
        ".",
      ]
images:
  - "${_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${_REPOSITORY}/api-service:latest"
options:
  logging: CLOUD_LOGGING_ONLY
```

_(Apply similar changes to `cloudbuild-frontend.yaml`)_

### 2. Deploy API Service (api-service)

```bash
# --- Required Variables ---
export GCP_PROJECT="<your-project-id>"
export CLOUD_RUN_REGION="<your-cloud-run-region>" # e.g., us-central1
export AR_REGION="<your-artifact-registry-region>" # e.g., us-central1
export AR_REPO="<your-artifact-registry-repo-name>" # e.g., gae-flexible or shl-rag-repo
export CLOUD_SQL_CONNECTION_NAME="<your-cloud-sql-connection-name>" # e.g., project:region:instance
export DB_USER_VAR="<your-database-user>" # e.g., postgres
export DB_NAME_VAR="<your-database-name>" # e.g., postgres
export DB_PASSWORD_SECRET_NAME="shl-rag-db-password" # Secret name created earlier
export GEMINI_KEY_SECRET_NAME="shl-rag-gemini-key"   # Secret name created earlier
# --- Optional Variables ---
export SERVICE_ACCOUNT_EMAIL="<your-service-account-email>" # e.g., PROJECT_NUMBER-compute@... or a dedicated one
export MEMORY="2Gi"

gcloud run deploy api-service \
  --project=$GCP_PROJECT \
  --region=$CLOUD_RUN_REGION \
  --image="${AR_REGION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}/api-service:latest" \
  --platform=managed \
  --memory=$MEMORY \
  --cpu=1 \
  --concurrency=80 \
  --timeout=300s \
  --allow-unauthenticated \
  --add-cloudsql-instances=$CLOUD_SQL_CONNECTION_NAME \
  --update-secrets="DB_PASSWORD=${DB_PASSWORD_SECRET_NAME}:latest,GEMINI_API_KEY=${GEMINI_KEY_SECRET_NAME}:latest" \
  --update-env-vars="DB_NAME=${DB_NAME_VAR},DB_USER=${DB_USER_VAR}" \
  # Optional: Specify service account if not using default
  # --service-account=$SERVICE_ACCOUNT_EMAIL
```

**Note:** `--allow-unauthenticated` makes the API publicly accessible. If you want to restrict access (e.g., only allow the frontend service), use IAM invoker roles and configure authentication.

### 3. Deploy Frontend Service (frontend-service)

First, get the URL of the deployed `api-service`:

```bash
export API_SERVICE_URL=$(gcloud run services describe api-service \
  --project=$GCP_PROJECT \
  --region=$CLOUD_RUN_REGION \
  --platform=managed \
  --format='value(status.url)')

echo "API Service URL: ${API_SERVICE_URL}"

# Check if URL was retrieved
if [ -z "$API_SERVICE_URL" ]; then
  echo "Error: Could not retrieve API Service URL. Ensure api-service deployed correctly."
  exit 1
fi
```

Now, deploy the `frontend-service`, providing the API URL as an environment variable:

```bash
# Use variables set in the previous step (GCP_PROJECT, CLOUD_RUN_REGION, etc.)
# --- Optional Variables ---
export FRONTEND_MEMORY="1Gi"

gcloud run deploy frontend-service \
  --project=$GCP_PROJECT \
  --region=$CLOUD_RUN_REGION \
  --image="${AR_REGION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}/frontend-service:latest" \
  --platform=managed \
  --memory=$FRONTEND_MEMORY \
  --allow-unauthenticated \
  --update-env-vars="API_HOST_URL=${API_SERVICE_URL}"
  # Optional: Specify service account if needed
  # --service-account=$SERVICE_ACCOUNT_EMAIL
```

## API Endpoints

The `api-service` exposes the following endpoints:

### GET `/health`

- **Description:** Basic health check endpoint.
- **Response (200 OK):**
  ```json
  {
    "status": "healthy"
  }
  ```

### POST `/recommend`

- **Description:** Accepts a query (job description, question, or URL) and returns recommended SHL assessments based on the RAG pipeline.
- **Request Body:**
  ```json
  {
    "query": "Looking for assessments for mid-level Python developers proficient in SQL and JavaScript, max duration 60 minutes."
  }
  ```
  _(The query can also be a URL like "https://jobs.lever.co/...")_
- **Response Body (200 OK):**
  ```json
  {
    "recommended_assessments": [
      {
        "url": "https://www.shl.com/solutions/products/product-catalog/view/python-new/",
        "adaptive_support": "No",
        "description": "Multi-choice test that measures the knowledge of Python programming, databases, modules and library. For developers.",
        "duration": 11,
        "remote_support": "Yes",
        "test_type": ["Knowledge & Skills", "Technology"]
      },
      {
        "url": "https://www.shl.com/solutions/products/product-catalog/view/javascript-test/",
        "adaptive_support": "No",
        "description": "Measures knowledge of JavaScript programming concepts, suitable for web developers.",
        "duration": 20,
        "remote_support": "Yes",
        "test_type": ["Knowledge & Skills", "Technology"]
      }
      // ... more recommendations (max 10)
    ]
  }
  ```
- **Response Body (Error):** Returns appropriate HTTP status codes (e.g., 500) with a JSON detail message on errors.

### POST `/recommend_raw` (Optional)

- **Description:** Same as `/recommend` but returns the raw dictionary output from the RAG pipeline without strict Pydantic validation on the response structure. Useful for debugging.

## Important Notes

- **Cold Starts:** Cloud Run services (especially the API service which loads models and connects to the DB) can experience "cold starts" if they haven't received traffic recently. The initial request after a period of inactivity might take significantly longer (up to 30-60 seconds or more depending on model size and complexity). If the application seems unresponsive initially, please wait a minute and refresh. Subsequent requests should be much faster. Consider configuring minimum instances in Cloud Run if consistent low latency is critical.
- **Data Freshness:** The recommendations are based on the data scraped and embedded in the vector store. The included scripts (`collect_data.py`, `add_links.py`, etc.) can be used to refresh this data, followed by running `create_store_embeddings.py` again.
- **Fine-Tuning:** The quality of recommendations depends heavily on the quality of the embedded data and the fine-tuned Sentence Transformer model. The included fine-tuning scripts are optional but recommended for optimal performance.
- **Costs:** Running services on Google Cloud (Cloud Run, Cloud SQL, Cloud Build, Secret Manager, Gemini API, etc.) incurs costs. Be sure to monitor your usage and set budgets if necessary. Shut down resources when not in use.

## Project Structure

```
.
├── .gcloudignore             # Files ignored by gcloud deployments
├── .gitignore                # Files ignored by git
├── data/                     # (Optional) Raw scraped data (CSVs)
├── debug_*_pages/            # (Optional) HTML debug files from scrapers
├── pdfs_individual/          # (Optional) Downloaded PDF files from scraper
├── shl_finetuned_..._model/  # Fine-tuned Sentence Transformer model files
├── src/                      # Main application source code
│   ├── __init__.py
│   ├── api.py                # FastAPI application logic and endpoints
│   ├── app.py                # Streamlit frontend application logic
│   ├── config.py             # Configuration loading (env vars)
│   ├── prompt_templates.py   # Prompts for the Gemini LLM
│   ├── rag_pipeline.py       # Core RAG logic orchestrating retrieval and generation
│   ├── retriever.py          # Handles embedding generation and DB interaction (pgvector)
│   └── web_utils.py          # Utility for fetching/extracting text from URLs
├── cloudbuild-api.yaml       # Cloud Build config for API service image
├── cloudbuild-frontend.yaml  # Cloud Build config for Frontend service image
├── create_store_embeddings.py # Script to generate and store embeddings in DB
├── Dockerfile.api            # Dockerfile for the API service
├── Dockerfile.frontend       # Dockerfile for the Frontend service
├── finetune_embedder.py      # (Optional) Script to fine-tune the embedding model
├── generate_synthetic_triplets.py # (Optional) Script to generate data for fine-tuning
├── requirements.txt          # Python dependencies
├── *.py                      # Other helper/data preparation scripts (scraping, merging)
├── *.csv                     # Intermediate or final data files from prep scripts
├── *.jsonl                   # Processed data chunks and triplet files
└── README.md                 # This file
```
