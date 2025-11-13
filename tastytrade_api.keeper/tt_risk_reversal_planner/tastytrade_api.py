# tastytrade_api.py
import requests
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

class TastytradeAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = None

    @property
    def is_logged_in(self) -> bool:
        """Checks if a session token is currently active."""
        return self.token is not None

    def login(self, username: str, password: str) -> str:
        url = f"{self.base_url}/sessions"
        payload = {"login": username, "password": password}
        r = self.session.post(url, json=payload, timeout=15)
        if r.status_code != 201:
            raise RuntimeError(f"Login failed: {r.status_code} {r.text}")
        self.token = r.json()["data"]["session-token"]
        log.info("Login successful")
        return self.token

    def logout(self):
        if not self.token:
            return
        try:
            url = f"{self.base_url}/sessions"
            self.session.delete(url, headers={"Authorization": self.token}, timeout=15)
            log.info("Logged out")
        except Exception as e:
            log.warning(f"Logout failed: {e}")
        finally:
            self.token = None
            self.session.close()

    def get(self, endpoint: str, params: Dict = None, headers: Dict = None) -> Dict:
        if not self.token:
            raise RuntimeError("Not logged in")
        url = f"{self.base_url}{endpoint}"
        auth_headers = {"Authorization": self.token}
        if headers:
            auth_headers.update(headers)
        r = self.session.get(url, params=params, headers=auth_headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_option_chain(self, symbol: str, include_closed: bool = False) -> Dict:
        return self.get(
            f"/option-chains/{symbol}",
            params={"include-closed": str(include_closed).lower()}
        )

    def get_quotes(self, symbols: List[str]) -> Dict:
        return self.get(
            "/market-data/by-type",
            params={"equity-option": symbols}
        )

    def get_spot_quote(self, symbol: str) -> float:
        data = self.get_quotes([symbol])
        item = next((i for i in data["data"]["items"] if i["symbol"] == symbol), None)
        if not item:
            raise RuntimeError(f"{symbol} not in quote")
        return float(item["mid"])