import json, requests
from lib.TTConfig import *
from lib.TTOrder import *

class TTApi:
    session_token: str = None
    remember_token: str = None
    streamer_token: str = None
    streamer_uri: str = None
    streamer_websocket_uri: str = None
    streamer_level: str = None
    tt_uri: str = None
    wss_uri: str = None
    headers: dict = {}
    user_data: dict = {}
    use_prod: bool = False
    use_mfa: bool = False

    def __init__(self, tt_config: TTConfig = TTConfig()) -> None:
        self.headers["Content-Type"] = "application/json"
        self.headers["Accept"] = "application/json"
        self.tt_config = tt_config

        if self.tt_config.use_prod:
            self.tt_uri = self.tt_config.prod_uri
            self.tt_wss = self.tt_config.prod_wss
        else:
            self.tt_uri = self.tt_config.cert_uri
            self.tt_wss = self.tt_config.prod_wss

    def __post(
        self, endpoint: str = None, body: dict = {}, headers: dict = None
    ) -> requests.Response:
        if headers is None:
            headers = self.headers
        print(f"Sending POST to {self.tt_uri + endpoint}")
        response = requests.post(
            self.tt_uri + endpoint, data=json.dumps(body), headers=headers
        )
        if response.status_code == 201:
            return response.json()
        print(f"Error {response.status_code}")
        print(f"Endpoint: {endpoint}")
        print(f"Body: {body}")
        print(f"Headers: {headers}")
        print(f"Response: {response.text}")
        return None

    def __get(self, endpoint: str = None, params: dict = {}) -> requests.Response:
        response = requests.get(self.tt_uri + endpoint, headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()
        print(f"Error {response.status_code}")
        print(f"Endpoint: {endpoint}")
        print(f"Params: {params}")
        print(f"Headers: {self.headers}")
        print(f"Response: {response.text}")
        return None

    def login(self) -> bool:
        body = {
            "login": self.tt_config.username,
            "password": self.tt_config.password,
            "remember-me": True,
        }
        if self.tt_config.use_mfa is True:
            mfa = input("MFA: ")
            self.headers["X-Tastyworks-OTP"] = mfa

        response = self.__post("/sessions", body=body)
        if response is None:
            return False

        self.user_data = response["data"]["user"]
        self.session_token = response["data"]["session-token"]
        self.headers["Authorization"] = self.session_token

        if self.tt_config.use_mfa is True:
            del self.headers["X-Tastyworks-OTP"]

        return True

    def validate(self) -> bool:
        response = self.__post("/sessions/validate")
        if response is None:
            return False
        return True

    def fetch_accounts(self) -> bool:
        response = self.__get("/accounts")
        if response is None:
            return False
        self.user_data["accounts"] = response["data"]["items"]
        return True

    def get_quote_tokens(self) -> bool:
        response = self.__get("/quote-streamer-tokens")
        if response is None:
            return False

        self.streamer_token = response["data"]["token"]
        self.streamer_uri = response["data"]["dxlink-uri"]
        self.streamer_websocket_uri = response["data"]["websocket-url"]
        self.streamer_level = response["data"]["streamer-level"]
        return True

    def market_metrics(self, symbols: list[str] = []) -> any:
        symbols = ",".join(str(x) for x in symbols)
        query = {"symbols": symbols}
        response = self.__get(f"/market-metrics", params=query)
        return response

    def balances(self, account_number: str = None) -> any:
        if not account_number:
            return None
        response = self.__get(f"/accounts/{account_number}/balances")
        return response

    def logout(self) -> bool:
        response = self.__post("/sessions/logout")
        if response is None:
            return False
        return True