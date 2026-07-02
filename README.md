# Prospection-B2B-Application
Serverless Google Cloud pipeline that scrapes French companies by IDCC, enriches company data via MCP API, retrieves verified contacts with FullEnrich, and stores results in Google Cloud Storage and BigQuery.

## Pahase 1: RubyPayeur IDCC Scraper
A serverless pipeline that scrapes French company's siren data from [rubypayeur.com](https://rubypayeur.com) and stores it in Google Cloud Storage and BigQuery.

---

##  Overview

Given an **IDCC code** (French collective labor agreement identifier), this tool:
1. Scrapes company data across all **Île-de-France** regions 
2. Saves one **CSV per region** + one **combined CSV** to Google Cloud Storage
3. **Appends** the combined data to a BigQuery table

---

##  Project Structure

```
├── Siren Collection/ scrapper.py        # Scraper logic
├── requirements.txt         # Python dependencies
├── serviceaccountkey.json   # GSC Connection Configuration
└── .env               # Local config (never commit this)
```

## ☁️ Google Cloud Setup

### 1. Enable APIs
```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com
```

### 2. Create GCS Bucket
```bash
gsutil mb -l europe-west1 gs://'YourBucketName'
```

### 3. Create BigQuery Dataset and Table
```bash
bq mk --dataset your-project-id:"YourDatasetName"

bq mk --table your-project-id:'YourDatasetName'.YourTableName \
  siren:INTEGER,nom:STRING,ville:STRING,\
  code_postal:INTEGER,processed:INTEGER,\
  source_folder:STRING,processed_date:DATETIME
```
### 4. Create Service Account
```bash
# Download key for local dev
gcloud iam service-accounts keys create your-service-account.json \
  --iam-account=scraper-sa@your-project-id.iam.gserviceaccount.com
```
---

##  How to Run

### Locally
```bash
pip install -r requirements.txt
define NEW IDCC in scraper = RubyPayeurScraper(idcc="0759") AND def __init__(self, idcc: str = "0759"):
complete .env variables and add service account key as json file
python scrapper.py
```
##  Output

### Google Cloud Storage
Files saved under `gs://YourBucketName/YourBucketFolerName/IDCC {idcc}/`:
- `entreprises_rubypayeur_idcc_{idcc}_{region}.csv` — one per region
- `entreprises_rubypayeur_idcc_{idcc}_ALL_REGIONS.csv` — combined
### Local Run Output
"message": "Total global: {len(entreprises)} entreprises"

### BigQuery Table — `YourDatasetName.YourTableName`

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
##  Tech Stack

| Tool | Purpose |
|------|---------|
| Python | Scraping with 
| Google Cloud Storage | CSV file storage |
| Google BigQuery | Data warehouse |

---

##  Notes

- Running the scraper twice for the same IDCC will create **duplicate rows** in BigQuery
- `.env` file should **never be committed** to GitHub — add it to `.gitignore`

#  SIREN Enrichment Pipeline

A serverless batch pipeline that reads unprocessed companies from BigQuery, enriches them with company and director data, then finds professional contacts via the FullEnrich API.


##  Overview

For each unprocessed SIREN in BigQuery, this pipeline:
1. Reads a **scheduled batch** of unprocessed companies from BigQuery
2. Calls the **French Government SIREN API** to get company details with their dirigeants
3. Sends director data to **FullEnrich API** to find work emails & phones
4. Saves enriched results back to **BigQuery** and **GCS**
5. Marks processed records (`processed = 1`)

---

##  Project Structure

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

##  Flow Diagram

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

## Input

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

### HTTP Request
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
