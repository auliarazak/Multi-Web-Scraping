import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "scrape.db")


RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")

DEFAULT_HEADLESS = True
DEFAULT_LIMIT = 60
SCROLL_ROUNDS = 10
SCROLL_WAIT = 1.4

DEFAULT_REVIEW_LOCATION = ""