import json
from burr.core import persistence
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

class GoogleSheetsPersister(persistence.BaseStatePersister):
    """
    Persister that stores Burr state in Google Sheets.
    """

    def __init__(self, spreadsheet_id: str, credentials_file: str):
        self.spreadsheet_id = spreadsheet_id
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(
        credentials_file,
        scopes=scopes)
        self.service = build("sheets", "v4", credentials=creds)

    
    
    def save(self, app_id: str, partition_key: str, state: dict):
        state_json = json.dumps(state)

        values = [[app_id, partition_key, state_json]]
        body = {"values": values}

        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range="states!A:C",
            valueInputOption="RAW",
            body=body).execute()
        


    def load(self, app_id: str, partition_key: str):
        result = self.service.spreadsheets().values().get(
        spreadsheetId=self.spreadsheet_id,
        range="states!A:C").execute()

        rows = result.get("values", [])

        for row in rows:
            if len(row) >= 3 and row[0] == app_id and row[1] == partition_key:
                return json.loads(row[2])

        return None
    


    def list(self, app_id: str):
        result = self.service.spreadsheets().values().get(
        spreadsheetId=self.spreadsheet_id,
        range="states!A:C").execute()

        rows = result.get("values", [])
        partition_keys = []

        for row in rows:
            if len(row) >= 2 and row[0] == app_id:
                partition_keys.append(row[1])

        return partition_keys
    


    def list_app_ids(self):
        result = self.service.spreadsheets().values().get(
        spreadsheetId=self.spreadsheet_id,
        range="states!A:C").execute()

        rows = result.get("values", [])
        app_ids = []

        for row in rows[1:]:
            if len(row) >= 1 and row[0] not in app_ids:
                app_ids.append(row[0])

        return app_ids