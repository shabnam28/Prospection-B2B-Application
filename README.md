# Prospection-B2B-Application
Serverless Google Cloud pipeline that scrapes French companies by IDCC, enriches company data via MCP API, retrieves verified contacts with FullEnrich, and stores results in Google Cloud Storage and BigQuery.
## Architecture

<img src="./assets/OPCO-FLOW-Prospection B2B.drawio.svg" alt="Architecture Diagram" width="700"/>

## 1. Pahase 1: RubyPayeur IDCC Scraper
A serverless pipeline that scrapes French company's siren data from [rubypayeur.com](https://rubypayeur.com) and stores it in Google Cloud Storage and BigQuery.

---

##  1.1 Overview

Given an **IDCC code** (French collective labor agreement identifier), this tool:
1. Scrapes company data across all **Île-de-France** regions 
2. Saves one **CSV per region** + one **combined CSV** to Google Cloud Storage
3. **Appends** the combined data to a BigQuery table

---

##  1.2 Project Structure

```
├── Siren Collection/ scrapper.py        # Scraper logic
├── requirements.txt         # Python dependencies
├── serviceaccountkey.json   # GSC Connection Configuration
└── .env               # Local config (never commit this)
```

## 1.3 Google Cloud Setup

### 1.3.1 Enable APIs
```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com
```

### 1.3.2. Create GCS Bucket
```bash
gsutil mb -l europe-west1 gs://'YourBucketName'
```

### 1.3.3. Create BigQuery Dataset and Table
```bash
bq mk --dataset your-project-id:"YourDatasetName"

bq mk --table your-project-id:'YourDatasetName'.YourTableName \
  siren:INTEGER,nom:STRING,ville:STRING,\
  code_postal:INTEGER,processed:INTEGER,\
  source_folder:STRING,processed_date:DATETIME
```
### 1.3.4. Create Service Account
```bash
# Download key for local dev
gcloud iam service-accounts keys create your-service-account.json \
  --iam-account=scraper-sa@your-project-id.iam.gserviceaccount.com
```
---

##  1.4 How to Run

### 1.4.1 Locally
```bash
pip install -r requirements.txt
define NEW IDCC in scraper = RubyPayeurScraper(idcc="0759") AND def __init__(self, idcc: str = "0759"):
complete .env variables and add service account key as json file
python scrapper.py
```
##  1.5 Output

### 1.5.1 Google Cloud Storage
Files saved under `gs://YourBucketName/YourBucketFolerName/IDCC {idcc}/`:
- `entreprises_rubypayeur_idcc_{idcc}_{region}.csv` — one per region
- `entreprises_rubypayeur_idcc_{idcc}_ALL_REGIONS.csv` — combined
### 1.5.2 Local Run Output
"message": "Total global: {len(entreprises)} entreprises"

### 1.5.3 BigQuery Table — `YourDatasetName.YourTableName`

| Field | Type | Description |
|-------|------|-------------|
| `siren` | INTEGER | Company identifier |
| `nom` | STRING | Company name |
| `ville` | STRING | City |
| `code_postal` | INTEGER | Postal code |
| `processed` | INTEGER | `0` = not processed yet |
| `source_folder` | STRING | e.g. `IDCC 3223` |
| `processed_date` | DATETIME | `NULL` until processed |

---
##  1.6 Tech Stack

| Tool | Purpose |
|------|---------|
| Python | Scraping with 
| Google Cloud Storage | CSV file storage |
| Google BigQuery | Data warehouse |

---

##  1.7 Notes

- Running the scraper twice for the same IDCC will create **duplicate rows** in BigQuery
- `.env` file should **never be committed** to GitHub — add it to `.gitignore`

# 2. Phase 2: SIREN Enrichment Pipeline

A serverless batch pipeline that reads unprocessed companies from BigQuery, enriches them with company and director data, then finds professional contacts via the FullEnrich API.


##  2.1 Overview

For each unprocessed SIREN in BigQuery, this pipeline:
1. Reads a **scheduled batch** of unprocessed companies from BigQuery
2. Calls the **French Government SIREN API** to get company details with their dirigeants
3. Sends director data to **FullEnrich API** to find work emails & phones
4. Saves enriched results back to **BigQuery** and **GCS**
5. Marks processed records (`processed = 1`)

---

##  2.2 Project Structure

