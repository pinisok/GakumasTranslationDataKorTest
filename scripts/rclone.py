import os
import logging
import configparser
from typing import Callable, List, Union

from rclone_python import rclone
from rclone_python.remote_types import RemoteTypes
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    DownloadColumn,
)

from .log import *


def LoadRemoteConfig(name):
    config = configparser.ConfigParser()
    config.read(os.getenv("RCLONE_CONFIG"))
    if len(config) == 0:
        raise Exception(f"Failed to load rclone config")
    if not name in config:
        raise Exception(f"Config {name} not found from '{os.getenv('RCLONE_CONFIG')}'")
    if len(config[name]) == 0:
        raise Exception(f"Config {name} is empty")
    return config

def hasRemote(remote):
    return remote+":" in rclone.get_remotes()

def createRemote(remote, config:configparser.ConfigParser):
    if hasRemote(remote+":"):
        return
    with open(f"{os.getenv('HOME')}/.config/rclone/rclone.conf", "w") as f:
        config.write(f)
    if not hasRemote(remote+":"):
        raise Exception("Failed to create remote")

class Recorder:
    # Records all updates provided to the update function.
    def __init__(self):
        self.history = []

    def update(self, update: dict):
        self.history.append(update)

    def get_summary_stats(self, stat_name: str) -> List[any]:
        # returns the stats related to the overall transfer task.
        return [update[stat_name] for update in self.history]

    def get_subtask_stats(self, stat_name: str, task_name: str) -> List[any]:
        # returns stats related to a specific subtask.
        return [
            task_update[stat_name]
            for update in self.history
            for task_update in update["tasks"]
            if task_update["name"] == task_name
        ]
def generatePbar():
    pbar = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(binary_units=True),
        TimeRemainingColumn(),
        console=Console(stderr=True),
        redirect_stdout=False,
        redirect_stderr=True,
    )
    return pbar

def copy(source, destination):
    recorder = Recorder()
    LOG_INFO(2, f"Rclone copy from '{source}' to '{destination}'")
    rclone.copy(source, destination, listener=recorder.update, args=["--drive-shared-with-me", "--fast-list", "--transfers=32", "--no-check-certificate"], pbar=generatePbar())
    return recorder

def sync(source, destination):
    recorder = Recorder()
    LOG_INFO(2, f"Rclone sync from '{source}' to '{destination}'")
    rclone.sync(source, destination, listener=recorder.update, args=["--drive-shared-with-me", "--fast-list", "--transfers=32", "--no-check-certificate"], pbar=generatePbar())
    return recorder

def check(source, destination):
    LOG_INFO(2, f"Rclone check from '{source}' to '{destination}'")
    returncode, result = rclone.check(source, destination, args=["--drive-shared-with-me", "--fast-list", "--no-check-certificate"])
    return_result = []
    for obj in result:
        if obj[0] != '=':
            return_result.append([obj[0], os.path.relpath(os.path.join(destination, obj[1]), destination)])
    return return_result

def link(dest):
    result = rclone.link(dest, args=["--drive-shared-with-me", "--no-check-certificate"])
    return result

def init():
    if not rclone.is_installed():
        raise Exception("Rclone is not installed")
    version = rclone.version()[1:].split(".")
    if int(version[0]) < 1 or int(version[0]) == 1 and int(version[1]) < 69:
        raise Exception(f"Please install newer rclone client, Current version : {rclone.version()}. Need to newer or equal than v1.69")
    # print("Setting up rclone")
    remote_name = os.getenv("REMOTE_NAME")
    if remote_name == None:
        LOG_WARN(2, f"Environment 'REMOTE_NAME' is not set, use default name 'gakumas'")
        remote_name = "gakumas"
    if not hasRemote(remote_name):
        remote_config = LoadRemoteConfig(remote_name)
        createRemote(remote_name, remote_config)
    if not hasRemote(remote_name):
        raise Exception("Failed to create remote")


init()
