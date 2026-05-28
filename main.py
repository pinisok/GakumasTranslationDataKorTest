
from datetime import datetime
import argparse, io, os

from scripts import rclone, adv, masterdb2, generic, localization
from scripts.log import *

full_update = False
CONVERT = True
UPDATE = True

def Convert(ADV=True, MASTERDB=True, GENERIC=True, LOCALIZATION=True, bFullUpdate=False, changed_files=None):
    if changed_files is None:
        changed_files = {}
    ERR_ADV_FILE = []
    ADV_FILE = []
    ERR_MASTERDB_FILE = []
    MASTERDB_FILE = []
    ERR_GENERIC_FILE = []
    GENERIC_FILE = []
    ERR_LOCALIZATION_FILE = []
    LOCALIZATION_FILE = []
    if ADV:
        LOG_INFO(1, "Converting ADV")
        adv_files = changed_files.get("adv")
        ERR_ADV_FILE, ADV_FILE = adv.ConvertDriveToOutput(adv_files, bFullUpdate)
    if MASTERDB:
        LOG_INFO(1, "Converting MasterDB")
        mdb_files = changed_files.get("masterdb")
        ERR_MASTERDB_FILE, MASTERDB_FILE = masterdb2.ConvertDriveToOutput(mdb_files, bFullUpdate)
    if GENERIC:
        LOG_INFO(1, "Converting Generic")
        gen_files = changed_files.get("generic")
        ERR_GENERIC_FILE, GENERIC_FILE = generic.ConvertDriveToOutput(gen_files, bFullUpdate)
    if LOCALIZATION:
        LOG_INFO(1, "Converting Localization")
        loc_files = changed_files.get("localization")
        ERR_LOCALIZATION_FILE, LOCALIZATION_FILE = localization.ConvertDriveToOutput(loc_files, bFullUpdate)

    if len(ADV_FILE) + len(MASTERDB_FILE) + len(GENERIC_FILE) + len(LOCALIZATION_FILE) > 0:
        LOG_INFO(1, "Write version.txt")
        with open("./output/version.txt", 'w', encoding='utf-8') as f:
            f.write(datetime.today().strftime("%Y%m%d_%H%M%S"))
    else:
        LOG_INFO(1, "No files updated")
    return (ERR_ADV_FILE, ADV_FILE), (ERR_MASTERDB_FILE, MASTERDB_FILE), (ERR_GENERIC_FILE, GENERIC_FILE), (ERR_LOCALIZATION_FILE, LOCALIZATION_FILE)

def Update(ADV=True, MASTERDB=True, bFullUpdate=False):
    ADV_FILE = []
    MASTERDB_FILE = []
    all_warnings = {}
    if ADV:
        LOG_INFO(1, "Updating ADV")
        ADV_FILE, adv_warnings = adv.UpdateOriginalToDrive()
        all_warnings.update(adv_warnings)
    if MASTERDB:
        LOG_INFO(1, "Updating MasterDB")
        MASTERDB_FILE, mdb_warnings = masterdb2.UpdateOriginalToDrive()
        all_warnings.update(mdb_warnings)

    return ADV_FILE, MASTERDB_FILE, all_warnings
    
def getDriveLink(rel_path, remote_path=""):
    """Get Google Drive open URL for a file.
    Returns (display_text, drive_url_or_None)."""
    if not remote_path:
        return rel_path, None
    full_remote = remote_path + "/" + rel_path
    try:
        link = rclone.link(full_remote)
        sheets_link = link.replace(
            "https://drive.google.com/open?id=",
            "https://docs.google.com/spreadsheets/d/"
        )
        return f"{rel_path} ({sheets_link})", sheets_link
    except Exception as e:
        LOG_DEBUG(1, f"Failed to get drive link: {e}")
        return rel_path, None

def _convert_summary(NAME, ARR):
    if len(ARR[0]) + len(ARR[1]) > 0:
        LOG_INFO(1, NAME)
        if len(ARR[0]) > 0:
            ARR[0].sort(key= lambda arr: arr[1])
            for fn in ARR[0]:
                LOG_INFO(2, f"변환 중 오류 {fn[1]} : {fn[0]}")
        if len(ARR[1]) > 0:
            ARR[1].sort()
            for fn in ARR[1]:
                LOG_INFO(2, f"{fn} 번역 갱신")

def _update_summary(NAME, upload_result, warnings=None, new_file_urls=None):
    """Log update summary. Collects Drive URLs for new files into new_file_urls list."""
    if warnings is None:
        warnings = {}
    if new_file_urls is None:
        new_file_urls = []
    ARR = upload_result.get("files", [])
    remote_path = upload_result.get("remote_path", "")
    if len(ARR) > 0:
        LOG_INFO(1, NAME)
        ARR.sort()
        for fn in ARR:
            rel_path = fn[1] if len(fn) > 1 else ""
            display, drive_url = getDriveLink(rel_path, remote_path)
            if fn[0] == "*":
                LOG_INFO(2, f"업데이트 : {display}")
            if fn[0] == "+":
                LOG_INFO(2, f"추가 : {display}")
                if drive_url:
                    new_file_urls.append(drive_url)
            # 해당 파일의 경고 출력 (파일당 최대 5건, 초과 시 요약)
            MAX_WARNINGS_PER_FILE = 5
            for wkey, wlist in warnings.items():
                if wkey in rel_path:
                    for w in wlist[:MAX_WARNINGS_PER_FILE]:
                        LOG_INFO(3, f"⚠ {w}")
                    if len(wlist) > MAX_WARNINGS_PER_FILE:
                        LOG_INFO(3, f"⚠ ... 외 {len(wlist) - MAX_WARNINGS_PER_FILE}건")
