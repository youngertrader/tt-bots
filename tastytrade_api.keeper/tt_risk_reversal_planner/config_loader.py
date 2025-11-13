# config_loader.py
from pathlib import Path
import configparser
from typing import Tuple

# Resolve config path relative to THIS file, regardless of CWD
BASE_DIR = Path(__file__).resolve().parent.parent  # config_loader.py → project root
CONFIG_PATH = BASE_DIR / "config" / "tt-ben.config"

def load_config() -> Tuple[configparser.ConfigParser, str, str, str, str, str]:
    """
    Load configuration from tt-ben.config.
    
    Returns:
        cfg: ConfigParser object
        username: Tastytrade username
        password: Tastytrade password
        account_number: Account number
        base_url: Base API URL
        default_symbol: Default underlying (e.g., TQQQ)
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
    section = "tastytrade" if use_prod else "tastytradesandbox"

    username = cfg.get(section, "username")
    password = cfg.get(section, "password")
    account_number = cfg.get("accountnumber", "self_directed")
    base_url = cfg.get("URI", "prod" if use_prod else "cert")
    default_symbol = cfg.get("options", "default_symbol", fallback="TQQQ").upper()

    return cfg, username, password, account_number, base_url, default_symbol