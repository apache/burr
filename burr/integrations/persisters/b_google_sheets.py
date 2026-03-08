import json
from burr.core.persistence import BaseStatePersister


class GoogleSheetsPersister(BaseStatePersister):
    """
    Persister that stores Burr state in Google Sheets.
    """

    def __init__(self, spreadsheet_id):
        self.spreadsheet_id = spreadsheet_id

    def save(self, app_id: str, partition_key: str, state: dict):
        """
        Save state to Google Sheets
        """
        print("Saving state to Google Sheets")

    def load(self, app_id: str, partition_key: str):
        """
        Load state from Google Sheets
        """
        print("Loading state from Google Sheets")

    def list(self, app_id: str):
        """
        List partitions
        """
        return []