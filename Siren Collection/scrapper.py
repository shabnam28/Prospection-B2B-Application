import os
import re
import io
import time
import logging
import requests
from bs4 import BeautifulSoup
import pandas as pd
from dotenv import load_dotenv
from google.cloud import storage
from google.cloud import bigquery

# Load .env
load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RubyPayeurScraper:
    """
    Scraper RubyPayeur
    - 1 CSV par région → uploadé directement dans GCS
    - 1 CSV global combiné → uploadé directement dans GCS
    - CSV ALL_REGIONS → appendé dans BigQuery
    Aucun fichier local créé.

    BQ table schema:
        siren           STRING
        nom             STRING
        ville           STRING
        code_postal     STRING
        region          STRING
        processed       INTEGER   (default 0)
        source_folder   STRING    (e.g. "IDCC 3223")
        processed_date  DATE      (default NULL)
    """

    def __init__(self, idcc: str = "0759"):

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'fr-FR,fr;q=0.9'
        })

        self.idcc          = idcc
        self.source_folder = f"IDCC {idcc}"

        # Read config from .env
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "cv-analyser-agent-4419d472152f.json"
        self.bucket_name  = os.getenv("BUCKET_NAME_SIRENS", )
        self.blob_idcc   = os.getenv("BLOB_IDCC")
        self.project_id   = os.getenv("PROJECT_ID")
        self.dataset_id   = os.getenv("DATASET_ID")
        self.bq_table  = os.getenv("TABLE_ID")
        self.bq_table_id = f"{self.project_id}.{self.dataset_id}.{self.bq_table}"
        self.source_folder = f"IDCC {idcc}"

        # Fully-qualified BigQuery table ID: project.dataset.table
        self.bq_table_id = (
            f"{self.project_id}.{self.dataset_id}.{self.bq_table}"
        )

        # Full GCS prefix: sirens_list/IDCC 3223
        self.gcs_prefix = f"{self.blob_idcc}/IDCC {self.idcc}"

        # GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(self.bucket_name)

        # BigQuery client
        self.bq_client = bigquery.Client(project=self.project_id)

        # Explicit BQ schema — must match the table exactly
        self.bq_schema = [
            bigquery.SchemaField("siren",          "INTEGER"),
            bigquery.SchemaField("nom",            "STRING"),
            bigquery.SchemaField("ville",          "STRING"),
            bigquery.SchemaField("code_postal",    "INTEGER"),
            bigquery.SchemaField("processed",      "INTEGER"),
            bigquery.SchemaField("source_folder",  "STRING"),
            bigquery.SchemaField("processed_date", "DATETIME"),
        ]

        # define regions 
        self.regions = [
            "paris",
            "seine-et-marne",
            "yvelines",
            "hauts-de-seine",
            "seine-saint-denis",
            "val-de-marne",
            "val-d-oise"
        ]

        # Stockage global
        self.all_regions_data = []

    # =========================================================
    # BUILD ENTREPRISE RECORD
    # =========================================================

    def _build_record(self, siren, nom, ville, code_postal, region):
        """
        Returns a dict matching the BQ table schema exactly:
        - processed       = 0     (not yet processed)
        - source_folder   = IDCC 3223
        - processed_date  = None  (NULL in BigQuery)
        """
        return {
            'siren':          siren.strip(),
            'nom':            nom.strip(),
            'ville':          ville.strip(),
            'code_postal':    code_postal.strip(),
            'processed':      0,
            'source_folder':  self.source_folder,
            'processed_date': None          # → NULL in BigQuery
        }

    # =========================================================
    # GCS UPLOAD
    # =========================================================

    def upload_df_to_gcs(self, df: pd.DataFrame, filename: str) -> str:
        """
        Upload a DataFrame as CSV directly to GCS.
        Returns the full GCS URI: gs://bucket/path/file.csv
        """
        buffer = io.StringIO()
        df.to_csv(buffer, index=False, encoding='utf-8-sig')
        buffer.seek(0)

        blob_path = f"{self.gcs_prefix}/{filename}"
        blob = self.bucket.blob(blob_path)

        blob.upload_from_string(
            buffer.getvalue(),
            content_type='text/csv; charset=utf-8'
        )

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        logger.info(f"☁️  Uploadé → {gcs_uri}")
        return gcs_uri

    # =========================================================
    # BIGQUERY APPEND
    # =========================================================

    def append_to_bigquery(self, gcs_uri: str):
        """
        Load the ALL_REGIONS CSV from GCS and append rows
        to the BigQuery table. Reads directly from GCS —
        no local file needed.
        """
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            schema=self.bq_schema,          # explicit schema, no autodetect
            null_marker=""                  # empty string → NULL (for processed_date)
        )

        logger.info(
            f"📤 Chargement BigQuery: {gcs_uri} → {self.bq_table_id}"
        )

        job = self.bq_client.load_table_from_uri(
            gcs_uri,
            self.bq_table_id,
            job_config=job_config
        )

        try:
            job.result()  # Wait for the job to complete
            logger.info(
                f"✅ BigQuery: {job.output_rows or 0} lignes ajoutées "
                f"dans {self.bq_table_id}"
            )
        except Exception as e:
            logger.error(f"❌ BigQuery job failed: {job.errors}")
            raise

    # =========================================================
    # URL
    # =========================================================

    def get_base_url(self, region: str) -> str:
        return (
            f"https://rubypayeur.com/annuaire/"
            f"conventions-collectives/"
            f"{self.idcc}/"
            f"{region}/page/"
        )

    # =========================================================
    # SCRAPE PAGE
    # =========================================================

    def scrape_page(self, region: str, page_num: int):

        url = f"{self.get_base_url(region)}{page_num}"
        logger.info(f"🔍 [{region}] Page {page_num}")

        try:
            response = self.session.get(url, timeout=15)

            if response.status_code != 200:
                logger.warning(f"❌ [{region}] HTTP {response.status_code}")
                return []

            soup = BeautifulSoup(response.content, 'html.parser')
            entreprises_page = []

            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 4:
                        entreprise = self._extract_entreprise_from_cells(
                            cells, region
                        )
                        if entreprise:
                            entreprises_page.append(entreprise)

            # Fallback regex
            if not entreprises_page:
                entreprises_page = self._extract_from_text_patterns(
                    soup, region
                )

            logger.info(f"✅ [{region}] {len(entreprises_page)} entreprises")
            return entreprises_page

        except Exception as e:
            logger.error(f"❌ [{region}] Erreur page {page_num}: {e}")
            return []

    # =========================================================
    # EXTRACTION TABLE
    # =========================================================

    def _extract_entreprise_from_cells(self, cells, region):
        try:
            nom         = cells[0].get_text(strip=True).replace('"', '')
            ville       = cells[1].get_text(strip=True)
            code_postal = cells[2].get_text(strip=True)
            siren       = cells[3].get_text(strip=True)

            if re.match(r'^\d{9}$', siren):
                return self._build_record(
                    siren, nom, ville, code_postal, region
                )
        except Exception:
            pass
        return None

    # =========================================================
    # EXTRACTION REGEX
    # =========================================================

    def _extract_from_text_patterns(self, soup, region):
        entreprises = []
        try:
            text = soup.get_text()
            pattern = (
                r'\|\s*([^|]+?)\s*\|'
                r'\s*([^|]+?)\s*\|'
                r'\s*(\d{5})\s*\|'
                r'\s*(\d{9})\s*\|'
            )
            for match in re.findall(pattern, text):
                nom, ville, code_postal, siren = match
                entreprises.append(
                    self._build_record(
                        siren, nom, ville, code_postal, region
                    )
                )
        except Exception as e:
            logger.error(f"Erreur regex: {e}")
        return entreprises

    # =========================================================
    # PAGINATION
    # =========================================================

    def get_total_pages(self, region: str):
        try:
            url = f"{self.get_base_url(region)}1"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return 1

            soup = BeautifulSoup(response.content, 'html.parser')
            max_page = 1

            for link in soup.find_all('a', href=re.compile(r'/page/\d+')):
                page_match = re.search(r'/page/(\d+)', link.get('href', ''))
                if page_match:
                    max_page = max(max_page, int(page_match.group(1)))

            logger.info(f"📄 [{region}] {max_page} pages")
            return max_page

        except Exception as e:
            logger.error(f"Erreur pagination [{region}]: {e}")
            return 1

    # =========================================================
    # SAVE REGION CSV → GCS
    # =========================================================

    def save_region_csv(self, region: str, entreprises: list):
        if not entreprises:
            logger.warning(f"Aucune donnée pour {region}")
            return

        df = pd.DataFrame(entreprises).drop_duplicates(subset=['siren'])

        filename = (
            f"entreprises_rubypayeur_"
            f"idcc_{self.idcc}_{region}.csv"
        )
        self.upload_df_to_gcs(df, filename)

    # =========================================================
    # SAVE GLOBAL CSV → GCS + APPEND TO BIGQUERY
    # =========================================================

    def save_combined_csv(self):
        if not self.all_regions_data:
            logger.warning("Aucune donnée globale")
            return

        df = pd.DataFrame(self.all_regions_data).drop_duplicates(
            subset=['siren']
        )

        filename = (
            f"entreprises_rubypayeur_"
            f"idcc_{self.idcc}_ALL_REGIONS.csv"
        )

        # 1. Upload CSV to GCS
        gcs_uri = self.upload_df_to_gcs(df, filename)

        logger.info(f"📊 Total global: {len(df)} entreprises")

        # 2. Append directly from GCS into BigQuery
        self.append_to_bigquery(gcs_uri)

    # =========================================================
    # SCRAPE REGION
    # =========================================================

    def scrape_region(self, region: str):
        logger.info(f"\n🚀 Début scraping région: {region}")

        total_pages     = self.get_total_pages(region)
        all_entreprises = []

        for page_num in range(1, total_pages + 1):
            entreprises_page = self.scrape_page(region, page_num)
            if entreprises_page:
                all_entreprises.extend(entreprises_page)
                self.all_regions_data.extend(entreprises_page)
            time.sleep(1)

        self.save_region_csv(region, all_entreprises)
        logger.info(
            f"✅ [{region}] terminé - {len(all_entreprises)} entreprises"
        )

    # =========================================================
    # SCRAPE ALL
    # =========================================================

    def scrape_all_regions(self):
        for region in self.regions:
            try:
                self.scrape_region(region)
            except Exception as e:
                logger.error(f"❌ Erreur région {region}: {e}")
            time.sleep(3)

        # Upload global CSV to GCS + append to BigQuery
        self.save_combined_csv()


# =========================================================
# EXECUTION
# =========================================================

if __name__ == "__main__":
    scraper = RubyPayeurScraper(idcc="0759")
    scraper.scrape_all_regions()
    logger.info("🎉 Scraping terminé")