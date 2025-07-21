import os, base64, json, gspread, asyncio
from google.oauth2.service_account import Credentials

_sheet_id = os.getenv("GOOGLE_SHEET_ID")
_sa_b64   = os.getenv("GCP_SA_B64")

def _client():
    creds_dict = json.loads(base64.b64decode(_sa_b64))
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

async def append_row(values: list[str]):
    if not (_sheet_id and _sa_b64): return
    loop = asyncio.get_running_loop()
    def _write():
        sh = _client().open_by_key(_sheet_id)
        ws = sh.worksheet("Scans")
        ws.append_row(values, value_input_option="RAW")
    await loop.run_in_executor(None, _write)