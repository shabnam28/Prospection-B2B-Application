import requests
import pandas as pd

def start_enrichment(daily_result: pd.DataFrame, api_key: str) -> pd.DataFrame:
    url = "https://app.fullenrich.com/api/v2/contact/enrich/bulk"

    headers = {
        "Authorization": f"{api_key}",
        "Content-Type": "application/json"
    }

    results = []
    contacts = daily_result.to_dict(orient="records")

    print(f"list of dirigeants to analyze: {len(contacts)}")

    #daily_result.to_csv("daily_result.csv", index=False, encoding="utf-8")
    #print("✅ CSV file saved as daily_result.csv")

    for contact in contacts:

        firstname = contact.get("dir_name", "")
        lastname = contact.get("dir_lname", "")
        role = contact.get("role", "")
        company_name = contact.get("company_name", "")
        siren = contact.get("siren", "")
        effectif_salary = contact.get("effectif_salary", "")

        # safe string conversion
        role = str(role)
        firstname = str(firstname)
        lastname = str(lastname)
        effectif_salary = str(effectif_salary)

        # SKIP RULES (safe version)
        if (
            role.upper().startswith("COMMISSAIRE")
            or role.upper().startswith("AUTRE")
            or not firstname
            or not lastname
            or effectif_salary.startswith(("0", "1 à 2", "Unité non employeuse", "Unité employeuse","Unités"))
        ):
            print(f"⏩ Skipping {firstname} {lastname} ({company_name}, {siren})")

            results.append({
                "siren": siren,
                "company_name": company_name,
                "dir_name": firstname,
                "dir_lname": lastname,
                "enrichment_id": None,
                "flag": False
            })
            continue

        payload = {
            "name": f"Enrichment {firstname} {lastname}",
            "data": [
                {
                    "first_name": firstname,
                    "last_name": lastname,
                    "company_name": company_name,
                    "enrich_fields": ["contact.work_emails", "contact.phones"]
                }
            ]
        }

        enrichment_id = None

        try:
            response = requests.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                print(f"❌ API error {response.status_code}: {response.text}")
            else:
                data = response.json()
                enrichment_id = data.get("id") or data.get("enrichment_id")
                print(f"✅ enrichment id is {enrichment_id}")

        except Exception as e:
            print(f"❌ Error for {siren} {firstname} {lastname}: {e}")

        results.append({
            "siren": siren,
            "company_name": company_name,
            "dir_name": firstname,
            "dir_lname": lastname,
            "enrichment_id": enrichment_id,
            "flag": False
        })

    return pd.DataFrame(results)