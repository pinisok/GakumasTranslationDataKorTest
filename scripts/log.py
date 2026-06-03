import logging
from rich.logging import RichHandler
from rich.console import Console


FORMAT = "%(message)s"
logging.basicConfig(format=FORMAT, datefmt="[%X]", handlers=[RichHandler(console=Console(stderr=True))])
logger = logging.getLogger("GakuToolkit")

def LOG_DEBUG(depth, msg, *args, **kwargs):
    if logger.isEnabledFor(logging.DEBUG):
        logger._log(logging.DEBUG, "\t"*depth + msg, args, kwargs)

def LOG_INFO(depth, msg, *args, **kwargs):
    if logger.isEnabledFor(logging.INFO):
        logger._log(logging.INFO, "\t"*depth + msg, args, kwargs)

def LOG_WARN(depth, msg, *args, **kwargs):
    if logger.isEnabledFor(logging.WARN):
        logger._log(logging.WARN, "\t"*depth + msg, args, kwargs)

def LOG_ERROR(depth, msg, *args, **kwargs):
    if logger.isEnabledFor(logging.ERROR):
        logger._log(logging.ERROR, "\t"*depth + msg, args, kwargs)

def AddLogHandler(handler):
    logger.addHandler(handler)
