from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "collector.log"

POLITE_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3
