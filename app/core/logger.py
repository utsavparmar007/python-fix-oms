import logging

def get_logger():
    # Set up a standard StreamHandler
    handler = logging.StreamHandler()

    # Create a simple formatter
    formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    logger = logging.getLogger("OMS_SYSTEM")
    logger.setLevel(logging.INFO)
    
    # Prevent adding multiple handlers if get_logger is called twice
    if not logger.handlers:
        logger.addHandler(handler)

    return logger
