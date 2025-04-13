import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PHONE = os.getenv("PHONE")
    SESSION_NAME = os.getenv("SESSION_NAME")
    SOURCES_FILE = os.getenv("SOURCES_FILE")
    TARGET_CHANNELS = [x.strip() for x in os.getenv("TARGET_CHANNELS").split(",")]
    KEYWORDS = [x.strip().lower() for x in os.getenv("KEYWORDS", "").split(",") if x]
    STOP_WORDS = [x.strip().lower() for x in os.getenv("STOP_WORDS", "").split(",") if x] 