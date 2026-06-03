"""
Centralized path constants for all pipelines.

All modules should import paths from here instead of defining their own.
"""

import os

# Base paths
DEFAULT_PATH = os.getcwd()
REMOTE_PATH = "gakumas:Gakumas_KR"
DRIVE_PATH = DEFAULT_PATH + "/res/drive"
TEMP_PATH = DEFAULT_PATH + "/temp"
OUTPUT_PATH = DEFAULT_PATH + "/output"

# Git submodule paths
GIT_ADV_PATH = DEFAULT_PATH + "/res/adv"
GIT_MASTERDB_PATH = DEFAULT_PATH + "/res/masterdb"

# ADV
ADV_ORIGINAL_PATH = GIT_ADV_PATH + "/Resource"
ADV_REMOTE_PATH = REMOTE_PATH + "/text assets"
ADV_DRIVE_PATH = DRIVE_PATH + "/text assets"
ADV_TEMP_PATH = TEMP_PATH + "/adv"
ADV_OUTPUT_PATH = OUTPUT_PATH + "/local-files/resource"
ADV_CACHE_FILE = "./cache/adv_update_date.txt"

# MasterDB (shared by v1 and v2)
MASTERDB_ORIGINAL_PATH = GIT_MASTERDB_PATH + "/gakumasu-diff/orig"
MASTERDB_JSON_PATH = GIT_MASTERDB_PATH + "/gakumasu-diff/json"
MASTERDB_ORIGINAL_DATA_PATH = GIT_MASTERDB_PATH + "/data"
MASTERDB_REMOTE_PATH = REMOTE_PATH + "/masterDB"
MASTERDB_DRIVE_PATH = DRIVE_PATH + "/masterDB"
MASTERDB_TEMP_PATH = TEMP_PATH + "/masterDB"
MASTERDB_OUTPUT_PATH = OUTPUT_PATH + "/local-files/masterTrans"
MASTERDB_CACHE_FILE = "./cache/masterdb_update_date.txt"

# MasterDB v2 specific
MASTERDB2_REMOTE_PATH = REMOTE_PATH + "/masterDB2"
MASTERDB2_DRIVE_PATH = DRIVE_PATH + "/masterDB2"

# Generic
GENERIC_REMOTE_PATH = REMOTE_PATH + "/GenericTrans"
GENERIC_DRIVE_PATH = DRIVE_PATH + "/GenericTrans"
GENERIC_TEMP_PATH = TEMP_PATH + "/GenericTrans"
GENERIC_OUTPUT_PATH = OUTPUT_PATH + "/local-files/genericTrans"
GENERIC_FILE_LIST = ["/generic.xlsx", "/generic.fmt.xlsx"]
GENERIC_REMOTE_LYRICS_PATH = GENERIC_REMOTE_PATH + "/lyrics"
GENERIC_DRIVE_LYRICS_PATH = GENERIC_DRIVE_PATH + "/lyrics"
GENERIC_OUTPUT_LYRICS_PATH = GENERIC_OUTPUT_PATH + "/lyrics"

# Localization
LOCALIZATION_FILE = "/localization.xlsx"
LOCALIZATION_REMOTE_PATH = REMOTE_PATH + LOCALIZATION_FILE
LOCALIZATION_DRIVE_PATH = DRIVE_PATH + LOCALIZATION_FILE
LOCALIZATION_OUTPUT_PATH = OUTPUT_PATH + "/local-files" + LOCALIZATION_FILE[:-5] + ".json"

# Localization — release-driven update (pinisok/gaku-patcher GitHub Releases)
# The latest release publishes a `localization.json` asset (JP source-of-truth).
# We gate updates on the release tag so we don't re-fetch the same release.
LOCALIZATION_RELEASE_API_URL = "https://api.github.com/repos/pinisok/gaku-patcher/releases/latest"
LOCALIZATION_RELEASE_ASSET_NAME = "localization.json"
LOCALIZATION_RELEASE_CACHE_FILE = "./cache/localization_release_tag.txt"
LOCALIZATION_SOURCE_JSON_PATH = TEMP_PATH + "/localization_source.json"
LOCALIZATION_RELEASE_NOTES_PATH = OUTPUT_PATH + "/RELEASE_NOTES.md"
