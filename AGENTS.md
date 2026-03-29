# AGENTS.md - Developer Guide for email-skill

This document provides guidelines for agents working on this codebase.

## Project Overview

This is a Python-based email automation skill that provides IMAP/SMTP operations through JSON-over-stdin/stdout scripts. Scripts are located in `scripts/` and communicate via JSON requests/responses.

## Build, Test, and Run Commands

### Running Scripts

```bash
# Windows
echo '{"requestId":"test","schemaVersion":"1.0","data":{}}' | python scripts/mail_list.py

# Linux/Mac
echo '{"requestId":"test","schemaVersion":"1.0","data":{}}' | python3 scripts/mail_list.py
```

### Virtual Environment

```bash
# Activate virtual environment
# Windows
.venv\Scripts\python.exe scripts/mail_list.py

# Linux/Mac
source .venv/bin/activate
python3 scripts/mail_list.py
```

### Testing

There are currently no automated tests in this repository. When adding tests:
- Place test files in a `tests/` directory at the project root
- Use `pytest` as the test framework
- Run a single test: `pytest tests/test_file.py::test_function_name`

### Linting/Type Checking

No pre-configured linting tools exist. If adding them, consider:
- `ruff` for linting
- `mypy` for type checking

## Code Style Guidelines

### Python Version

- Use Python 3.11+ syntax and features
- Use built-in `tomllib` (Python 3.11+)

### Imports

- Standard library imports first, then third-party
- Use absolute imports from `common` (e.g., `from common import ...`)
- Group imports by type with blank lines between groups:
  ```python
  import json
  import smtplib
  from typing import Any
  
  from email.message import EmailMessage
  from email.utils import formataddr
  
  from common import SkillError, connect_imap
  ```

### Type Annotations

- Use type hints for all function parameters and return types
- Use `Any` when type is unknown
- Use `dict[str, Any]` for JSON-like dictionaries
- Use `list[str]`, `tuple[str, ...]` for collections
- Union types: prefer `X | None` over `Optional[X]`
- Use `X | Y` syntax (Python 3.10+)

### Naming Conventions

- Functions: `snake_case` (e.g., `connect_imap`, `load_config`)
- Classes: `PascalCase` (e.g., `SkillError`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `SCHEMA_VERSION`)
- Variables: `snake_case` (e.g., `account_name`, `account_cfg`)
- Private functions: prefix with `_` (e.g., `_extract_summary`)

### Error Handling

- Use the `SkillError` dataclass from `common.py` for all errors
- Error codes should be in `UPPER_SNAKE_CASE`:
  - `VALIDATION_ERROR` - Invalid input data
  - `CONFIG_ERROR` - Configuration issues
  - `AUTH_ERROR` - Authentication failures
  - `NETWORK_ERROR` - Network/connection issues
  - `MAIL_OPERATION_ERROR` - IMAP/SMTP operation failures
  - `MAILBOX_ERROR` - Mailbox selection/management issues
  - `INTERNAL_ERROR` - Unexpected errors (auto-handled)
- Include helpful error messages and details
- Chain exceptions using `from exc` for debugging
- Use `write_error()` and `write_unknown_error()` from `common` for responses

### Response Format

All scripts must follow this JSON contract:

```python
# Success
{
    "ok": True,
    "requestId": "...",
    "schemaVersion": "1.0",
    "data": { ... }
}

# Error
{
    "ok": False,
    "requestId": "...",
    "schemaVersion": "1.0",
    "error": {
        "code": "ERROR_CODE",
        "message": "Human readable message",
        "details": { ... }  # optional
    }
}
```

### Script Template

Follow this structure for new scripts:

```python
from typing import Any
from common import (
    SkillError,
    close_imap_safely,
    connect_imap,
    load_config,
    resolve_account,
    with_runtime,
)


def handler(request: dict[str, Any]) -> dict[str Any]:
    data = request.get("data", {})
    # Validation
    # ...
    
    config = load_config()
    account_name, account_cfg = resolve_account(config, request.get("account"))
    
    client = connect_imap(account_cfg)
    try:
        # IMAP operations
        # ...
        return {
            "account": account_name,
            # response fields
        }
    finally:
        close_imap_safely(client)


if __name__ == "__main__":
    raise SystemExit(with_runtime(handler))
```

### Data Classes

Use `@dataclass` for structured error types:

```python
@dataclass
class SkillError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        # ...
```

### JSON Handling

- Use `json` module for JSON serialization/deserialization
- Always use `ensure_ascii=True` for consistent output
- Use `json.dumps()` not `json.dump()` for stdout

### Logging

- Use `_stderr_log()` from `common` for structured logging
- Log levels: `INFO`, `WARN`, `ERROR`

### IMAP/SMTP Best Practices

- Always close connections in `finally` blocks using `close_imap_safely()` / `close_smtp_safely()`
- Use `select_mailbox()` to select folders with proper error handling
- Use `uid` commands where possible for consistency
- Handle connection timeouts
- Validate SSL certificates (default on)

### Configuration

- Configuration file: `scripts/config.toml`
- Sample: `scripts/config.sample.toml`
- Use `load_config()` from `common` to load
- Use `resolve_account()` to get account with fallback

### Key Modules in common.py

| Function | Purpose |
|----------|---------|
| `SkillError` | Error dataclass |
| `load_config()` | Load TOML config |
| `resolve_account()` | Get account config |
| `read_request()` | Parse stdin JSON |
| `write_success()` | Write success response |
| `write_error()` | Write error response |
| `connect_imap()` | IMAP connection |
| `connect_smtp()` | SMTP connection |
| `with_runtime()` | Request/response wrapper |

### Adding New Scripts

1. Create `scripts/mail_<operation>.py` or `scripts/folder_<operation>.py`
2. Use the script template above
3. Add documentation to `SKILL.md`
4. Test with sample JSON request

### Gitignore

The project ignores:
- `.venv/` - Virtual environment
- `config.toml` - Runtime configuration (contains secrets)
