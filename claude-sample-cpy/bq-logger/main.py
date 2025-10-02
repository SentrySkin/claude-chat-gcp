import base64
import json
import os
from google.cloud import bigquery
from datetime import datetime

PROJECT_ID = os.getenv("GCP_PROJECT", "christinevalmy")
DATASET = "assistant_logs"
TABLE = "claude_conversations"

bq_client = bigquery.Client()

def app(event, context):
    """Triggered from Pub/Sub and writes logs to BigQuery"""
    if "data" not in event:
        print("No data in event")
        return

    message = base64.b64decode(event["data"]).decode("utf-8")
    row = json.loads(message)

    if "timestamp" not in row:
        row["timestamp"] = datetime.utcnow().isoformat()

    table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"
    errors = bq_client.insert_rows_json(table_ref, [row])

    if errors:
        print(f"BigQuery insert errors: {errors}")
    else:
        print(f"Inserted row: {row}")
