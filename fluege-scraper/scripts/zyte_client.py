"""Zugriff auf Scrapy-Cloud-Jobs und deren Items."""

from collections.abc import Iterator

import requests


JOBS_URL = "https://app.zyte.com/api/jobs/list.json"
JOBS_UPDATE_URL = "https://app.zyte.com/api/jobs/update.json"
ITEMS_URL = "https://storage.zyte.com/items/{job_id}"
SOURCE_TAG = "airport-daily"
PENDING_TAG = "db-pending"
IMPORTED_TAG = "db-imported"
AIRPORT_SPIDERS = {
    "berlin_airport_flights",
    "frankfurt_airport_flights",
    "munich_airport_flights",
}
ITEM_PAGE_SIZE = 1000


class ZyteClient:
    """
    Die Klasse kapselt alle HTTP-Zugriffe auf Scrapy Cloud und den Item-Speicher.
    """

    def __init__(self, api_key: str, project_id: str):
        self.auth = (api_key, "")
        self.project_id = project_id

    @staticmethod
    def _json(response: requests.Response):
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"HTTP {response.status_code} für {response.url}: "
                f"{response.text[:2000]}"
            ) from exc
        return response.json()

    def list_pending_jobs(self) -> list[dict]:
        """Lädt fertige Airport-Jobs und filtert sie anhand der Import-Tags."""
        response = requests.get(
            JOBS_URL,
            params={"project": self.project_id, "state": "finished", "count": 100},
            auth=self.auth,
            timeout=30,
        )
        jobs = self._json(response).get("jobs", [])
        if not isinstance(jobs, list):
            raise RuntimeError("Scrapy Cloud lieferte keine gültige Jobliste")

        relevant = [job for job in jobs if job.get("spider") in AIRPORT_SPIDERS]
        selected = []
        for job in relevant:
            tags = set(job.get("tags") or [])
            if (
                SOURCE_TAG in tags
                and PENDING_TAG in tags
                and IMPORTED_TAG not in tags
            ):
                selected.append(job)
        if not selected and relevant:
            print("Gefundene fertige Airport-Jobs, aber ohne passende Import-Tags:")
            for job in relevant[:10]:
                print(
                    f"- {job.get('id', '?')} ({job.get('spider', '?')}), "
                    f"Tags: {job.get('tags') or []}"
                )
        return selected

    def iter_items(self, job_id: str) -> Iterator[dict]:
        """Liest sämtliche Job-Items seitenweise und ohne Größenlimit ein."""
        last_item_key = None
        while True:
            params: list[tuple[str, str | int]] = [
                ("count", ITEM_PAGE_SIZE),
                ("meta", "_key"),
            ]
            if last_item_key:
                params.append(("startafter", last_item_key))
            response = requests.get(
                ITEMS_URL.format(job_id=job_id),
                params=params,
                headers={"Accept": "application/json"},
                auth=self.auth,
                timeout=60,
            )
            items = self._json(response)
            if not isinstance(items, list):
                raise RuntimeError(f"Job {job_id} lieferte kein JSON-Array")
            if not items:
                return
            for item in items:
                if not isinstance(item, dict):
                    raise RuntimeError(f"Job {job_id} enthält ein ungültiges Item")
                yield item
                last_item_key = item.get("_key", last_item_key)
            if len(items) < ITEM_PAGE_SIZE:
                return
            if not last_item_key:
                raise RuntimeError(
                    f"Job {job_id}: Pagination ohne Item-_key unmöglich"
                )

    def mark_imported(self, job_id: str) -> None:
        """
        Markiert einen vollständig gespeicherten Job als importiert.
        Hierbei wird das db-pending-Tag entfernt und das db-imported-Tag hinzugefügt.
        """
        response = requests.post(
            JOBS_UPDATE_URL,
            data={
                "project": self.project_id,
                "job": job_id,
                "add_tag": IMPORTED_TAG,
                "remove_tag": PENDING_TAG,
            },
            auth=self.auth,
            timeout=30,
        )
        payload = self._json(response)
        if payload.get("status") != "ok":
            raise RuntimeError(f"Tags für Job {job_id} nicht aktualisiert: {payload}")