```
├── run.py               # Cloud Function entry point + batch orchestration
├── main.py              # Cloud Function entry point + batch orchestration
├── search_siren.py      # French Gov SIREN API calls
├── full_enrich.py       # FullEnrich API for contact enrichment
├── database.py          # BigQuery save helper
├── NAF2025.csv          # NAF activity code reference file
├── requirements.txt     # Python dependencies
└── .env                 # Local config (never commit this)
```
---

##  2.3 Flow Diagram

```
HTTP Request / Cloud Scheduler
          │
          ▼
  daily_scraper()          ← Cloud Function entry point
          │
          ▼
  read_from_bigquery()
  → SELECT * WHERE processed = 0 where source_foulder= "IDCC 1678" limit 50
          ▼
  For each SIREN in batch:
  │
  ├── search_siren.py
  │   └── get_siren_info_by_api()
  │       → denomination, address, NAF code,
  │         effectif,Activité principale (NAF/APE), directors list, etc
  │
  ├── NAF2025.csv lookup   → activity label
  ├── effectif_dict lookup → employee range label
  │
  └── full_enrich.py
      └── start_enrichment()
          → skip rules (commissaire, small companies)
          → POST to FullEnrich API
          → returns enrichment_id per director
          │
          ▼
  update_bigquery_flags()
  → SET processed = 1, processed_date = NOW()
          │
          ├── GCS: processed SIRENs CSV
          ├── GCS: enriched results CSV
          └── BigQuery: save_to_bigquery()
              → only rows WITH valid enrichment_id
```
---

## 2.4 Input

### BigQuery Table (`YourTableName`)
Records where `processed = 0` are picked up automatically from Siren list:

| Field | Type | Description |
|-------|------|-------------|
| `siren` | INTEGER | Company identifier |
| `nom` | STRING | Company name |
| `ville` | STRING | City |
| `code_postal` | INTEGER | Postal code |
| `processed` | INTEGER | `0` = not processed |
| `source_folder` | STRING | e.g. `IDCC 1486` |
| `processed_date` | DATETIME | `NULL` until processed |

### 2.4.1 HTTP Request
```json
POST /hello-http
Content-Type: application/json

{
  "project_id": "YourProjectName",
  "dataset_id": "YourDatasetName",
  "table_id": "YourTableName",
  "bucket_name": "YourBucketName",
  "batch_size": 25 or 50
}
```
---
## 2.5  Output

### 2.5.1 BigQuery — `YourEnricheTable` Table

| Field | Type | Description |
|-------|------|-------------|
| `siren` | STRING | Company SIREN |
| `company_name` | STRING | Company name |
| `denomination` | STRING | Legal denomination |
| `IDCC` | STRING | Source IDCC folder |
| `ville` | STRING | City |
| `code_postal` | INTEGER | Postal code |
| `adresse` | STRING | Full address |
| `code_naf` | STRING | NAF/APE code |
| `effectif_salary` | STRING | e.g. `10 à 19 salariés` |
| `activity_type` | STRING | NAF label |
| `clef_NIC` | STRING | Collective agreement key |
| `company_taille` | STRING | Company size category |
| `role` | STRING | Director role |
| `dir_name` | STRING | Director last name |
| `dir_lname` | STRING | Director first name |
| `enrichment_id` | STRING | FullEnrich reference ID |
| `flag` | BOOLEAN | Enrichment flag |`0` = not processed by default
| `processed_date` | TIMESTAMP | Processing timestamp |
| `status` | STRING | `success` / `no_dirigeants` |

### 2.5.2. Google Cloud Storage

| Path | Content |
|------|---------|
| `gs://YourBucketName/Processed SIRENS Folder/siren_{timestamp}.csv` | List of processed SIRENs |
| `gs://YourBucketName/Enriched results Folder/enriched_{timestamp}.csv` | Full enriched results |

---

## 2.6 Module Details

### 2.6.1 `main.py` — Cloud Function Entry Point
Receives the HTTP request and delegates to `daily_scraper()` in `run.py`:

```python
@functions_framework.http
def hello_http(request):
    return daily_scraper(request)
```

---

### 2.6.2`run.py` — Batch Orchestration
Coordinates the full pipeline:
- Reads unprocessed SIRENs from BigQuery
- Calls SIREN API + FullEnrich for each record
- Updates BigQuery flags
- Saves results to GCS and BigQuery

