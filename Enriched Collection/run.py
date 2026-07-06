import pandas as pd
import time
import io
import os
from io import StringIO
from datetime import datetime, timedelta
from google.cloud import secretmanager
from google.cloud import bigquery
from google.cloud import storage
from search_siren import get_siren_info_by_api
from full_enrich import start_enrichment
from database import save_to_bigquery

# =========================
# ENV VARIABLES (CLOUD SAFE)
# =========================

project_id = os.getenv("PROJECT_ID")
dataset_id = os.getenv("DATASET_ID")
table_id = os.getenv("TABLE_ID_Paris")

bucket_name = os.getenv("BUCKET_NAME_SIRENS")
blob_sirens = os.getenv("BLOB_SIREN")
blob_enrich = os.getenv("BLOB_ENRICH")


# -----------------------------
# SECRET MANAGER
# -----------------------------
def get_secret(secret_name: str):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


# Load secrets ONCE
full_enrich_api_key = None

def init_secrets():
    global  full_enrich_api_key
    full_enrich_api_key = get_secret("FULL_ENRICH_API_KEY")
# =========================
# CONSTANTS
# =========================

effectif_dict = {
    "NN": "Unités non employeuses",
    "00": "0 salarié",
    "01": "1 à 2 salariés",
    "02": "3 à 5 salariés",
    "03": "6 à 9 salariés",
    "11": "10 à 19 salariés",
    "12": "20 à 49 salariés",
    "21": "50 à 99 salariés",
    "22": "100 à 199 salariés",
    "31": "200 à 249 salariés",
    "32": "250 à 499 salariés",
    "41": "500 à 999 salariés",
    "42": "1000 à 1999 salariés",
    "51": "2000 à 4999 salariés",
    "52": "5000 à 9999 salariés",
    "53": "10000+"
}

# =========================
# READ NAF
# =========================
def load_naf_reference(csv_path: str):
    """
    Load NAF 2025 reference file and keep only:
    - activite_principale_naf25
    - libelle_activite_principale_naf25

    Both columns are forced to string type.
    """

    df = pd.read_csv(csv_path, sep=",", encoding="latin1")
    # Force string type + clean values
    df["naf_code"] = (
        df["naf_code"]
        .astype(str)
        .str.strip()
    )
    # Remove invalid rows if any
    df = df.dropna()
    naf_dict = dict(zip(
    df["naf_code"],
    df["naf_label"]
))

    print('naf_dict fetched' )
    return naf_dict

# =========================
# BIGQUERY READ
# =========================

def read_from_bigquery(project_id, dataset_id, table_id):
    client = bigquery.Client()

    query = f"""
        SELECT *
        FROM `{project_id}.{dataset_id}.{table_id}`
        Where processed = 0  and source_folder = "IDCC 2332" AND CAST(code_postal AS STRING) LIKE '75%' 
        LIMIT 25
    """


    df = client.query(query).to_dataframe()
    return df, client


# =========================
# UPDATE FLAGS
# =========================

def update_bigquery_flags(client, project_id, dataset_id, table_id, sirens):
    if not sirens:
        return

    siren_list = ",".join([f"'{s}'" for s in sirens])

    query = f"""
        UPDATE `{project_id}.{dataset_id}.{table_id}`
        SET processed = 1,
            processed_date = CURRENT_DATETIME()
        WHERE CAST(siren AS STRING) IN ({siren_list})
    """

    job = client.query(query)
    job.result()

    print(f"✅ Updated {len(sirens)} rows")

# =========================
# Save in BUCKET SIRENS AND ENRICHED
# =========================
def save_processed_sirens_to_gcs(df, bucket_name, blob):
    """
    Save processed SIRENs as a CSV file in GCS.

    Args:
        processed_sirens (list): List of SIREN values.
        bucket_name (str): GCS bucket name.
    """

    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)

    # Timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Upload to GCS
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    blob = bucket.blob(
        f"{blob}/siren_{timestamp}.csv"
    )

    blob.upload_from_string(
        csv_buffer.getvalue(),
        content_type="text/csv"
    )

    print(
        f"✅ Uploaded gs://{bucket_name}/{blob}/siren_{timestamp}.csv"
    )
# =========================
# GCS SAVE CSV
# =========================

def save_csv_to_gcs(df, bucket_name, folder):
    buffer = StringIO()
    df.to_csv(buffer, index=False)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    blob = bucket.blob(f"{folder}/file_{ts}.csv")

    blob.upload_from_string(buffer.getvalue(), content_type="text/csv")

    print(f"✅ Saved gs://{bucket_name}/{folder}/file_{ts}.csv")


# =========================
# MAIN PROCESSING
# =========================

