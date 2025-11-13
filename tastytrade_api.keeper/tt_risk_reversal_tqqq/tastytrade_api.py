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

    def login(self, username: str, password: str) -> str:
        url = f"{self.base_url}/sessions"
        payload = {"login": username, "password": password}
        r = self.session.post(url, json=payload, timeout=15)
        if r.status_code != 201:
            raise RuntimeError(f"Login failed: {r.status_code} {r.text}")
        self.token = r.json()["data"]["session-token"]
        log.info("Login successful")
        self.session.headers["Authorization"] = self.token
        return self.token

    def logout(self):
        if not self.token:
            return
        try:
            url = f"{self.base_url}/sessions"
            self.session.delete(url, timeout=15)
            log.info("Logged out")
        except Exception as e:
            log.warning(f"Logout failed: {e}")
        finally:
            if "Authorization" in self.session.headers:
                del self.session.headers["Authorization"]
            self.token = None
            self.session.close()

    def get(self, endpoint: str, params: Dict = None, headers: Dict = None) -> Dict:
        if not self.token:
            raise RuntimeError("Not logged in")
        url = f"{self.base_url}{endpoint}"
        current_headers = self.session.headers.copy()
        if headers:
            current_headers.update(headers)
            
        r = self.session.get(url, params=params, headers=current_headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_option_chain(self, symbol: str, include_closed: bool = False) -> Dict:
        return self.get(
            f"/option-chains/{symbol}",
            params={"include-closed": str(include_closed).lower()}
        )

    def get_quotes(self, symbols: List[str]) -> Dict:
        """
        Fetches option quotes. Reverting to original REST endpoint.
        """
        return self.get(
            "/market-data/by-type", # <-- Revert to correct REST endpoint
            params={"equity-option": symbols} # <-- Correctly use equity-option parameter for OCC symbols
        )

    def get_spot_quote(self, symbol: str) -> float:
        """
        Fetches the spot quote for a single equity symbol.
        """
        # FIX: Must use the "equity" parameter for stock symbols
        data = self.get(
            "/market-data/by-type",
            params={"equity": [symbol]} # <-- FIX: Use "equity" parameter here
        )
        
        item = next((i for i in data["data"]["items"] if i["symbol"] == symbol), None)
        if not item:
            raise RuntimeError(f"{symbol} not in quote")

        # The mid price is standard for the /market-data endpoint
        mid = float(item.get("mid") or 0)
        
        if mid == 0:
             raise RuntimeError(f"Could not calculate valid mid price for {symbol}")
             
        return mid