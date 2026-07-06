from google.cloud import bigquery
from google.cloud import secretmanager
import requests
import pandas as pd
import os
from datetime import datetime

# -----------------------------
# ENV VARIABLES (CONFIG)
# -----------------------------
project_id = os.getenv("PROJECT_ID")
dataset_id = os.getenv("DATASET_ID")
table_enrich = os.getenv("TABLE_OPCO_ENRICH")
table_contact = os.getenv("TABLE_OPCO_CONTACTS")

bq_client = bigquery.Client()

# -----------------------------
# SECRET MANAGER
# -----------------------------
def get_secret(secret_name: str):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


# Load secrets ONCE
google_api = None
full_enrich_api_key = None

def init_secrets():
    global google_api, full_enrich_api_key
    google_api = get_secret("GOOGLE_MAPS_API_KEY")
    full_enrich_api_key = get_secret("FULL_ENRICH_API_KEY")
   


# -----------------------------
# GOOGLE MAPS WEBSITE FETCH
# -----------------------------
def get_company_website(company_name: str):
    try:
        query = company_name.replace(" ", "+")
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={query}&key={google_api}"

        response = requests.get(url).json()

        if response.get("status") in ["REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST"]:
            print("Google API error:", response.get("status"))
            return None, True

        results = response.get("results", [])
        if not results:
            return None, False

        place_id = results[0]["place_id"]

        details_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=website&key={google_api}"
        details = requests.get(details_url).json()

        if details.get("status") in ["REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST"]:
            print("Google API error:", details.get("status"))
            return None, True

        website = details.get("result", {}).get("website")
        print(f"website: {website}")
        return website, False

    except Exception as e:
        print("Google Maps error:", e)
        return None, True


# -----------------------------
# FULLENRICH API
# -----------------------------
def get_enrichment_data(enrichment_id: str):
    headers = {"Authorization": full_enrich_api_key}
    url = f"https://app.fullenrich.com/api/v2/contact/enrich/bulk/{enrichment_id}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    entries = data.get("data", [])

    if not entries:
        return {"emails": [], "phones": [], "regions": []}

    contact_info = entries[0].get("contact_info", {})

    best_email = contact_info.get("most_probable_work_email", {})
    emails = [best_email["email"]] if best_email.get("email") else []

    phones_list = contact_info.get("phones", [])
    phones = [p["number"] for p in phones_list]
    regions = [p["region"] for p in phones_list]

    return {
        "emails": emails,
        "phones": phones,
        "regions": regions
    }


# -----------------------------
# MAIN PROCESS
# -----------------------------
def process_enrichment():
    query = f"""
    SELECT *
    FROM `{project_id}.{dataset_id}.{table_enrich}`
    WHERE flag = false and IDCC= 'IDCC 1147'
    LIMIT 20
    """

    df = bq_client.query(query).to_dataframe()
    print(f"Number of rows: {len(df)}")

    if df.empty:
        return "No records to process"

    results = []
    successful_ids = []

    for _, row in df.iterrows():
        enrichment_id = row["enrichment_id"]
        company_name = row.get("company_name")

        try:
            # enrichment API
            data = get_enrichment_data(enrichment_id)

            # website API
            website = None
            if company_name:
                website, api_error = get_company_website(company_name)
                if api_error:
                    print("Google API error -> stopping job")
                    break

            results.append({
                "enrichment_id": enrichment_id,
                "siren": str(row["siren"]),
                "processed_date": row["processed_date"],
                "emails": ",".join(data["emails"]),
                "phones": ",".join(data["phones"]),
                "regions": ",".join(data["regions"]),
                "website_link": website,
                "inserted_date": datetime.utcnow()
            })

            successful_ids.append(enrichment_id)

        except Exception as e:
            print(f"Error processing {enrichment_id}: {e}")

    # -----------------------------
    # INSERT INTO BIGQUERY
    # -----------------------------
    if results:
        df_out = pd.DataFrame(results)

        table_ref = f"{project_id}.{dataset_id}.{table_contact}"

        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND"
        )

        bq_client.load_table_from_dataframe(
            df_out,
            table_ref,
            job_config=job_config
        ).result()

    # -----------------------------
    # UPDATE FLAG
    # -----------------------------
    if successful_ids:
        ids = ",".join([f"'{i}'" for i in successful_ids])

        update_query = f"""
        UPDATE `{project_id}.{dataset_id}.{table_enrich}`
        SET flag = TRUE
        WHERE enrichment_id IN ({ids})
        """

        bq_client.query(update_query).result()

    return f"Processed {len(results)} records"


# -----------------------------
# CLOUD FUNCTION ENTRY POINT
# -----------------------------
def hello_http(request):
    try:
        init_secrets()
        result = process_enrichment()
        return {"status": "success", "message": result}, 200

    except Exception as e:
        print("FATAL ERROR:", str(e))
        return {"status": "error", "message": str(e)}, 500