def process_daily_batch(project_id, dataset_id, table_id, bucket_name, naf_dict, effectif_dict, batch_size=30):

    print("🔗 Reading BigQuery...")
    df, bq_client = read_from_bigquery(project_id, dataset_id, table_id)
    print(len(df))

    unprocessed = df[df["processed"] == 0]

    if unprocessed.empty:
        return {"status": "done", "message": "No data left"}

    batch = unprocessed.head(batch_size)

    results = []
    processed_sirens = []

    for _, row in batch.iterrows():

        siren = str(row["siren"])
        nom = row.get("nom", "")
        ville = row.get("ville", "")
        code_postal = row.get("code_postal", "")
        idcc= row.get("source_folder","")

        try:
            dirs, etab = get_siren_info_by_api(siren)

            denomination = etab.get("Dénomination", "")
            adresse = etab.get("Adresse postale", "")
            code_naf = etab.get("Activité principale (NAF/APE)", "")
            activity_principal = etab.get("Code NAF 2025", "")
            activity_type = naf_dict.get(activity_principal, "UNKNOWN")
            tranche = etab.get("Effectif salarié","") 
            effectif_salary = effectif_dict.get(tranche, "UNKNOWN") 
            company_taille = etab.get("Taille de la structure", "")

            if dirs:
                for d in dirs:
                    results.append({
                        "siren": siren,
                        "company_name": nom,
                        "denomination":denomination,
                        "IDCC": idcc,
                        "ville": ville,
                        "code_postal": code_postal,
                        "adresse": adresse,
                        "code_naf": code_naf,
                        "effectif_salary": effectif_salary,
                        "activity_type": activity_type,
                        "clef_NIC": "",
                        "company_taille": company_taille,
                        "role": d.get("qualite",""),
                        "details": "",
                        "dir_name":d.get("prenoms",""),
                        "dir_lname": d.get("nom",""),
                        "status": "success",
                        "processed_date": datetime.utcnow(), 
                    })
            else:
                results.append({
                    "siren": siren,
                    "company_name": nom,
                    "denomination" :denomination,
                    "IDCC": idcc,
                    "ville": ville,
                    "code_postal": code_postal,
                    "adresse": adresse,
                    "code_naf": code_naf,
                    "effectif_salary": tranche,
                    "activity_type": activity_type,
                    "clef_NIC": "",
                    "company_taille": company_taille,
                    "role": "",
                    "details": "",
                    "dir_name": "",
                    "dir_lname": "",
                    "processed_date":datetime.utcnow() , 
                    "status": "no_dirigeants"
                })

            processed_sirens.append(siren)

        except Exception as e:
            print(f"❌ Error with SIREN :{siren}: {e}")

            '''results.append({
                "siren": siren,
                "status": "error",
                "error": str(e),
                "processed_date": datetime.utcnow()
            })

            processed_sirens.append(siren)'''

    # =========================
    # SAVE + UPDATE
    # =========================
    # Update flags in BigQuery
    print(f"✏️ Updating BigQuery flags...")
    update_bigquery_flags(bq_client, project_id, dataset_id, table_id, processed_sirens)
    processed_siren = pd.DataFrame(processed_sirens)
    save_processed_sirens_to_gcs(processed_siren,bucket_name,blob_sirens)
    # Save results to Cloud Storage as Excel file
    results_df = pd.DataFrame(results)
    save_processed_sirens_to_gcs(results_df,bucket_name,blob_enrich)
    print(results_df.head())
    init_secrets()

    full_enrich = start_enrichment(results_df,full_enrich_api_key)
    print(full_enrich)
    print(df.shape)
    # Select only SIREN and enrichment_id from full_enrich
    full_enrich_subset = full_enrich[["siren","dir_name", "dir_lname","flag","enrichment_id"]]
    combined_df = results_df.merge(
    full_enrich_subset,
    on=["siren", "dir_name", "dir_lname"],
    how="left",
)
    print(combined_df.head())
    filtered_df = combined_df[combined_df["enrichment_id"].notnull()]
    print(filtered_df.head())

    # Save only filtered data to BigQuery
    if not filtered_df.empty:
        save_to_bigquery(filtered_df)
    else:
        print("⚠️ No valid enrichment_id found. Skipping save.")


# =========================
# CLOUD FUNCTION ENTRYPOINT
# =========================

def daily_scraper(request):

    try:
        request_json = request.get_json(silent=True) or {}
        naf_dict = load_naf_reference("NAF2025.csv")


        result = process_daily_batch(
            project_id=project_id,
            dataset_id=dataset_id,
            table_id=table_id,
            bucket_name=bucket_name,
            naf_dict= naf_dict,
            effectif_dict=effectif_dict,
            batch_size=25
        )

        return result, 200

    except Exception as e:
        return {"status": "error", "message": str(e)}, 500