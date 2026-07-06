from google.cloud import bigquery
import pandas as pd
import os

# Set environment variable
project_id = os.getenv("PROJECT_ID")
dataset_id = os.getenv("DATASET_ID")
table_name = os.getenv("TABLE_OPCO_ENRICH")
table_id = f"{project_id}.{dataset_id}.{table_name}"
 
# Initialize BigQuery client
bq_client = bigquery.Client()
def save_to_bigquery(df: pd.DataFrame):
    # Define schema explicitly
    schema = [
    # Define the schema of the table
        bigquery.SchemaField("siren", "STRING"),
        bigquery.SchemaField("company_name", "STRING"),
        bigquery.SchemaField("denomination", "STRING"),
        bigquery.SchemaField("adresse", "STRING"),
        bigquery.SchemaField("IDCC", "STRING"),
        bigquery.SchemaField("ville", "STRING"),
        bigquery.SchemaField("code_postal", "INTEGER"),
        bigquery.SchemaField("code_naf", "STRING"),
        bigquery.SchemaField("effectif_salary", "STRING"),
        bigquery.SchemaField("activity_type", "STRING"),
        bigquery.SchemaField("clef_NIC", "STRING"),
        bigquery.SchemaField("company_taille", "STRING"),
        bigquery.SchemaField("role", "STRING"),
        bigquery.SchemaField("details", "STRING"),
        bigquery.SchemaField("dir_name", "STRING"),
        bigquery.SchemaField("dir_lname", "STRING"),
        bigquery.SchemaField("processed_date", "TIMESTAMP"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("enrichment_id", "STRING"),
        bigquery.SchemaField("flag", "BOOLEAN"),
    ]

# Check if table exists
    try:
        bq_client.get_table(table_id)
        table_exists = True
    except Exception:
        table_exists = False

    if not table_exists:
        print(f"Table {table_id} does not exist. Creating table...")
        table = bigquery.Table(table_id, schema=schema)
        table = bq_client.create_table(table)
        print(f"✅ Table {table_id} created.")

    # Load DataFrame into BigQuery
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_APPEND"  # append to table if exists
    )
    print(f"Loading data into full enrich table", len(df))

    job = bq_client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Wait for the job to complete
    print(f"✅ Data loaded into {table_id}.")


