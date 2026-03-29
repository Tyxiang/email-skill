# AGENTS.md - Development Guidelines

## Build & Run Commands

### Running Scripts
```bash
# Run a script with JSON input via stdin (Windows PowerShell)
echo '{"requestId":"test","schemaVersion":"1.0","data":{...}}' | python scripts/mail_list.py

# Run a script with JSON input via stdin (Linux/Mac)
echo '{"requestId":"test","schemaVersion":"1.0","data":{...}}' | python3 scripts/mail_list.py
```

### Testing
No formal test framework is configured. Test scripts manually by piping JSON requests:
```bash
# List emails
echo '{"requestId":"test","schemaVersion":"1.0","data":{"maxResults":5}}' | python scripts/mail_list.py

# Read email
echo '{"requestId":"read","schemaVersion":"1.0","data":{"uid":"123"}}' | python scripts/mail_read.py

# Send email
echo '{"requestId":"send","schemaVersion":"1.0","data":{"to":["user@example.com"],"subject":"Test","bodyText":"Hello"}}' | python scripts/mail_send.py
```

### Linting & Formatting
No linting tools are currently installed. Add to `.venv` if needed:
```bash
./.venv/Scripts/pip.exe install ruff black mypy pytest
```

## Code Style Guidelines

### Imports
- Standard library imports first (alphabetically sorted)
- Third-party imports second
- Local imports last (from `common` module)
- Use `from typing import Any` for type hints
- Example:
```python
import base64
import json
from typing import Any

from common import SkillError, load_config, with_runtime
```

### Formatting
- **Indentation**: Tabs (not spaces)
- **Line length**: Keep lines reasonable (no strict limit enforced)
- **Quotes**: Double quotes for strings
- **Trailing commas**: Use in multi-line structures

### Type Hints
- Use Python 3.10+ style union syntax: `str | None` instead of `Optional[str]`
- Use `dict[str, Any]` for generic dictionaries
- Use `list[str]` for lists of strings
- Annotate function parameters and return types
- Example:
```python
def handler(request: dict[str, Any]) -> dict[str, Any]:
    data = request.get("data", {})
    uid: str | None = data.get("uid")
```

### Naming Conventions
- **Functions**: `snake_case` (e.g., `load_config`, `parse_recipients`)
- **Variables**: `snake_case` (e.g., `account_name`, `body_text`)
- **Classes**: `PascalCase` (e.g., `SkillError`, `_HTMLToTextParser`)
- **Constants**: `UPPER_CASE` (e.g., `SCHEMA_VERSION`)
- **Private functions**: Prefix with underscore (e.g., `_get_password_from_env`)

### Error Handling
- Use custom `SkillError` exception for all errors
- Always provide error code and human-readable message
- Include `details` dict for additional context when helpful
- Standard error codes:
  - `VALIDATION_ERROR`: Invalid input
  - `CONFIG_ERROR`: Configuration issues
  - `AUTH_ERROR`: Authentication failures
  - `NETWORK_ERROR`: Connection failures
  - `MAIL_OPERATION_ERROR`: IMAP/SMTP failures
  - `MAILBOX_ERROR`: Mailbox selection failures
  - `INTERNAL_ERROR`: Unexpected errors
- Example:
```python
if not uid:
    raise SkillError("VALIDATION_ERROR", "data.uid is required")
```

### Function Structure
- All scripts follow the same pattern:
  1. Imports at top
  2. Helper functions (if needed)
  3. `handler(request: dict[str, Any])` function
  4. `if __name__ == "__main__"` block calling `with_runtime(handler)`
- Use `finally` blocks for resource cleanup (IMAP/SMTP connections)
- Example:
```python
def handler(request: dict[str, Any]):
    # Validate input
    # Process request
    return { ... }

if __name__ == "__main__":
    raise SystemExit(with_runtime(handler))
```

### Resource Management
- Always use try/finally for IMAP/SMTP connections
- Use helper functions: `close_imap_safely()`, `close_smtp_safely()`
- Example:
```python
client = connect_imap(account_cfg)
try:
    # Use client
finally:
    close_imap_safely(client)
```

### JSON Contract
- All scripts: JSON request via stdin, JSON response via stdout
- Logs/errors: stderr
- Request format: `{"requestId": "...", "schemaVersion": "1.0", "data": {...}}`
- Success response: `{"ok": true, "requestId": "...", "data": {...}}`
- Error response: `{"ok": false, "requestId": "...", "error": {"code": "...", "message": "..."}}`

### Documentation
- Add docstrings to public functions
- Include type hints for all parameters
- Comment complex logic inline

## Configuration
- Copy `scripts/config.default.toml` to `scripts/config.toml`
- Set environment variables for authentication:
  - Password: `EMAIL_USERNAME`, `EMAIL_PASSWORD`
  - OAuth2: `EMAIL_OAUTH2_CLIENT_ID`, `EMAIL_OAUTH2_CLIENT_SECRET`, `EMAIL_OAUTH2_REFRESH_TOKEN`, `EMAIL_OAUTH2_TOKEN_URL`

## Project Structure
```
repository/
  scripts/
    common/             # Shared utilities (modular package)
      __init__.py       # Public API exports
      errors.py         # SkillError exception and constants
      validators.py     # Input validation
      config.py         # Configuration loading
      auth.py           # OAuth2 and password authentication
      imap_utils.py     # IMAP operations
      smtp_utils.py     # SMTP operations
      parsers.py        # Email parsing
      protocol.py       # JSON protocol handling
    config.default.toml # Default config template
    config.toml         # Local config (gitignored)
    folder_*.py         # Folder management scripts
    mail_*.py           # Email operation scripts
  requirements.txt      # Python dependencies
  README.md
  SKILL.md
  AGENTS.md
```
