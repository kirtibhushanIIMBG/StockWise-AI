"""In-memory, per-browser session store. Data is temporary and lost on server restart."""
import copy
import threading
import uuid

import config
from data_processing import load_csv_path


class SessionStore:
    def __init__(self):
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def _ensure(self, sid: str) -> dict:
        if sid not in self._data:
            self._data[sid] = {"items": load_csv_path(config.SAMPLE_CSV), "source": "sample", "pending": None}
        return self._data[sid]

    def get_items(self, sid: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._ensure(sid)["items"])

    def source(self, sid: str) -> str:
        with self._lock:
            return self._ensure(sid)["source"]

    def set_items(self, sid: str, items: list[dict], source: str):
        with self._lock:
            s = self._ensure(sid)
            s["items"], s["source"] = copy.deepcopy(items), source

    def upsert(self, sid: str, items: list[dict]):
        with self._lock:
            s = self._ensure(sid)
            by_sku = {i["sku"]: i for i in s["items"]}
            for it in items:
                by_sku[it["sku"]] = copy.deepcopy(it)
            s["items"] = list(by_sku.values())
            s["source"] = "custom"


store = SessionStore()
