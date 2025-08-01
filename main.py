import os
from google.auth import default
from googleapiclient.discovery import build
from google.cloud import bigquery
from datetime import datetime
from google.cloud import storage

# === CONFIG ===
ROOT_FOLDER_ID = "1Hw_tKL6qx1d7I0MUnFgfS6TqWO7dvu-d"
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
GCP_PROJECT_ID = "snocks-analytics"  # <--- Ersetzen
BQ_DATASET = "input_automation_euw3"         # <--- Ersetzen
BQ_TABLE = "creatix_images"                 # <--- Ersetzen
IMAGE_VALUE_EUR = 30

# === AUTH ===
# Holt die default credentials aus der Cloud Functions Umgebung
creds, _ = default(scopes=[
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/cloud-platform'
])
drive_service = build('drive', 'v3', credentials=creds)
bq_client = bigquery.Client(credentials=creds, project=GCP_PROJECT_ID)

# === HELPER FUNKTIONEN ===

def my_function(request):
    client = storage.Client()  # Uses Cloud Function's identity automatically
    buckets = list(client.list_buckets())
    return f"Found {len(buckets)} buckets"

def test_bigquery_permissions():
    try:
        dataset = bq_client.get_dataset(BQ_DATASET)
        print("✅ Zugriff auf Dataset möglich:", dataset.dataset_id)
    except Exception as e:
        print("❌ Kein Zugriff auf Dataset:", e)

def get_last_id_from_bigquery():
    query = f"""
        SELECT MAX(id) as last_id
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}`
    """
    query_job = bq_client.query(query)
    result = query_job.result()
    row = next(result, None)
    return row.last_id if row and row.last_id is not None else 0

def list_folders(parent_id):
    folders = []
    page_token = None
    while True:
        response = drive_service.files().list(
            q=f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()
        folders.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break
    return folders

def get_images_in_folder(folder_id):
    images = []
    page_token = None

    while True:
        response = drive_service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()

        for file in response.get('files', []):
            if any(file['name'].lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
                images.append(file['name'])

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    return images

def get_images_from_favoriten_folders(results_folder_id):
    image_list = []
    subfolders = list_folders(results_folder_id)

    for folder in subfolders:
        if "- Favoriten" in folder['name']:
            images = get_images_in_folder(folder['id'])
            image_list.extend(images)

    return image_list

def insert_images_into_bigquery(image_list):
    table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"
    timestamp = datetime.utcnow().isoformat()
    
    last_id = get_last_id_from_bigquery()

    rows_to_insert = [
        {
            "id": last_id + i + 1,
            "filename": image,
            "value": IMAGE_VALUE_EUR,
            "timestamp": timestamp
        }
        for i, image in enumerate(image_list)
    ]

    errors = bq_client.insert_rows_json(table_id, rows_to_insert)
    if errors:
        print(f"❌ Fehler beim Einfügen in BigQuery: {errors}")
    else:
        print(f"✅ {len(rows_to_insert)} Einträge erfolgreich in BigQuery eingefügt.")

# === MAIN ===

def main():
    test_bigquery_permissions()
    all_images = []
    months = list_folders(ROOT_FOLDER_ID)
    print(f"📁 Gefundene Monate: {len(months)}")

    for month in months:
        month_name = month['name']
        jobs = list_folders(month['id'])

        for job in jobs:
            job_name = job['name']
            subfolders = list_folders(job['id'])

            for folder in subfolders:
                if folder['name'] == '3_Results':
                    images = get_images_from_favoriten_folders(folder['id'])
                    all_images.extend(images)
                    print(f"{month_name} / {job_name} / 3_Results / * - Favoriten: {len(images)} Bilder")

    print(f"\n✅ Gesamtanzahl Bilder in allen '- Favoriten'-Ordnern: {len(all_images)}")
    print(f"💰 Gesamtwert: {len(all_images) * IMAGE_VALUE_EUR} Euro")

    insert_images_into_bigquery(all_images)

if __name__ == "__main__":
    main()