---

### 2.6.3 `search_siren.py` — SIREN API
Calls the French Government API:
```
GET https://recherche-entreprises.api.gouv.fr/search?q={siren}
```

Returns per company:

| Field | Description |
|-------|-------------|
| `Dénomination` | Legal company name |
| `Adresse postale` | Full address |
| `Activité principale (NAF/APE)` | NAF code |
| `Code NAF 2025` | Updated NAF 2025 code |
| `Effectif salarié` | Employee range code |
| `Taille de la structure` | Company size |
| `Convention(s) collective(s)` | IDCC list |
| `dirigeants` | List of directors with name and role |

---

### 2.6.4 `full_enrich.py` — Contact Enrichment
Calls FullEnrich bulk API:
```
POST https://app.fullenrich.com/api/v2/contact/enrich/bulk
```

**Skip rules** — directors are automatically skipped if:
- Role starts with `COMMISSAIRE` or `AUTRE`
- First name or last name is empty
- Company has 0–2 employees (`effectif` starts with `0`, `1 à 2`, or `Unités`)

Returns `enrichment_id` per director for later email/phone retrieval.

---

### 2.6.5 `database.py` — BigQuery Save
- **Auto-creates** the `YourEnrichedTable` table if it does not exist
- Uses `WRITE_APPEND` — never overwrites existing data
- Only saves rows that have a valid `enrichment_id`

---

### 2.6.6 `NAF2025.csv` — Activity Reference
Maps NAF codes to French activity labels:
```csv
naf_code,naf_label
62.02A,Conseil en systèmes et logiciels informatiques
```
---

##  2.7 How to Run phase 2

### 2.7.1 Via Postman (deployed function)

| | |
|---|---|
| **Method** | `POST` |
| **URL** | `https://europe-your-project.cloudfunctions.net/hello-http` |
| **Header** | `Content-Type: application/json` |
---

### 2.7.2 Via Scheduled Job Run 
  |**Define to run a function for which source_folder** | SELECT * FROM `{project_id}.{dataset_id}.{table_id}`
                                                          Where processed = 0  and source_folder = "IDCC 2332" AND CAST(code_postal AS STRING) LIKE                                                             '75%'LIMIT 25
---

##  2.8 Google Cloud Setup Configuration

### 2.8.1 Step 1 — Enable APIs
```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com
```

### 2.8.2 Step 2 — Create Service Account
```bash
# Download key for local dev only
gcloud iam service-accounts keys create your-service-account.json \
```

### 2.8.3 Step 3 — Deploy Cloud Function
```bash
gcloud functions deploy hello-http 
```

###  2.8.4 Step 4 — Schedule Daily Run (optional)
```bash
create schedule run Function
  --schedule="0 8 * * *" \
  --uri="https://europe-your-project.cloudfunctions.net/hello-http" \
```
---

##  2.9 Tech Stack

| Tool | Purpose |
|------|---------|
| Python | Batch processing |
| French Gov SIREN API | Company + director data |
| FullEnrich API | Work email & phone enrichment |
| Google Cloud Functions | Serverless HTTP trigger |
| Google Cloud Storage | CSV result storage |
| Google BigQuery | Input data + enriched output |
| Cloud Scheduler | Daily automatic trigger |
---

## 2.10 : Phase  2- Notes

- Default **batch size is 25-50** per run — tune via `batch_size` parameter
- Only rows with a valid `enrichment_id` are saved to BigQuery
- Directors from small companies (0–2 employees) are **skipped** automatically
- Records that fail the SIREN API call are **skipped silently** (logged as warnings)
- `.env` and `*.json` key files should **never be committed** to GitHub

# 3 Contact Collection Pipeline
 
A serverless Cloud Function that retrieves enriched contact data (emails, phones)
and company websites for previously enriched directors, then stores the results in BigQuery.
 
---
 
## 3.1 Overview
For each enriched director in BigQuery (`flag = false`), this function:
1. Calls **FullEnrich API** to retrieve emails and phone numbers
2. Calls **Google Maps Places API** to find the company website
3. Saves contact results to a new BigQuery table (`OPCO_CONTACTS`)
4. Updates the `flag = TRUE` on processed records

## 3.2 Project Structure
 
