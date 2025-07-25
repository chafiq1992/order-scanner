import os
import base64
import json
import gspread
import asyncio
from google.oauth2.service_account import Credentials


# Cached Google client and worksheet objects
_client_obj = None
_worksheet = None


_sheet_id = os.getenv("GOOGLE_SHEET_ID")
_sa_b64 = os.getenv("GCP_SA_B64")


def _client():
    global _client_obj
    if _client_obj is None:
        creds_dict = json.loads(base64.b64decode(_sa_b64))
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        _client_obj = gspread.authorize(creds)
    return _client_obj


async def append_row(values: list[str]):
    if not (_sheet_id and _sa_b64):
        return
    loop = asyncio.get_running_loop()

    def _write():
        global _worksheet
        if _worksheet is None:
            sh = _client().open_by_key(_sheet_id)
            _worksheet = sh.worksheet("Scans")
        _worksheet.append_row(values, value_input_option="RAW")
    await loop.run_in_executor(None, _write)
