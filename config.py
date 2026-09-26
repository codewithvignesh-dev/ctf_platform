import os
from dotenv import load_dotenv

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "change-this-secret-key-in-production"
    )

    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_NAME = os.environ.get("DB_NAME", "ctf_platform")

    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads",
        "challenge_files"
    )

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    TAB_SWITCH_WARN_LIMIT = 2
    TAB_SWITCH_BLOCK_LIMIT = 3

    ALLOWED_ATTACHMENT_EXT = {
        "zip",
        "png",
        "jpg",
        "jpeg",
        "txt",
        "pdf",
        "pcap",
        "gz",
        "tar"
    }
