import pandas as pd
import requests
import time

def get_siren_info_by_api(siren: str):

    """
    Get company information from the API Recherche Entreprises.
    Returns:
        dirigeants (list)
        etablissement_info (dict)
    """

   
    url = "https://recherche-entreprises.api.gouv.fr/search"

    params = {
        "q": siren
    }

    response = requests.get(url, params=params, timeout=30)
    
    response.raise_for_status()

    data = response.json()

    if data["total_results"] == 0:
        return [], {}

    company = data["results"][0]
    siege = company.get("siege", {})

    dirigeants = company.get("dirigeants", [])

    etablissement_info = {
        "Dénomination": company.get("nom_complet", ""),
        "Adresse postale": siege.get("adresse", ""),
        "Activité principale (NAF/APE)": company.get("activite_principale", ""),
        "Code NAF/APE": company.get("activite_principale", ""),
        "Code NAF 2025": company.get("activite_principale_naf25", ""),
        "Effectif salarié": company.get("tranche_effectif_salarie", ""),
        "Année effectif": company.get("annee_tranche_effectif_salarie", ""),
        "Taille de la structure": company.get("categorie_entreprise", ""),
        "Convention(s) collective(s)": siege.get("liste_idcc", []),
        "Adresse": siege.get("adresse", ""),
        "Code postal": siege.get("code_postal", ""),
        "Ville": siege.get("libelle_commune", ""),
        "SIRET": siege.get("siret", ""),
        "Nature juridique": company.get("nature_juridique", ""),
        "Section NAF": company.get("section_activite_principale", ""),
    }

    return dirigeants, etablissement_info


def process_excel(input_file, output_file):
    df = pd.read_excel(input_file)

    results = []
    
    # FIX: Iterate correctly with index to get corresponding row data
    for idx, row in df.iterrows():
        siren = str(row["siren"])
        nom = row.get("nom", "")
        ville = row.get("ville", "")
        code_postal = row.get("code_postal", "")
        
        try:
            time.sleep(0.5)
            dirs, etab = get_siren_info_by_api(siren)
            denomination = etab.get("Dénomination", "")
            adresse = etab.get("Adresse postale", "")
            activity_type = etab.get("Activité principale (NAF/APE)", "")
            code_naf = etab.get("Code NAF/APE", "")
            code_naf25 = etab.get("Code NAF 2025", "")
            activity_type = get_naf25_label(code_naf25)
            tranche = etab.get("Effectif salarié", "")
            clef_nic = etab.get("Convention(s) collective(s)", "")
            company_taille = etab.get("Taille de la structure", "")
            if dirs:
                for d in dirs:
                    results.append({
                        "SIREN": siren,
                        "nom": nom,
                        "denomination": denomination,
                        "ville": ville,
                        "code_postal": code_postal,
                        "Adresse": adresse,
                        "activity_type": activity_type,
                        "Code NAF/APE de l'établissement": code_naf,
                        "Effectif salarié": tranche,
                        "Clef NIC": clef_nic,
                        "company_taille": company_taille,
                        "Role": d["role"],
                        "Details": d["details"]
                    })
            else:
                # No dirigeants found
                results.append({
                    "SIREN": siren,
                    "nom": nom,
                    "denomination": denomination,
                    "ville": ville,
                    "code_postal": code_postal,
                    "Adresse": adresse,
                    "activity_type": activity_type,
                    "Code NAF/APE de l'établissement": code_naf,
                    "Effectif salarié": tranche,
                    "Clef NIC": clef_nic,
                    "company_taille": company_taille,
                    "Role": "",
                    "Details": ""
                })

        except Exception as e:
            print(f"⚠️ Error with SIREN {siren}: {e}")
            # Add row with error info
            results.append({
                "SIREN": siren,
                "nom": nom,
                "denomination": "",
                "ville": ville,
                "code_postal": code_postal,
                "Adresse": "ERROR",
                "activity_type": "",
                "Code NAF/APE de l'établissement": "",
                "Effectif salarié": "",
                "Clef NIC": "",
                "company_taille": "",
                "Role": "",
                "Details": str(e)
            })

    out_df = pd.DataFrame(results)
    out_df.to_excel(output_file, index=False)
    print(f"✅ Exported {len(out_df)} rows to {output_file}")
