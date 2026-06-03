"""
Drive synchronization module.

Separates rclone I/O from conversion logic so that
Download (Phase 0) and Upload (Phase 3) run independently.
"""

from . import rclone
from .helper import Helper_GetFilesFromDir, Helper_GetFilesFromDirByCheck
from .paths import (
    DRIVE_PATH, REMOTE_PATH,
    ADV_REMOTE_PATH, ADV_DRIVE_PATH,
    MASTERDB2_REMOTE_PATH, MASTERDB2_DRIVE_PATH,
    GENERIC_REMOTE_PATH, GENERIC_DRIVE_PATH,
    GENERIC_REMOTE_LYRICS_PATH, GENERIC_DRIVE_LYRICS_PATH, GENERIC_FILE_LIST,
    LOCALIZATION_FILE, LOCALIZATION_REMOTE_PATH, LOCALIZATION_DRIVE_PATH,
)
from .log import *


def download_all(bFullUpdate=False, ADV=True, MASTERDB=True, GENERIC=True, LOCALIZATION=True):
    """Phase 0: Download remote → local for all enabled pipelines.

    Returns dict of changed file paths per pipeline:
        {"adv": [...], "masterdb": [...], "generic": [...], "localization": [...]}
    Each value is a list of (abs_path, rel_path, filename) tuples.
    """
    result = {
        "adv": [],
        "masterdb": [],
        "generic": [],
        "localization": [],
    }

    if ADV:
        LOG_INFO(1, "Download ADV")
        result["adv"] = _download_adv(bFullUpdate)

    if MASTERDB:
        LOG_INFO(1, "Download MasterDB")
        result["masterdb"] = _download_masterdb(bFullUpdate)

    if GENERIC:
        LOG_INFO(1, "Download Generic")
        result["generic"] = _download_generic(bFullUpdate)

    if LOCALIZATION:
        LOG_INFO(1, "Download Localization")
        result["localization"] = _download_localization(bFullUpdate)

    return result


def upload_all(ADV=True, MASTERDB=True, LOCALIZATION=True):
    """Phase 3: Upload local → remote for pipelines that support Update.

    Returns (adv_result, masterdb_result, localization_result) where each result is
    {"files": [...], "remote_path": "..."} or {"files": [], "remote_path": ""}.
    """
    adv_result = {"files": [], "remote_path": ADV_REMOTE_PATH}
    masterdb_result = {"files": [], "remote_path": MASTERDB2_REMOTE_PATH}
    localization_result = {"files": [], "remote_path": REMOTE_PATH}

    if ADV:
        LOG_INFO(1, "Upload ADV")
        adv_result["files"] = _upload_pipeline(ADV_DRIVE_PATH, ADV_REMOTE_PATH)

    if MASTERDB:
        LOG_INFO(1, "Upload MasterDB")
        masterdb_result["files"] = _upload_pipeline(MASTERDB2_DRIVE_PATH, MASTERDB2_REMOTE_PATH)

    if LOCALIZATION:
        LOG_INFO(1, "Upload Localization")
        localization_result["files"] = _upload_localization()

    return adv_result, masterdb_result, localization_result


# ============================================================
# Internal download helpers
# ============================================================


def _download_adv(bFullUpdate):
    if bFullUpdate:
        rclone.copy(ADV_REMOTE_PATH, ADV_DRIVE_PATH)
        return Helper_GetFilesFromDir(ADV_DRIVE_PATH, ".xlsx", "adv_")
    else:
        check_result = rclone.check(ADV_REMOTE_PATH, ADV_DRIVE_PATH)
        changed = Helper_GetFilesFromDirByCheck(check_result, ADV_DRIVE_PATH, ".xlsx", "adv_")
        rclone.copy(ADV_REMOTE_PATH, ADV_DRIVE_PATH)
        return changed


