"""ADV pipeline: file converters and folder-level orchestration.

Submodules:
- adv_encode: text encoding (_encode, _processEMtag)
- adv_record: DataFrame/record processing
- adv_merge: merge/diff/conversion logic
"""

import os, fnmatch
from io import StringIO

from .helper import (
    Helper_GetFilesFromDir, Helper_GetFilesFromDirByDate,
    load_cache_date, save_cache_date,
)
from .log import LOG_DEBUG, LOG_INFO, LOG_ERROR, logger

# Re-export submodule functions for backward compatibility
from .adv_encode import _encode, _processEMtag, END_EM_LENGTH
from .adv_record import (
    _internalOverrideXlsxColumn,
    _internalReadXlsx,
    _internalXlsxDataFrameProcess,
    _internalXlsxRecordsProcess,
    _internalCsvWriter,
)
from .adv_merge import (
    _internalTxtToScv,
    _internalCsvToDataFrame,
    _internalUpdateDataFrame,
    _internalDataFrameToXlsx,
    _replace_at_offset,
    _internalCsvToTxt,
)
from .paths import (
    GIT_ADV_PATH, ADV_ORIGINAL_PATH, ADV_REMOTE_PATH, ADV_DRIVE_PATH,
    ADV_TEMP_PATH, ADV_OUTPUT_PATH, ADV_CACHE_FILE,
)


# ============================================================
# File Converters
# ============================================================


def XlsxToCsv(read_fp, write_fp, origin_path: str) -> None:
    """Convert translated XLSX → CSV for game engine import."""
    xlsx_dataframe = _internalReadXlsx(read_fp)
    _internalXlsxDataFrameProcess(xlsx_dataframe, origin_path)
    xlsx_records = xlsx_dataframe.to_dict(orient="records")
    xlsx_records = _internalXlsxRecordsProcess(xlsx_records)
    _internalCsvWriter(write_fp, xlsx_records)


def CsvToTxt(read_fp, write_path: str, original_path: str) -> None:
    """Merge CSV translations into original TXT game script."""
    csv_strings = "".join(read_fp.readlines())
    with open(original_path, "r", encoding='utf-8') as write_fp:
        txt_strings = "".join(write_fp.readlines())
    txt_strings = _internalCsvToTxt(csv_strings, txt_strings)
    with open(write_path, "w", encoding="utf-8") as write_fp:
        write_fp.write(txt_strings)


def XlsxToTxt(input_path: str, write_path: str, original_path: str) -> None:
    """Convert translated XLSX → TXT (XLSX→CSV→TXT pipeline)."""
    with open(input_path, "rb") as input_fp:
        csvIO = StringIO()
        XlsxToCsv(input_fp, csvIO, os.path.basename(write_path))
    csvIO.seek(0)
    CsvToTxt(csvIO, write_path, original_path)


def TxtToXlsx(input_path: str, output_path: str, file_name: str) -> list[str]:
    """Convert original TXT → XLSX for translation. Returns list of warnings."""
    with open(input_path, "r", encoding="utf-8") as input_fp:
        csv = _internalTxtToScv(input_fp, file_name)
    dataframe = _internalCsvToDataFrame(csv)
    warnings = []

    if os.path.exists(output_path):
        original_fp = open(output_path, "rb")
        LOG_DEBUG(4, "Try to update original file")
        dataframe, warnings = _internalUpdateDataFrame(dataframe, original_fp, file_name)
        original_fp.close()

    LOG_DEBUG(4, "Write result to file")
    dir_path = os.path.dirname(output_path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path)
        
    write_fp = open(output_path, "wb")
    _internalDataFrameToXlsx(dataframe, write_fp)
    write_fp.close()
    return warnings


# ============================================================
# Parallel wrappers
# ============================================================


def XlsxToTxt_parallels(obj):
    """Parallel worker for XLSX→TXT conversion."""
    input_path, filename = obj
    output_path = os.path.join(ADV_OUTPUT_PATH, filename[:-5] + ".txt")
    original_path = os.path.join(ADV_ORIGINAL_PATH, filename[:-5] + ".txt")
    converted_file_list = []
    error_file_list = []
    try:
        XlsxToTxt(input_path, output_path, original_path)
        converted_file_list.append(filename)
    except Exception as e:
        LOG_ERROR(2, f"Error converting {filename}: {e}")
        error_file_list.append((e, filename))
    return error_file_list, converted_file_list


