import base64
import binascii
import html
import imaplib
import json
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


@dataclass
class SkillError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def get_oauth2_token(oauth_cfg: dict[str, Any]) -> str:
    """Fetches a new OAuth2 access token using the refresh token with retry logic."""
    token_url = oauth_cfg.get("token_url")
    refresh_token = oauth_cfg.get("refresh_token")
    client_id = oauth_cfg.get("client_id")
    client_secret = oauth_cfg.get("client_secret")

    if not all([token_url, refresh_token, client_id, client_secret]):
        raise SkillError("CONFIG_ERROR", "Missing one or more required OAuth2 fields for token refresh in account configuration.")

    if not isinstance(token_url, str):
        raise SkillError("CONFIG_ERROR", "OAuth2 token_url must be a string")

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")

    max_retries = 3
    base_delay = 1.0

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    body = response.read().decode('utf-8', errors='replace')
                    if response.status in (400, 401, 403):
                        raise SkillError("OAUTH_ERROR", f"OAuth2 token refresh failed (auth error): {response.status}", {"status": response.status, "body": body})
                    raise SkillError("OAUTH_ERROR", f"Failed to refresh OAuth2 token, status: {response.status}", {"status": response.status, "body": body})

                token_data = json.loads(response.read().decode("utf-8"))
                access_token = token_data.get("access_token")
                if not access_token:
                    raise SkillError("OAUTH_ERROR", "No access_token in OAuth2 response", {"response": token_data})
                return access_token
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                raise SkillError("OAUTH_ERROR", f"OAuth2 token refresh failed (auth error): {e.code}", {"status": e.code}) from e
            if attempt == max_retries:
                raise SkillError("OAUTH_ERROR", f"Failed to refresh OAuth2 token after {max_retries} attempts: {e.reason}") from e
        except urllib.error.URLError as e:
            if attempt == max_retries:
                raise SkillError("NETWORK_ERROR", f"Failed to connect to OAuth2 token URL after {max_retries} attempts: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise SkillError("OAUTH_ERROR", "Failed to parse OAuth2 token response as JSON") from e

        if attempt < max_retries:
            delay = base_delay * (2 ** (attempt - 1))
            time.sleep(delay)

    raise SkillError("NETWORK_ERROR", f"Failed to refresh OAuth2 token after {max_retries} attempts")


class _HTMLToTextParser(HTMLParser):
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "table", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in {"script", "style"}:
            self._ignore_depth += 1
            return
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignore_depth or not data:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        combined = "".join(self._parts)
        combined = combined.replace("\r\n", "\n").replace("\r", "\n")
        combined = re.sub(r"\n{3,}", "\n\n", combined)
        return "\n".join(line.rstrip() for line in combined.splitlines()).strip()


def _normalize_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise SkillError(
        "VALIDATION_ERROR",
        f"{field_name} must be a string or list of strings",
    )


def _safe_decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _decode_imap_value(raw: bytes | bytearray | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode("utf-8", errors="replace")
    return str(raw)


def _parse_imap_list(raw: str) -> list[str]:
    items: list[str] = []
    token: list[str] = []
    in_quotes = False
    escape = False

    for char in raw:
        if escape:
            token.append(char)
            escape = False
            continue
        if in_quotes:
            if char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
            else:
                token.append(char)
            continue
        if char == '"':
            in_quotes = True
            continue
        if char.isspace():
            if token:
                items.append("".join(token))
                token = []
            continue
        token.append(char)

    if token:
        items.append("".join(token))
    return items


def _extract_fetch_list(descriptor: str, attribute: str) -> list[str]:
    match = re.search(rf"{re.escape(attribute)} \((.*?)\)", descriptor)
    if not match:
        return []
    return _parse_imap_list(match.group(1))


def extract_fetch_tags(fetch_rows: list[Any] | tuple[Any, ...]) -> dict[str, list[str]]:
    flags: list[str] = []
    gmail_labels: list[str] = []

    for row in fetch_rows:
        descriptor: str | None = None
        if isinstance(row, tuple) and row:
            descriptor = _decode_imap_value(row[0])
        elif isinstance(row, (bytes, bytearray, str)):
            descriptor = _decode_imap_value(row)
        if not descriptor:
            continue

        flags = _extract_fetch_list(descriptor, "FLAGS") or flags
        gmail_labels = _extract_fetch_list(descriptor, "X-GM-LABELS") or gmail_labels

    system_tags = [item for item in flags if item.startswith("\\")]
    keywords = [item for item in flags if not item.startswith("\\")]

    tags: list[str] = []
    for item in [*flags, *gmail_labels]:
        if item not in tags:
            tags.append(item)

    return {
        "flags": flags,
        "systemTags": system_tags,
        "keywords": keywords,
        "gmailLabels": gmail_labels,
        "tags": tags,
    }


def _stderr_log(payload: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(payload, ensure_ascii=True) + "\n")


def load_config() -> dict[str, Any]:
    config_dir = Path(__file__).resolve().parent
    config_name = "config.toml"
    config_path = config_dir / config_name
    if not config_path.exists():
        raise SkillError(
            "CONFIG_ERROR",
            f"config file not found",
            {"configPath": str(config_path)},
        )
    with config_path.open("rb") as f:
        return tomllib.load(f)


def _get_nested_value(config: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    """Safely get a nested value from config using a list of keys."""
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def _merge_account_config(global_cfg: dict[str, Any], account_cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge global settings with account-specific settings (account takes precedence)."""
    merged = {}
    
    # Deep merge function for nested dicts
    def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    return deep_merge(global_cfg, account_cfg) if global_cfg else account_cfg


def validate_account_config(account_name: str, account_cfg: dict[str, Any]) -> None:
    """Validate account configuration and raise descriptive errors."""
    # Required fields
    if not account_cfg.get("email"):
        raise SkillError("CONFIG_ERROR", f"Account '{account_name}' missing required field: email")
    
    # Auth validation
    auth_cfg = account_cfg.get("auth", {})
    auth_type = auth_cfg.get("type", "username&password")
    
    if auth_type == "username&password":
        if not auth_cfg.get("username"):
            raise SkillError("CONFIG_ERROR", f"Account '{account_name}': auth.username is required for {auth_type}")
        if not auth_cfg.get("password"):
            raise SkillError("CONFIG_ERROR", f"Account '{account_name}': auth.password is required for {auth_type}")
    
    elif auth_type == "username&app-password":
        if not auth_cfg.get("username"):
            raise SkillError("CONFIG_ERROR", f"Account '{account_name}': auth.username is required for {auth_type}")
        if not auth_cfg.get("app-password"):
            raise SkillError("CONFIG_ERROR", f"Account '{account_name}': auth.app-password is required for {auth_type}")
    
    elif auth_type == "oauth2":
        oauth_cfg = auth_cfg.get("oauth2", {})
        required_oauth_fields = ["client_id", "client_secret", "refresh_token", "token_url"]
        for field in required_oauth_fields:
            if not oauth_cfg.get(field):
                raise SkillError(
                    "CONFIG_ERROR",
                    f"Account '{account_name}': auth.oauth2.{field} is required for OAuth2 authentication"
                )
    else:
        raise SkillError(
            "CONFIG_ERROR",
            f"Account '{account_name}': Unsupported auth type: {auth_type}. Supported: username&password, username&app-password, oauth2"
        )
    
    # IMAP validation
    imap_cfg = account_cfg.get("imap", {})
    if not imap_cfg.get("host"):
        raise SkillError("CONFIG_ERROR", f"Account '{account_name}': imap.host is required")
    if not imap_cfg.get("port"):
        raise SkillError("CONFIG_ERROR", f"Account '{account_name}': imap.port is required")
    
    # SMTP validation
    smtp_cfg = account_cfg.get("smtp", {})
    if not smtp_cfg.get("host"):
        raise SkillError("CONFIG_ERROR", f"Account '{account_name}': smtp.host is required")
    if not smtp_cfg.get("port"):
        raise SkillError("CONFIG_ERROR", f"Account '{account_name}': smtp.port is required")
    
    # TLS/STARTTLS conflict check
    tls_conflict_imap = imap_cfg.get("tls", False) and imap_cfg.get("starttls", False)
    tls_conflict_smtp = smtp_cfg.get("tls", False) and smtp_cfg.get("starttls", False)
    
    if tls_conflict_imap:
        raise SkillError(
            "CONFIG_ERROR",
            f"Account '{account_name}': imap.tls and imap.starttls cannot both be true"
        )
    if tls_conflict_smtp:
        raise SkillError(
            "CONFIG_ERROR",
            f"Account '{account_name}': smtp.tls and smtp.starttls cannot both be true"
        )


def resolve_account(config: dict[str, Any], requested_account: str | None) -> tuple[str, dict[str, Any]]:
    accounts = config.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        raise SkillError("CONFIG_ERROR", "[accounts] table is missing or empty in config.toml")

    if requested_account:
        account = accounts.get(requested_account)
        if not isinstance(account, dict):
            raise SkillError("CONFIG_ERROR", f"Account not found: {requested_account}")
        
        # Merge with global settings
        global_cfg = config.get("global", {})
        merged_cfg = _merge_account_config(global_cfg, account)
        
        # Validate the merged configuration
        validate_account_config(requested_account, merged_cfg)
        
        return requested_account, merged_cfg

    for account_name, account_cfg in accounts.items():
        if isinstance(account_cfg, dict) and account_cfg.get("default") is True:
            # Merge with global settings
            global_cfg = config.get("global", {})
            merged_cfg = _merge_account_config(global_cfg, account_cfg)
            
            # Validate the merged configuration
            validate_account_config(account_name, merged_cfg)
            
            return account_name, merged_cfg

    # Fallback to first account
    first_name = next(iter(accounts.keys()))
    first_cfg = accounts[first_name]
    if not isinstance(first_cfg, dict):
        raise SkillError("CONFIG_ERROR", f"Invalid account config shape for: {first_name}")
    
    # Merge with global settings
    global_cfg = config.get("global", {})
    merged_cfg = _merge_account_config(global_cfg, first_cfg)
    
    # Validate the merged configuration
    validate_account_config(first_name, merged_cfg)
    
    return first_name, merged_cfg


def read_request() -> dict[str, Any]:
    import io
    raw = ""
    if hasattr(sys.stdin, "buffer"):
        raw = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8").read().strip()
    else:
        raw = sys.stdin.read().strip()
    if not raw:
        return {"schemaVersion": SCHEMA_VERSION, "data": {}}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SkillError("VALIDATION_ERROR", "stdin must be valid JSON", {"error": str(exc)}) from exc

    if not isinstance(payload, dict):
        raise SkillError("VALIDATION_ERROR", "request root must be a JSON object")

    data = payload.get("data", {})
    if data is None:
        payload["data"] = {}
    elif not isinstance(data, dict):
        raise SkillError("VALIDATION_ERROR", "data must be an object")

    payload.setdefault("schemaVersion", SCHEMA_VERSION)
    return payload


def write_success(request: dict[str, Any], data: dict[str, Any]) -> None:
    response: dict[str, Any] = {
        "ok": True,
        "requestId": request.get("requestId"),
        "schemaVersion": request.get("schemaVersion", SCHEMA_VERSION),
        "data": data,
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=True))


def write_error(request: dict[str, Any] | None, exc: SkillError) -> None:
    response: dict[str, Any] = {
        "ok": False,
        "requestId": (request or {}).get("requestId"),
        "schemaVersion": (request or {}).get("schemaVersion", SCHEMA_VERSION),
        "error": exc.as_dict(),
    }
    _stderr_log(
        {
            "level": "ERROR",
            "code": exc.code,
            "message": exc.message,
            "requestId": (request or {}).get("requestId"),
        }
    )
    sys.stdout.write(json.dumps(response, ensure_ascii=True))


def write_unknown_error(request: dict[str, Any] | None, exc: Exception) -> None:
    response: dict[str, Any] = {
        "ok": False,
        "requestId": (request or {}).get("requestId"),
        "schemaVersion": (request or {}).get("schemaVersion", SCHEMA_VERSION),
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Unexpected error",
            "details": {"type": type(exc).__name__, "message": str(exc)},
        },
    }
    _stderr_log(
        {
            "level": "ERROR",
            "code": "INTERNAL_ERROR",
            "message": str(exc),
            "type": type(exc).__name__,
            "requestId": (request or {}).get("requestId"),
        }
    )
    sys.stdout.write(json.dumps(response, ensure_ascii=True))


def connect_imap(account_cfg: dict[str, Any]) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    imap_cfg = account_cfg["imap"]
    auth_cfg = account_cfg["auth"]

    host = imap_cfg.get("host")
    port = imap_cfg.get("port")
    tls = bool(imap_cfg.get("tls", True))
    starttls = bool(imap_cfg.get("starttls", False))
    timeout = imap_cfg.get("timeout", account_cfg.get("timeout", 30))
    ssl_verify = account_cfg.get("ssl_verify", True)
    ssl_ca_path = account_cfg.get("ssl_ca_path")

    try:
        # Create SSL context
        ssl_context = ssl.create_default_context()
        if not ssl_verify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        if ssl_ca_path:
            ssl_context.load_verify_locations(ssl_ca_path)

        # Connect
        if tls:
            client: imaplib.IMAP4_SSL | imaplib.IMAP4 = imaplib.IMAP4_SSL(
                host, int(port), timeout=int(timeout), ssl_context=ssl_context
            )
        else:
            client = imaplib.IMAP4(host, int(port), timeout=int(timeout))
            if starttls:
                client.starttls(ssl_context)

        # Authenticate
        auth_type = auth_cfg.get("type", "username&password")
        if auth_type == "oauth2":
            email = account_cfg.get("email")
            oauth_cfg = auth_cfg.get("oauth2", {})
            access_token = get_oauth2_token(oauth_cfg)
            auth_string = f"user={email}\1auth=Bearer {access_token}\1\1"
            auth_bytes = auth_string.encode("utf-8")
            status, detail = client.authenticate("XOAUTH2", lambda x=None: auth_bytes)
        else:
            username = auth_cfg.get("username")
            if auth_type == "username&app-password":
                password = auth_cfg.get("app-password")
            else:
                password = auth_cfg.get("password")
            status, detail = client.login(str(username), str(password))

        if status != "OK":
            _stderr_log(
                {
                    "level": "ERROR",
                    "code": "AUTH_ERROR",
                    "phase": "imap.login",
                    "status": status,
                    "detail": str(detail),
                }
            )
            raise SkillError("AUTH_ERROR", f"IMAP login failed ({auth_type})")

        return client
    except imaplib.IMAP4.error as exc:
        _stderr_log(
            {
                "level": "ERROR",
                "code": "AUTH_ERROR",
                "phase": "imap.auth",
                "message": str(exc),
            }
        )
        raise SkillError("AUTH_ERROR", "IMAP authentication failed") from exc
    except OSError as exc:
        _stderr_log(
            {
                "level": "ERROR",
                "code": "NETWORK_ERROR",
                "phase": "imap.connection",
                "message": str(exc),
            }
        )
        raise SkillError("NETWORK_ERROR", "IMAP connection failed") from exc


def connect_smtp(account_cfg: dict[str, Any]) -> smtplib.SMTP_SSL | smtplib.SMTP:
    smtp_cfg = account_cfg["smtp"]
    auth_cfg = account_cfg["auth"]

    host = smtp_cfg.get("host")
    port = smtp_cfg.get("port")
    tls = bool(smtp_cfg.get("tls", True))
    starttls = bool(smtp_cfg.get("starttls", False))
    timeout = smtp_cfg.get("timeout", account_cfg.get("timeout", 30))
    ssl_verify = account_cfg.get("ssl_verify", True)
    ssl_ca_path = account_cfg.get("ssl_ca_path")

    try:
        # Create SSL context
        ssl_context = ssl.create_default_context()
        if not ssl_verify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        if ssl_ca_path:
            ssl_context.load_verify_locations(ssl_ca_path)

        # Connect
        if tls:
            client: smtplib.SMTP_SSL | smtplib.SMTP = smtplib.SMTP_SSL(
                str(host), int(port), timeout=int(timeout), context=ssl_context
            )
        else:
            client = smtplib.SMTP(str(host), int(port), timeout=int(timeout))
            if starttls:
                client.starttls(context=ssl_context)

        # Authenticate
        auth_type = auth_cfg.get("type", "username&password")
        if auth_type == "oauth2":
            email = account_cfg.get("email")
            oauth_cfg = auth_cfg.get("oauth2", {})
            access_token = get_oauth2_token(oauth_cfg)
            auth_string = f"user={email}\1auth=Bearer {access_token}\1\1"
            client.auth("XOAUTH2", lambda x=None: auth_string)
        else:
            username = auth_cfg.get("username")
            if auth_type == "username&app-password":
                password = auth_cfg.get("app-password")
            else:
                password = auth_cfg.get("password")
            client.login(str(username), str(password))

        return client
    except smtplib.SMTPAuthenticationError as exc:
        raise SkillError("AUTH_ERROR", "SMTP auth failed", {"message": str(exc)}) from exc
    except smtplib.SMTPException as exc:
        raise SkillError("NETWORK_ERROR", "SMTP protocol error", {"message": str(exc)}) from exc
    except OSError as exc:
        raise SkillError("NETWORK_ERROR", "SMTP connection failed", {"message": str(exc)}) from exc


def close_imap_safely(client: imaplib.IMAP4_SSL | imaplib.IMAP4) -> None:
    try:
        client.logout()
    except Exception as exc:
        _stderr_log(
            {
                "level": "WARN",
                "code": "CLEANUP_ERROR",
                "phase": "imap.logout",
                "message": str(exc),
                "type": type(exc).__name__,
            }
        )


def close_smtp_safely(client: smtplib.SMTP_SSL | smtplib.SMTP) -> None:
    try:
        client.quit()
    except Exception as exc:
        _stderr_log(
            {
                "level": "WARN",
                "code": "CLEANUP_ERROR",
                "phase": "smtp.quit",
                "message": str(exc),
                "type": type(exc).__name__,
            }
        )


def get_imap_capabilities(client: imaplib.IMAP4_SSL | imaplib.IMAP4) -> set[str]:
    capabilities = getattr(client, "capabilities", ())
    normalized: set[str] = set()
    for item in capabilities:
        if isinstance(item, bytes):
            normalized.add(item.decode("utf-8", errors="replace").upper())
        else:
            normalized.add(str(item).upper())
    return normalized


def expunge_uids_safely(
    client: imaplib.IMAP4_SSL | imaplib.IMAP4,
    uids: str,
    *,
    folder: str,
) -> list[str]:
    capabilities = get_imap_capabilities(client)
    if "UIDPLUS" not in capabilities:
        raise SkillError(
            "MAIL_OPERATION_ERROR",
            "Safe expunge requires IMAP UIDPLUS support",
            {
                "folder": folder,
                "uids": uids.split(","),
                "capabilities": sorted(capabilities),
            },
        )

    expunged_uids: list[str] = []
    failed: list[dict[str, str]] = []
    for uid in uids.split(","):
        status, detail = client.uid("EXPUNGE", uid)
        if status == "OK":
            expunged_uids.append(uid)
        else:
            failed.append({"uid": uid, "status": str(status), "detail": str(detail)})

    if failed:
        raise SkillError(
            "MAIL_OPERATION_ERROR",
            "Failed to expunge one or more mails safely",
            {
                "folder": folder,
                "expungedUids": expunged_uids,
                "failed": failed,
            },
        )

    return expunged_uids


def get_sender_address(account_cfg: dict[str, Any], custom_from: Any = None) -> tuple[str, str]:
    if custom_from is not None:
        if not isinstance(custom_from, str) or not custom_from.strip():
            raise SkillError("VALIDATION_ERROR", "data.from must be a non-empty string when provided")
        custom_from_str = custom_from.strip()
        parsed_name, parsed_email = parseaddr(custom_from_str)
        if not parsed_email:
            return custom_from_str, custom_from_str
        return parsed_email, custom_from_str

    email_addr = account_cfg.get("email")
    if not isinstance(email_addr, str) or not email_addr.strip():
        raise SkillError("CONFIG_ERROR", "account email is missing")
    email_addr = email_addr.strip()

    display_name = account_cfg.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return email_addr, formataddr((display_name.strip(), email_addr))

    return email_addr, email_addr

def get_smtp_signatures(account_cfg: dict[str, Any]) -> tuple[str | None, str | None]:
    smtp_cfg = account_cfg.get("smtp")
    if smtp_cfg is None:
        return None, None
    if not isinstance(smtp_cfg, dict):
        raise SkillError("CONFIG_ERROR", "smtp config must be an object")

    signature_cfg = smtp_cfg.get("signature")
    if signature_cfg is None:
        return None, None
    if not isinstance(signature_cfg, dict):
        raise SkillError("CONFIG_ERROR", "smtp.signature must be an object")

    # Check if signature is explicitly disabled
    if signature_cfg.get("enabled", True) is False:
        return None, None

    signature_html = signature_cfg.get("html")
    signature_text = signature_cfg.get("text")

    if signature_html is not None and not isinstance(signature_html, str):
        raise SkillError("CONFIG_ERROR", "smtp.signature.html must be a string")
    if signature_text is not None and not isinstance(signature_text, str):
        raise SkillError("CONFIG_ERROR", "smtp.signature.text must be a string")

    signature_text = signature_text.rstrip() if isinstance(signature_text, str) else ""
    signature_html = signature_html.rstrip() if isinstance(signature_html, str) else ""

    return (signature_text or None, signature_html or None)

def apply_signatures(
    body_text: str | None,
    body_html: str | None,
    signature_text: str | None,
    signature_html: str | None,
) -> tuple[str | None, str | None]:
    if not signature_text and not signature_html:
        return body_text, body_html

    # Auto-generate text signature from HTML if not provided
    if not signature_text and signature_html:
        signature_text = html_to_text(signature_html)

    # Auto-generate HTML signature from text if not provided
    if not signature_html and signature_text:
        signature_html = text_to_html(signature_text)

    signed_text = body_text
    if signature_text and body_text is not None:
        signed_text = f"{body_text}\n\n{signature_text}" if body_text else signature_text

    signed_html = body_html
    if signature_html and body_html is not None:
        signed_html = f"{body_html}<br><br>{signature_html}"

    return signed_text, signed_html


def html_to_text(value: str) -> str:
    parser = _HTMLToTextParser()
    parser.feed(value)
    parser.close()
    text = html.unescape(parser.get_text())
    return re.sub(r"[ \t]+", " ", text).strip()


def text_to_html(value: str) -> str:
    return "<br>".join(html.escape(line) for line in value.splitlines())


def decode_mime_header(value: str | None) -> str:
    from email.header import decode_header, make_header
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def _clean_surrogate_chars(text: str) -> str:
    """Remove or replace Unicode surrogate characters that cannot be encoded in UTF-8."""
    if not text:
        return text
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def extract_text_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and part.get_content_disposition() in (None, "inline"):
                return _clean_surrogate_chars(part.get_content()).strip()
        return ""
    if message.get_content_type() == "text/plain":
        return _clean_surrogate_chars(message.get_content()).strip()
    return ""


def extract_html_body(message) -> str | None:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html" and part.get_content_disposition() in (None, "inline"):
                return _clean_surrogate_chars(part.get_content()).strip()
        return None
    if message.get_content_type() == "text/html":
        return _clean_surrogate_chars(message.get_content()).strip()
    return None


def ensure_body_alternatives(
    body_text: str | None,
    body_html: str | None,
) -> tuple[str | None, str | None]:
    normalized_text = body_text.strip() if isinstance(body_text, str) and body_text.strip() else None
    normalized_html = body_html.strip() if isinstance(body_html, str) and body_html.strip() else None

    if normalized_html and not normalized_text:
        normalized_text = html_to_text(normalized_html)
    if normalized_text and not normalized_html:
        return normalized_text, None
    return normalized_text, normalized_html


def select_mailbox(client: imaplib.IMAP4_SSL | imaplib.IMAP4, mailbox: str) -> None:
    candidates = [mailbox, f'"{mailbox}"']

    for name in candidates:
        status, detail = client.select(name)
        if status == "OK":
            return

    list_status, list_detail = client.list()
    decoded_list = []
    if list_status == "OK" and list_detail:
        decoded_list = [_safe_decode(row) for row in list_detail if isinstance(row, bytes)]

    raise SkillError(
        "MAILBOX_ERROR",
        f"Unable to select mailbox: {mailbox}",
        {
            "mailbox": mailbox,
            "attempted": candidates,
            "listStatus": list_status,
            "mailboxes": decoded_list,
        },
    )


def parse_base64_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    if raw_attachments is None:
        return []
    if not isinstance(raw_attachments, list):
        raise SkillError("VALIDATION_ERROR", "data.attachments must be an array when provided")

    attachments: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_attachments):
        if not isinstance(item, dict):
            raise SkillError("VALIDATION_ERROR", f"data.attachments[{idx}] must be an object")

        filename = item.get("filename")
        content_base64 = item.get("contentBase64")
        if not isinstance(filename, str) or not filename.strip():
            raise SkillError("VALIDATION_ERROR", f"data.attachments[{idx}].filename is required")
        if not isinstance(content_base64, str) or not content_base64.strip():
            raise SkillError("VALIDATION_ERROR", f"data.attachments[{idx}].contentBase64 is required")

        try:
            content_bytes = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SkillError(
                "VALIDATION_ERROR",
                f"data.attachments[{idx}].contentBase64 is not valid base64",
            ) from exc

        attachments.append({"filename": filename.strip(), "content": content_bytes})

    return attachments


def guess_attachment_type(filename: str) -> tuple[str, str]:
    guessed_type, _ = mimetypes.guess_type(filename)
    if not guessed_type:
        return "application", "octet-stream"
    maintype, subtype = guessed_type.split("/", 1)
    return maintype, subtype


def normalize_uids(value: Any) -> str:
    uids = _normalize_str_list(value, "uids")
    if not uids:
        raise SkillError("VALIDATION_ERROR", "uids cannot be empty")
    
    # Validate UID format: IMAP UIDs should be digits, '*', or ranges separated by ':'
    # Each UID element can be a single UID or a range (e.g., "123", "*", "1:10")
    uid_pattern = re.compile(r'^([0-9]+|\*)(:[0-9]+)?$')
    
    for uid_entry in uids:
        # Split by comma in case a single entry contains multiple UIDs
        for uid in uid_entry.split(','):
            uid = uid.strip()
            if not uid:
                continue
            if not uid_pattern.match(uid):
                raise SkillError(
                    "VALIDATION_ERROR",
                    f"Invalid UID format: {uid}. UIDs must be numeric, '*', or ranges (e.g., '123', '*', '1:10')"
                )
    
    return ",".join(uids)


def build_message(
    sender: str,
    to_list: list[str],
    subject: str,
    body_text: str | None,
    body_html: str | None,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    if not to_list:
        raise SkillError("VALIDATION_ERROR", "to cannot be empty")
    if not subject:
        raise SkillError("VALIDATION_ERROR", "subject cannot be empty")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to_list)
    message["Subject"] = subject

    if cc_list:
        message["Cc"] = ", ".join(cc_list)

    # Bcc is used for SMTP envelope recipients and should not be exposed in headers.
    _ = bcc_list

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    if body_text is not None:
        message.set_content(body_text)
    elif body_html:
        message.set_content("This message contains HTML content.")
    else:
        message.set_content("")

    if body_html:
        message.add_alternative(body_html, subtype="html")

    return message


def parse_recipients(data: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    to_list = _normalize_str_list(data.get("to"), "to")
    cc_list = _normalize_str_list(data.get("cc"), "cc")
    bcc_list = _normalize_str_list(data.get("bcc"), "bcc")
    return to_list, cc_list, bcc_list


from typing import Any, Callable


def with_runtime(handler: Callable[[dict[str, Any]], dict[str, Any]]) -> int:
    request: dict[str, Any] | None = None
    try:
        request = read_request()
        data = handler(request)
        write_success(request, data)
        return 0
    except SkillError as exc:
        write_error(request, exc)
        return 1
    except Exception as exc:
        write_unknown_error(request, exc)
        return 2