def _download_masterdb(bFullUpdate):
    if bFullUpdate:
        rclone.copy(MASTERDB2_REMOTE_PATH, MASTERDB2_DRIVE_PATH)
        return Helper_GetFilesFromDir(MASTERDB2_DRIVE_PATH, ".xlsx")
    else:
        check_result = rclone.check(MASTERDB2_REMOTE_PATH, MASTERDB2_DRIVE_PATH)
        changed = Helper_GetFilesFromDirByCheck(check_result, MASTERDB2_DRIVE_PATH, ".xlsx")
        rclone.copy(MASTERDB2_REMOTE_PATH, MASTERDB2_DRIVE_PATH)
        return changed


def _download_generic(bFullUpdate):
    import os
    drive_file_paths = []

    if bFullUpdate:
        rclone.copy(GENERIC_REMOTE_LYRICS_PATH, GENERIC_DRIVE_LYRICS_PATH)
        drive_file_paths = Helper_GetFilesFromDir(GENERIC_DRIVE_LYRICS_PATH, ".xlsx")
        for file in GENERIC_FILE_LIST:
            rclone.copy(GENERIC_REMOTE_PATH + file, GENERIC_DRIVE_PATH)
            drive_file_paths += [(GENERIC_DRIVE_PATH + file, file, os.path.basename(file))]
    else:
        check_result = rclone.check(GENERIC_REMOTE_LYRICS_PATH, GENERIC_DRIVE_LYRICS_PATH)
        drive_file_paths = Helper_GetFilesFromDirByCheck(check_result, GENERIC_DRIVE_LYRICS_PATH, ".xlsx")
        rclone.copy(GENERIC_REMOTE_LYRICS_PATH, GENERIC_DRIVE_LYRICS_PATH)
        for file in GENERIC_FILE_LIST:
            check_result = rclone.check(GENERIC_REMOTE_PATH + file, GENERIC_DRIVE_PATH)
            if len(check_result) > 0:
                rclone.copy(GENERIC_REMOTE_PATH + file, GENERIC_DRIVE_PATH)
                drive_file_paths += [(GENERIC_DRIVE_PATH + file, file, os.path.basename(file))]

    return drive_file_paths


def _download_localization(bFullUpdate):
    import os
    if bFullUpdate:
        rclone.copy(LOCALIZATION_REMOTE_PATH, DRIVE_PATH)
        return [(LOCALIZATION_DRIVE_PATH, LOCALIZATION_FILE, os.path.basename(LOCALIZATION_DRIVE_PATH))]
    else:
        check_result = rclone.check(LOCALIZATION_REMOTE_PATH, DRIVE_PATH)
        if len(check_result) > 0:
            rclone.copy(LOCALIZATION_REMOTE_PATH, DRIVE_PATH)
            return [(LOCALIZATION_DRIVE_PATH, LOCALIZATION_FILE, os.path.basename(LOCALIZATION_DRIVE_PATH))]
        return []


# ============================================================
# Internal upload helper
# ============================================================


def _upload_pipeline(drive_path, remote_path):
    file_list = rclone.check(drive_path, remote_path)
    LOG_WARN(2, f"There is {len(file_list)} files changed")
    LOG_DEBUG(2, f"file_list : {file_list}")
    for obj in file_list:
        if obj[0] == "*":
            LOG_DEBUG(2, f"Update '{obj[1]}' file to remote")
    for obj in file_list:
        if obj[0] == "+":
            LOG_DEBUG(2, f"Add new '{obj[1]}' file to remote")
    if len(file_list) > 0:
        rclone.sync(drive_path, remote_path)
    return file_list


def _upload_localization():
    """Single-file upload of localization.xlsx — uses copy (not sync) so the
    parent dir's other files are not touched."""
    import os
    file_list = rclone.check(LOCALIZATION_DRIVE_PATH, LOCALIZATION_REMOTE_PATH)
    LOG_DEBUG(2, f"localization check_result : {file_list}")
    if len(file_list) > 0:
        # copy the single file into the remote parent dir.
        rclone.copy(LOCALIZATION_DRIVE_PATH, REMOTE_PATH)
        # Normalize entries so _update_summary can display them.
        return [(entry[0], os.path.basename(LOCALIZATION_FILE)) for entry in file_list]
    return []
