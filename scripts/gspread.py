from .log import *
import gspread
import gspread_formatting as gfmt
import datetime
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _disable_requests_tls_verification():
    original_request = requests.sessions.Session.request

    def patched_request(self, method, url, *args, **kwargs):
        kwargs.setdefault("verify", False)
        return original_request(self, method, url, *args, **kwargs)

    requests.sessions.Session.request = patched_request

TARGET_SHEET = "1gjYXr-aFrDLLXUfmsA-tN_Tc5rgovtIfeDqoJM-78jM"


def _build_file_chip_cell(url, date_str):
    """Build a CellData with chipRuns for a Drive file chip + date text.

    Cell text: "@ (2026-03-22)"
    chipRuns maps the @ at index 0 to a Drive file rich link chip.
    Note: Only Google Drive file URIs can be written as chips.
    """
    cell_text = f"@ {date_str}"
    return {
        "userEnteredValue": {"stringValue": cell_text},
        "chipRuns": [
            {
                "startIndex": 0,
                "chip": {
                    "richLinkProperties": {"uri": url},
                },
            }
        ],
    }


def log(logs, new_file_urls=None):
    if new_file_urls is None:
        new_file_urls = []
    _disable_requests_tls_verification()
    account = gspread.service_account(r"api.json")
    SHEET = account.open_by_key(TARGET_SHEET)
    worksheet = SHEET.worksheet("업데이트 로그")
    sheet_id = worksheet.id
    worksheet.insert_cols([[]], 1)

    now = datetime.datetime.now()
    date_str = now.strftime("(%Y-%m-%d)")

    # Write title (A2) and log text (A3) via normal update
    worksheet.update([
        [str(now) + " 업데이트 기록"],
        [logs],
    ], 'A2:A3')

    # Format title (A2)
    worksheet.format("A2", {
        "backgroundColor": {
            "red": 0.945,
            "green": 0.760,
            "blue": 0.196
        },
        "horizontalAlignment": "CENTER",
        "textFormat": {
            "foregroundColor": {
                "red": 0.0,
                "green": 0.0,
                "blue": 0.0
            },
            "fontSize": 18,
            "bold": True
        }
    })
    # Format log text (A3)
    worksheet.format("A3", {
        "backgroundColor": {
            "red": 1.0,
            "green": 0.95,
            "blue": 0.8
        },
        "horizontalAlignment": "LEFT",
        "textFormat": {
            "foregroundColor": {
                "red": 0.0,
                "green": 0.0,
                "blue": 0.0
            },
            "fontSize": 12,
            "bold": False
        }
    })

    # Write file chip rows (A4+) via batchUpdate with chipRuns
    # Drive chip requests are limited to 10 per batchUpdate call
    if new_file_urls:
        chip_rows = []
        for url in new_file_urls:
            chip_rows.append({"values": [_build_file_chip_cell(url, date_str)]})

        CHIP_BATCH_SIZE = 10
        start_row = 3  # 0-indexed row 3 = A4
        for i in range(0, len(chip_rows), CHIP_BATCH_SIZE):
            batch = chip_rows[i:i + CHIP_BATCH_SIZE]
            batch_start = start_row + i
            SHEET.batch_update({
                "requests": [
                    {
                        "updateCells": {
                            "rows": batch,
                            "fields": "userEnteredValue,chipRuns",
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": batch_start,
                                "endRowIndex": batch_start + len(batch),
                                "startColumnIndex": 0,
                                "endColumnIndex": 1,
                            },
                        }
                    }
                ]
            })

        # Format chip rows
        last_row = 4 + len(new_file_urls) - 1
        worksheet.format(f"A4:A{last_row}", {
            "backgroundColor": {
                "red": 0.93,
                "green": 0.97,
                "blue": 1.0
            },
            "horizontalAlignment": "LEFT",
            "textFormat": {
                "foregroundColor": {
                    "red": 0.0,
                    "green": 0.0,
                    "blue": 0.0
                },
                "fontSize": 11,
                "bold": False
            }
        })

    gfmt.set_column_width(worksheet, 'A', 900)