def main(ADV=True, MASTERDB=True, GENERIC=True, LOCALIZATION=True):
    from scripts import sync

    # Phase 0: Download from Google Drive
    LOG_INFO(0, "Phase 0: Download from Drive")
    changed_files = sync.download_all(full_update, ADV, MASTERDB, GENERIC, LOCALIZATION)

    # Phase 1: Convert (local drive → output)
    if CONVERT:
        LOG_INFO(0, "Phase 1: Convert")
        C_ADV_FILE, C_MASTERDB_FILE, C_GENERIC_FILE, C_LOCALIZATION_FILE = Convert(ADV, MASTERDB, GENERIC, LOCALIZATION, full_update, changed_files)

    # Phase 2: Update (submodule → local drive)
    # Phase 3: Upload to Google Drive
    U_UPLOAD_ADV = {"files": [], "remote_path": ""}
    U_UPLOAD_MASTERDB = {"files": [], "remote_path": ""}
    update_warnings = {}
    if UPDATE:
        LOG_INFO(0, "Phase 2: Update")
        _, _, update_warnings = Update(ADV, MASTERDB, full_update)

        LOG_INFO(0, "Phase 3: Upload to Drive")
        U_UPLOAD_ADV, U_UPLOAD_MASTERDB = sync.upload_all(ADV, MASTERDB)

    has_changes = False
    logStream = io.StringIO()
    logHandler = logging.StreamHandler(logStream)
    AddLogHandler(logHandler)
    new_file_urls = []
    if UPDATE:
        if len(U_UPLOAD_ADV["files"]) + len(U_UPLOAD_MASTERDB["files"]) > 0:
            has_changes = True
            LOG_INFO(0, "---------------- 업데이트된 파일 요약 ----------------")

            _update_summary("ADV", U_UPLOAD_ADV, update_warnings, new_file_urls)
            _update_summary("MASTERDB", U_UPLOAD_MASTERDB, update_warnings, new_file_urls)

            LOG_INFO(0, "----------------------------------------------------------")
        else:
            LOG_INFO(0, "No files updated")
    if CONVERT:
        if len(C_ADV_FILE[0]) + len(C_ADV_FILE[1]) + len(C_MASTERDB_FILE[0]) + len(C_MASTERDB_FILE[1]) + len(C_GENERIC_FILE[0]) + len(C_GENERIC_FILE[1]) + len(C_LOCALIZATION_FILE[0]) + len(C_LOCALIZATION_FILE[1]) > 0:
            has_changes = True
            LOG_INFO(0, "---------------- 번역 갱신된 파일 요약 ----------------")

            _convert_summary("ADV", C_ADV_FILE)
            _convert_summary("MASTERDB", C_MASTERDB_FILE)
            _convert_summary("GENERIC", C_GENERIC_FILE)
            _convert_summary("LOCALIZATION", C_LOCALIZATION_FILE)

            LOG_INFO(0, "----------------------------------------------------------")
        else:
            LOG_INFO(0, "No files converted")
    log_content = logStream.getvalue()
    if has_changes:
        try:
            import scripts.gspread
            scripts.gspread.log(log_content, new_file_urls)
        except Exception as e:
            LOG_ERROR(0, f"Failed to log to Google Sheets: {e}")
    logHandler.close()
    logStream.close()

    # Exit with error if any conversion failures occurred
    if CONVERT:
        total_errors = len(C_ADV_FILE[0]) + len(C_MASTERDB_FILE[0]) + len(C_GENERIC_FILE[0]) + len(C_LOCALIZATION_FILE[0])
        if total_errors > 0:
            LOG_ERROR(0, f"Convert phase had {total_errors} error(s)")
            raise SystemExit(1)
    


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--fullupdate', action='store_true')
    parser.add_argument('--DEBUG', action='store_true')
    parser.add_argument('--convert', action='store_true')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--adv', action='store_true')
    parser.add_argument('--masterdb', action='store_true')
    parser.add_argument('--generic', action='store_true')
    parser.add_argument('--localization', action='store_true')
    args = parser.parse_args()
    if args.fullupdate:
        full_update = True
    if args.DEBUG:
        logger.setLevel("DEBUG")
    else:
        logger.setLevel("INFO")
        import sys, os
        sys.stdout = open(os.devnull, 'w')
        rclone.logger.addHandler(RichHandler(console=Console(stderr=True)))
    handler = logging.FileHandler(f"output_python_{(datetime.today().strftime('%Y%m%d_%H%M%S'))}.log")
    logger.addHandler(handler)
    LOG_INFO(0, "Start scripts")
    if args.convert or args.update:
        CONVERT = False
        UPDATE = False
        if args.convert:
            CONVERT = True
        if args.update:
            UPDATE = True
    ADV = True
    MASTERDB = True
    GENERIC = True
    LOCALIZATION = True
    if args.adv or args.masterdb or args.generic or args.localization:
        ADV = False
        MASTERDB = False
        GENERIC = False
        LOCALIZATION = False
        if args.adv:
            ADV = True
        if args.masterdb:
            MASTERDB = True
        if args.generic:
            GENERIC = True
        if args.localization:
            LOCALIZATION = True


    main(ADV, MASTERDB, GENERIC, LOCALIZATION)