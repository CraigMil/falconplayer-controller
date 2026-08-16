"""Low-level HTTP client for the FPP REST API."""

from __future__ import annotations

import httpx


class FPPClient:
    def __init__(self, host: str, timeout: float = 10.0) -> None:
        base = host.rstrip("/")
        if not base.startswith("http"):
            base = f"http://{base}"
        self._base = base
        self._http = httpx.Client(base_url=f"{base}/api", timeout=timeout)

    # ------------------------------------------------------------------ status

    def status(self) -> dict:
        return self._get("/fppd/status")

    def system_info(self) -> dict:
        return self._get("/system/info")

    # --------------------------------------------------------------- playlists

    def list_playlists(self) -> list[str]:
        return self._get("/playlists")

    def start_playlist(self, name: str, repeat: bool = False) -> dict:
        repeat_flag = 1 if repeat else 0
        return self._get(f"/playlist/{name}/start/{repeat_flag}")

    def stop(self) -> dict:
        return self._get("/playlists/stop")

    def stop_gracefully(self) -> dict:
        return self._get("/playlists/stopgracefully")

    # --------------------------------------------------------------- sequences

    def list_sequences(self) -> list[str]:
        return self._get("/sequence")

    def start_sequence(self, name: str, start_second: int = 0) -> dict:
        return self._get(f"/sequence/{name}/start/{start_second}")

    def stop_sequence(self) -> dict:
        return self._get("/sequence/current/stop")

    # ------------------------------------------------------------------ media

    def list_media(self) -> dict:
        return self._get("/media")

    # -------------------------------------------------------------- file upload

    def upload_file(self, file_type: str, filename: str, data: bytes) -> httpx.Response:
        """Upload a file. file_type: 'images', 'videos', or 'sequences'."""
        resp = self._http.post(
            f"/file/{file_type}/{filename}",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        resp.raise_for_status()
        return resp

    # -------------------------------------------------------------- overlays

    def list_overlay_models(self) -> list:
        return self._get("/overlays/models")

    def get_overlay_model(self, name: str) -> dict:
        return self._get(f"/overlays/model/{name}")

    def set_overlay_state(self, model: str, state: int) -> dict:
        """state: 0=off, 1=override, 2=overlay"""
        return self._put(f"/overlays/model/{model}/state", {"state": state})

    def clear_overlay(self, model: str) -> dict:
        return self._get(f"/overlays/model/{model}/clear")

    def fill_overlay(self, model: str, r: int, g: int, b: int) -> dict:
        return self._put(f"/overlays/model/{model}/fill", {"r": r, "g": g, "b": b})

    def text_overlay(self, model: str, **kwargs) -> dict:
        return self._put(f"/overlays/model/{model}/text", kwargs)

    # ---------------------------------------------------------------- helpers

    def _get(self, path: str) -> dict:
        resp = self._http.get(path)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {}

    def _put(self, path: str, body: dict) -> dict:
        resp = self._http.put(path, json=body)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "FPPClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