def TxtToXlsx_parallels(obj):
    """Parallel worker for TXT→XLSX conversion."""
    input_path, output_path, filename = obj
    try:
        warnings = TxtToXlsx(input_path, output_path, filename)
        return {filename: warnings} if warnings else {}
    except Exception as e:
        LOG_ERROR(2, f"Error: {e}")
        logger.exception(e)
        return {}


# ============================================================
# Folder processing helpers
# ============================================================


ADV_BLACKLIST_FILE = [
    "musics.txt",
    "adv_warmup.txt",
    "adv_produce_lesson_*",
    "adv_produce-lesson_*"
]

ADV_BLACKLIST_FOLDER = [
    "pstep",
    "pweek",
]


def _internalGetOutputPath(filename: str) -> str:
    """Extract output folder name from an ADV filename."""
    splitted_name = filename[4:-4].split("_")
    folder_name = splitted_name[0]
    if splitted_name[0] == "pstory":
        folder_name += "_" + splitted_name[1]
    folder_name = folder_name.split("-")[0]
    return folder_name


def _filter_adv_files(file_paths):
    """Apply blacklist and map to (input_path, output_xlsx_path, filename)."""
    file_list = []
    for abs_path, rel_path, filename in file_paths:
        if any(fnmatch.fnmatch(filename, rule) for rule in ADV_BLACKLIST_FILE):
            continue
        foldername = _internalGetOutputPath(filename)
        if foldername in ADV_BLACKLIST_FOLDER:
            continue
        input_path = rel_path
        output_path = os.path.join(ADV_DRIVE_PATH, foldername, filename[:-4] + ".xlsx")
        file_list.append((input_path, output_path, filename))
    return file_list


def _convert_xlsx_to_txt_batch(drive_file_paths):
    """Run XlsxToTxt in parallel via multiprocessing Pool.

    Returns (error_file_list, converted_file_list).
    """
    from .parallel import run_parallel, collect_errors_and_successes

    results = run_parallel(
        XlsxToTxt_parallels,
        [(abs_path, filename) for abs_path, rel_path, filename in drive_file_paths],
        desc="XLSX→TXT",
    )
    return collect_errors_and_successes(results)


# ============================================================
# Folder Processors (public API)
# ============================================================


def UpdateOriginalToDrive():
    """Update: Campus-Adv-txts → Google Drive XLSX."""
    last_update_date = load_cache_date(ADV_CACHE_FILE)
    if last_update_date:
        LOG_DEBUG(2, f"Load update date {last_update_date}")
    save_cache_date(ADV_CACHE_FILE)

    if last_update_date is not None:
        LOG_DEBUG(2, "Check git diff")
        original_file_paths = Helper_GetFilesFromDirByDate(
            last_update_date, GIT_ADV_PATH, ".txt", "adv_"
        )
    else:
        original_file_paths = []
    if len(original_file_paths) <= 0:
        LOG_INFO(2, "ADV is not updated, skip")
        return [], {}

    file_list = _filter_adv_files(original_file_paths)
    LOG_INFO(2, f"Updating {len(file_list)} adv files")
    from .parallel import run_parallel, collect_dict_results

    results = run_parallel(TxtToXlsx_parallels, file_list, desc="TXT→XLSX")
    all_warnings = collect_dict_results(results)

    return file_list, all_warnings


def ConvertDriveToOutput(drive_file_paths=None, bFullUpdate=False):
    """Convert: Google Drive XLSX → GakumasTranslationDataKor TXT."""
    if drive_file_paths is None:
        LOG_DEBUG(2, "No file list provided, scanning local drive")
        drive_file_paths = Helper_GetFilesFromDir(ADV_DRIVE_PATH, ".xlsx", "adv_")
    if len(drive_file_paths) <= 0:
        LOG_INFO(2, "ADV is not updated, skip")
        return [], []
    LOG_INFO(2, f"Converting {len(drive_file_paths)} adv files")

    return _convert_xlsx_to_txt_batch(drive_file_paths)