```
Contact Collection/
├── main.py              # Cloud Function entry point + full logic
├── requirements.txt     # Python dependencies
└── .env                 # Local config (never commit this)
```
## 3.3 Configuration
 
### 3.3.1 Environment Variables
Set these in GCP Cloud Function environment or `.env` for local dev:
 
```env
GOOGLE_APPLICATION_CREDENTIALS=your-service-account.json
PROJECT_ID=YOUR_PROJECT_ID
DATASET_ID=YOUR_DATASET
TABLE_ENRICH=YOUR_ENRICH_TABLE
TABLE_CONTACTS=YOUR_CONTACTS_TABLE
```
 
### 3.3.2 Secret Manager
The following secrets must be created in **GCP Secret Manager**:
 
| Secret Name | Description |
|-------------|-------------|
| `GOOGLE_MAPS_API_KEY` | Google Maps Places API key |
| `FULL_ENRICH_API_KEY` | FullEnrich API key |
 
---

## 3.4 Flow Diagram
 
```
HTTP Request
     │
     ▼
hello_http()
     │
     ├── init_secrets()
     │   └── Load GOOGLE_MAPS_API_KEY + FULL_ENRICH_API_KEY
     │       from GCP Secret Manager
     │
     ▼
process_enrichment()
     │
     ▼
BigQuery: SELECT * FROM YOUR_ENRICH_TABLE
WHERE flag = false AND IDCC = 'IDCC 1147'
LIMIT 20
     │
     ▼
For each row:
     │
     ├── get_enrichment_data(enrichment_id)
     │   └── GET FullEnrich API
     │       → emails, phones, regions
     │
     └── get_company_website(company_name)
         └── GET Google Maps Places API
             → place_id → website URL
     │
     ▼
INSERT results INTO YOUR_CONTACTS_TABLE (BigQuery)
     │
     ▼
UPDATE YOUR_ENRICH_TABLE
SET flag = TRUE
WHERE enrichment_id IN (processed_ids)
```
 
---
 
## 3.5 Input
 
### 3.5.1 BigQuery Table — `YOUR_ENRICH_TABLE`
Records where `flag = false` are picked up:
 
| Field | Type | Description |
|-------|------|-------------|
| `siren` | STRING | Company SIREN |
| `company_name` | STRING | Company name |
| `denomination` | STRING | Legal denomination |
| `IDCC` | STRING | Source IDCC folder |
| `ville` | STRING | City |
| `code_postal` | INTEGER | Postal code |
| `adresse` | STRING | Full address |
| `code_naf` | STRING | NAF/APE code |
| `effectif_salary` | STRING | e.g. `10 à 19 salariés` |
| `activity_type` | STRING | NAF label |
| `clef_NIC` | STRING | Collective agreement key |
| `company_taille` | STRING | Company size category |
| `role` | STRING | Director role |
| `dir_name` | STRING | Director last name |
| `dir_lname` | STRING | Director first name |
| `enrichment_id` | STRING | FullEnrich reference ID |
| `flag` | BOOLEAN | Enrichment flag |`0` = not processed by default
| `processed_date` | TIMESTAMP | Processing timestamp |
| `status` | STRING | `success` / `no_dirigeants` |
 
### 3.5.2 HTTP Request
No body required — the function runs automatically on trigger:
```json
POST /hello-http
```
 
Or with optional parameters if extended:
```json
{
  "idcc": "IDCC 1147",
  "batch_size": 20
}
```
---
 
## 3.6 Output

### 3.6.1 BigQuery Table — `YOUR_CONTACTS_TABLE`
 
| Field | Type | Description |
|-------|------|-------------|
| `enrichment_id` | STRING | FullEnrich reference ID |
| `siren` | STRING | Company SIREN |
| `processed_date` | TIMESTAMP | Original enrichment date |
| `emails` | STRING | Comma-separated work emails |
| `phones` | STRING | Comma-separated phone numbers |
| `regions` | STRING | Comma-separated phone regions |
| `website_link` | STRING | Company website URL |
| `inserted_date` | TIMESTAMP | When this record was inserted |
 
### 3.6.2 BigQuery Flag Update
```sql
UPDATE CV.OPCO_ENRICH
SET flag = TRUE
WHERE enrichment_id IN (processed_ids)
```
---
## 3.7 Module Details
 
