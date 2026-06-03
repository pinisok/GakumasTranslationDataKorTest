import os, sys
from datetime import datetime
import shutil

import pandas as pd
import openpyxl
import xlsxwriter

from .helper import *
from .helper import Serialize, Deserialize
from .log import *


"""
Converter

"""

def XlsxToJson(input_path, output_path):
    input_dataframe = pd.read_excel(input_path, na_values="", keep_default_na=False, na_filter=False, engine="openpyxl")
    input_dataframe = input_dataframe.convert_dtypes()
    input_dataframe.fillna("", inplace=True)
    input_records = input_dataframe.to_dict(orient="records")
    data = {}
    for input_record in input_records:
        input_record_keys = input_record.keys()
        if not 0 in input_record_keys or not type(input_record[0]) == str:
            continue
        if not "ID" in input_record_keys or not type(input_record['ID']) == str:
            continue
        if not "번역" in input_record_keys or not type(input_record['번역']) == str:
            LOG_DEBUG(3, f"{input_record['ID']}({input_record[0]})의 번역 값이 존재하지 않습니다. 넘어갑니다.")
            continue
        # 수정해야되는 내용 수정
        if input_record["번역"].startswith("'"):
            data[input_record["ID"]] = Deserialize(input_record["번역"][1:])
        else:
            data[input_record["ID"]] = Deserialize(input_record["번역"])
    os.makedirs(os.path.split(output_path)[0], exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False, indent=4)
"""

Folder Processor

"""


from .paths import (
    LOCALIZATION_FILE, LOCALIZATION_REMOTE_PATH,
    LOCALIZATION_DRIVE_PATH, LOCALIZATION_OUTPUT_PATH,
)
from . import localization_release


# 업데이트 반영
# pinisok/gaku-patcher 의 최신 release 에 첨부된 localization.json 을 기준으로
# Google Drive 의 localization.xlsx 에 새 키를 추가하고, JP 원문이 바뀐 키는 갱신,
# release 에서 사라진 키는 OBSOLETE 마커로 표시한다.
#
# 반환 시그니처는 adv.UpdateOriginalToDrive 와 동일: (file_list, warnings)
#   - file_list: [(input_path, output_path, filename)] — main.Update() 가 무시하므로
#                실제로 변경된 경우에만 한 항목을 채워 넣는다.
#   - warnings: {filename: [str, ...]} — main 의 _update_summary 가 파일별 경고로 출력.
def UpdateOriginalToDrive(bFullUpdate=False):
    release = localization_release.fetch_latest_release()
    if release is None:
        LOG_WARN(2, "Localization release fetch failed — skipping update")
        return [], {}

    last_tag = localization_release.load_last_release_tag()
    if not bFullUpdate and last_tag == release.tag:
        LOG_INFO(2, f"Localization release {release.tag} already processed — skip")
        return [], {}

    LOG_INFO(2, f"Localization release {release.tag} detected "
                f"(previous: {last_tag or 'none'})")

    release_json = localization_release.download_release_json(release.asset_url)
    if release_json is None:
        return [], {}

    if not os.path.exists(LOCALIZATION_DRIVE_PATH):
        LOG_WARN(2, f"{LOCALIZATION_DRIVE_PATH} not found locally — "
                    f"download from Drive (Phase 0) before Update")
        return [], {}

    diff = localization_release.diff_release_against_xlsx(
        release_json, LOCALIZATION_DRIVE_PATH
    )

    if diff.empty:
        LOG_INFO(2, f"Localization release {release.tag} has no diff vs drive xlsx — "
                    f"only the tag cache is advanced")
        localization_release.save_release_tag(release.tag)
        return [], {}

    localization_release.apply_diff_to_xlsx(release_json, diff, LOCALIZATION_DRIVE_PATH)
    localization_release.append_release_notes(release, diff)
    localization_release.save_release_tag(release.tag)

    warnings = _diff_warnings(release, diff)
    filename = os.path.basename(LOCALIZATION_DRIVE_PATH)
    file_list = [(LOCALIZATION_DRIVE_PATH, LOCALIZATION_DRIVE_PATH, filename)]
    return file_list, warnings


def _diff_warnings(release, diff) -> dict:
    """Convert a diff into per-file warnings for the gspread / log summary."""
    filename = os.path.basename(LOCALIZATION_DRIVE_PATH)
    messages = [localization_release.summarize_diff(release, diff)]
    if diff.removed:
        sample = ", ".join(diff.removed[:5])
        suffix = "" if len(diff.removed) <= 5 else f" (외 {len(diff.removed) - 5}건)"
        messages.append(f"제거된 키는 OBSOLETE 처리: {sample}{suffix}")
    if diff.changed_jp:
        sample = ", ".join(list(diff.changed_jp.keys())[:5])
        suffix = "" if len(diff.changed_jp) <= 5 else f" (외 {len(diff.changed_jp) - 5}건)"
        messages.append(f"JP 변경된 키 재검수 필요: {sample}{suffix}")
    return {filename: messages}


# 번역 수정사항 반영
# Google Drive > GakumasTranslationDataKor
def ConvertDriveToOutput(drive_file_paths=None, bFullUpdate=False):
    if drive_file_paths is None:
        LOG_DEBUG(2, "No file list provided, scanning local drive")
        if os.path.exists(LOCALIZATION_DRIVE_PATH):
            drive_file_paths = [(LOCALIZATION_DRIVE_PATH, LOCALIZATION_FILE, os.path.basename(LOCALIZATION_DRIVE_PATH))]
        else:
            drive_file_paths = []

    if len(drive_file_paths) <= 0:
        LOG_INFO(2, "Localization file is not updated, skip")
        return [],[]
    
    converted_file_list = []
    error_file_list = []
    
    if len(drive_file_paths) > 0:
        input_path = LOCALIZATION_DRIVE_PATH
        output_path = LOCALIZATION_OUTPUT_PATH
        LOG_DEBUG(2, f"Start convert from drive to output '{input_path}' to '{output_path}'")
        try:
            XlsxToJson(input_path, output_path)
            converted_file_list.append(os.path.basename(LOCALIZATION_DRIVE_PATH))
        except Exception as e:
            LOG_ERROR(2, f"Error during Convert generic file from drive to output: {e}")
            logger.exception(e)
            error_file_list.append((os.path.basename(LOCALIZATION_DRIVE_PATH), e))
    return error_file_list, converted_file_list