### 3.7.1 `hello_http()` — Entry Point
- Initializes secrets from GCP Secret Manager
- Calls `process_enrichment()`
- Returns success/error response
  
### 3.7.2 `init_secrets()` — Secret Loader
Loads API keys **once per function execution** from GCP Secret Manager:
- `GOOGLE_MAPS_API_KEY`
- `FULL_ENRICH_API_KEY`
  
### 3.7.3 `get_enrichment_data()` — FullEnrich API
```
GET https://app.fullenrich.com/api/v2/contact/enrich/bulk/{enrichment_id}
```
Returns:
- `emails` — most probable work email
- `phones` — list of phone numbers
- `regions` — phone number regions

### 3.7.4 `get_company_website()` — Google Maps API
Two-step call:
```
# Step 1 — Find place
GET https://maps.googleapis.com/maps/api/place/textsearch/json?query={company_name}
 
# Step 2 — Get website
GET https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=website
```
**Stops the job** if API returns `REQUEST_DENIED` or `OVER_QUERY_LIMIT`.

## 3.8 How to Run
 
### 3.8.1 Locally
```bash
pip install -r requirements.txt
python main.py
```
 
### 3.8.2 Via Postman (deployed function)
 
| | |
|---|---|
| **Method** | `POST` |
| **URL** | `https://europe-west1-your-project.cloudfunctions.net/hello-http` |
| **Header** | `Content-Type: application/json` |
| **Body** | *(empty or `{}`)* |
 
---

## 3.9 Google Cloud Setup
 
### 3.9.1 — Enable APIs
```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  bigquery.googleapis.com \
  secretmanager.googleapis.com \
  places-backend.googleapis.com
```
 
### Step 3.9.2 — Create Secrets
```bash
echo -n "your-google-maps-key" | \
  gcloud secrets create GOOGLE_MAPS_API_KEY --data-file=-
 
echo -n "your-fullenrich-key" | \
  gcloud secrets create FULL_ENRICH_API_KEY --data-file=-
```
 
### Step 3.9.3 — Grant Secret Access to Service Account
```bash
gcloud secrets add-iam-policy-binding GOOGLE_MAPS_API_KEY \
  --member="serviceAccount:your-sa@your-project.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
 
gcloud secrets add-iam-policy-binding FULL_ENRICH_API_KEY \
  --member="serviceAccount:your-sa@your-project.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```
 
### Step 3.9.4 — Deploy Cloud Function
```bash
gcloud functions deploy hello-http \
  --gen2 \
  --runtime python311 \
  --trigger-http \
  --entry-point hello_http \
  --region europe-west1 \
  --timeout 3600 \
  --memory 512MB \
  --allow-unauthenticated \
  --set-env-vars \
    PROJECT_ID=your-project-id,\
    DATASET_ID=CV,\
    TABLE_OPCO_ENRICH=OPCO_ENRICH,\
    TABLE_OPCO_CONTACTS=OPCO_CONTACTS
```
 
### Step 3.9.5 — Schedule Daily Run (optional)
```bash
gcloud scheduler jobs create http contact-collection \
  --schedule="0 9 * * *" \
  --uri="https://europe-west1-your-project.cloudfunctions.net/hello-http" \
  --time-zone="Europe/Paris"
```
 
---
 
## 3.10 Requirements
 
```
functions-framework==3.*
requests
pandas
google-cloud-bigquery
google-cloud-secret-manager
db-dtypes
```
 
---
 
## 3.11 Tech Stack
 
| Tool | Purpose |
|------|---------|
| Python | Processing logic |
| FullEnrich API | Retrieve emails & phones |
| Google Maps Places API | Find company website |
| Google Cloud Functions | Serverless HTTP trigger |
| Google BigQuery | Input + output data store |
| GCP Secret Manager | Secure API key storage |
| Cloud Scheduler | Daily automatic trigger |
 
---
 
## 3.12 Notes

- **Batch size is hardcoded to 20** — change `LIMIT 20` in the query to adjust
- If Google Maps API returns `OVER_QUERY_LIMIT` → the job **stops immediately** to avoid extra charges
- **IDCC filter is hardcoded** (`IDCC 1147`) in the query — make it dynamic if needed
- API keys are loaded from **Secret Manager**, never from `.env` in production
- `.env` and `*.json` files should **never be committed** to GitHub
```gitignore
# .gitignore
.env
*.json
__pycache__/
```
