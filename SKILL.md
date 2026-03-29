---
name: email-skill
description: This skill provides script-based email operations for an agent. It includes functionalities for managing mailboxes, reading/searching emails, sending/replying/forwarding emails, and managing attachments, allowing agents to perform comprehensive email_related tasks programmatically.
---

# email-skill

## 1. Overview

This skill provides script-based email operations for an agent. It includes functionalities for managing mailboxes, reading/searching emails, sending/replying/forwarding emails, and managing attachments, allowing agents to perform comprehensive email_related tasks programmatically.

## 2. Configuration

Configure this skill with `./scripts/config.toml`. Configuration method see `./scripts/config.sample.toml`.

- Start from `./scripts/config.sample.toml` and copy it to `./scripts/config.toml`.
- Fill in a real account entry in `config.toml` before using the skill.

## 3. Data Exchange Contract

### 3.1. Overview

All scripts follow the same JSON-over-stdin contract:

1. Agent sends one JSON object to stdin.
2. Script writes one JSON object to stdout.
3. Logs and diagnostics are written to stderr.

### 3.2. Request Schema

```json
{
  "requestId": "optional-trace-id",
  "schemaVersion": "1.0",
  "account": "optional-account-name-in-config",
  "data": {}
}
```

### 3.3. Success Response Schema

```json
{
  "ok": true,
  "requestId": "same-as-request",
  "schemaVersion": "1.0",
  "data": {}
}
```

Response `data` field definitions in this document describe possible fields; fields that are not applicable to a specific operation may be omitted.

### 3.4. Error Response Schema

```json
{
  "ok": false,
  "requestId": "same-as-request",
  "schemaVersion": "1.0",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "details": {}
  }
}
```

## 4. Scripts

### 4.1. Overview

All scripts are under `scripts/`.

### 4.2. `folder_create.py`

Create mailbox.

Request `data` fields:

- `name`: string, required

Response `data` fields:

- `account`: string - Account name used
- `name`: string - Mailbox name created
- `created`: boolean - `true` on success

### 4.3. `folder_delete.py`

Delete mailbox.

Request `data` fields:

- `name`: string, required

Response `data` fields:

- `account`: string - Account name used
- `name`: string - Mailbox name deleted
- `deleted`: boolean - `true` on success

### 4.4. `folder_list.py`

List mailboxes.

Request `data` fields: none (`{}`).

Response `data` fields:

- `account`: string - Account name used
- `mailboxes`: array of objects - Parsed mailbox list
  - `name`: string - Mailbox name
  - `delimiter`: string or null - Hierarchy delimiter reported by server
  - `flags`: string[] - IMAP LIST flags (e.g., `\HasNoChildren`, `\Noselect`)
  - `raw`: string - Original LIST row for diagnostics/compatibility

### 4.5. `folder_rename.py`

Rename mailbox.

Request `data` fields:

- `oldName`: string, required
- `newName`: string, required

Response `data` fields:

- `account`: string - Account name used
- `oldName`: string - Original mailbox name
- `newName`: string - New mailbox name
- `renamed`: boolean - `true` on success

### 4.6. `mail_copy.py`

Copy email(s) from one mailbox to another.

Request `data` fields:

- `uids`: string[] or comma-separated string, required
- `sourceFolder`: string, optional, default `INBOX`
- `targetFolder`: string, required

Response `data` fields:

- `account`: string - Account name used
- `uids`: string[] - UIDs copied
- `sourceFolder`: string - Source mailbox name
- `targetFolder`: string - Target mailbox name
- `copied`: boolean - `true` on success

### 4.7. `mail_delete.py`

Delete email(s).

Request `data` fields:

- `uids`: string[] or comma-separated string, required
- `folder`: string, optional, default `INBOX`
- `expunge`: boolean, optional, default `false` (soft delete)

Response `data` fields:

- `account`: string - Account name used
- `uids`: string[] - UIDs deleted
- `folder`: string - Mailbox name used
- `deleted`: boolean - `true` on success
- `expunged`: boolean - `true` if hard delete (`expunge`) was performed; otherwise `false`.

### 4.8. `mail_forward.py`

Forward email with optional additional body and attachments.

Behavior notes:

- If `bodyHtml` is provided without `bodyText`, the script derives a plain-text fallback automatically.
- When the original message contains HTML, the forwarded message preserves an HTML body alongside the plain-text forwarded content whenever possible.

Request `data` fields:

- `uid`: string, required
- `folder`: string, optional, default `INBOX`
- `to`: string or string[], required
- `cc`: string or string[], optional
- `bcc`: string or string[], optional
- `bodyText`: string, optional (prepended to forwarded content)
- `bodyHtml`: string, optional
- `attachments`: array of { filename: string, contentBase64: string }, optional

Response `data` fields:

- `account`: string - Account name used
- `forwarded`: boolean - `true` on success
- `uid`: string - UID of original email
- `sourceFolder`: string - Source mailbox name
- `to`: string[] - Recipient list
- `cc`: string[] - CC recipient list
- `bccCount`: integer - Number of BCC recipients
- `subject`: string - Forwarded subject (with `Fwd:` prefix)
- `originalAttachmentCount`: integer - Number of original attachments
- `additionalAttachmentCount`: integer - Number of additional attachments

Automatically includes original email and attachments in forwarded message.

### 4.9. `mail_mark.py`

Mark email(s) with various flags.

Request `data` fields:

- `uids`: string[] or comma-separated string, required
- `markType`: string, optional, default `read`. Allowed values:
  - `read`: Mark as read (`\Seen` flag)
  - `unread`: Mark as unread (remove `\Seen` flag)
  - `flag`: Add star/flag (`\Flagged` flag)
  - `unflag`: Remove star/flag
  - `spam`: Mark as spam (`\Spam` flag)
  - `notspam`: Mark as not spam
  - `junk`: Mark as junk (`\Junk` flag)
  - `notjunk`: Mark as not junk
- `folder`: string, optional, default `INBOX`

Response `data` fields:

- `account`: string - Account name used
- `uids`: string[] - UIDs marked
- `folder`: string - Mailbox name used
- `markType`: string - Mark type applied
- `flag`: string - IMAP flag name
- `marked`: boolean - `true` on success

### 4.10. `mail_move.py`

Move email(s) from one mailbox to another.

Request `data` fields:

- `uids`: string[] or comma-separated string, required
- `sourceFolder`: string, optional, default `INBOX`
- `targetFolder`: string, required

Response `data` fields:

- `account`: string - Account name used
- `uids`: string[] - UIDs moved
- `sourceFolder`: string - Source mailbox name
- `targetFolder`: string - Target mailbox name
- `moved`: boolean - `true` on success

### 4.11. `mail_read.py`

Read email content and metadata.

Behavior notes:

- If an attachment cannot be decoded, the script returns a structured `MAIL_OPERATION_ERROR` instead of an internal crash.

Request `data` fields:

- `uid`: string, required
- `folder`: string, optional, default `INBOX`

This command attempts to mark the message as read (`\Seen`) after successful fetch. If marking as read fails, the script will return an error and no content will be returned.

Response `data` fields:

- `account`: string - Account name used
- `uid`: string - Email UID
- `folder`: string - Mailbox name used
- `subject`: string - Email subject
- `from`: string - Sender address
- `to`: string - Recipient addresses
- `cc`: string - CC addresses (empty if not present)
- `date`: string - Email date header value
- `messageId`: string - Email `Message-ID`
- `bodyText`: string - Plain text body (`null` if no text body)
- `bodyHtml`: string - HTML body (`null` if no HTML body)
- `attachments`: array of { filename: string, contentBase64: string, size: integer } - Attachment list
- `attachmentCount`: integer - Number of attachments
- `flags`: string[] - Raw IMAP flags reported by server
- `systemTags`: string[] - System flags such as `\Seen`, `\Answered`, `\Flagged`
- `keywords`: string[] - Non-system IMAP keywords/tags
- `gmailLabels`: string[] - Gmail labels when server supports `X-GM-LABELS`
- `tags`: string[] - Combined deduplicated list of flags and labels

### 4.12. `mail_reply.py`

Reply email.

Behavior notes:

- If `bodyHtml` is provided without `bodyText`, the script derives a plain-text fallback automatically.
- The script keeps quoted original content aligned between the plain-text and HTML reply bodies whenever possible.

Request `data` fields:

- `uid`: string, required
- `folder`: string, optional, default `INBOX`
- `bodyText`: string, optional
- `bodyHtml`: string, optional
- `replyAll`: boolean, optional, default `false`
- `priority`: string, optional, default `normal`. Allowed: `high`, `normal`, `low`
- `readReceipt`: boolean, optional, default `false`
- `inReplyTo`: string, optional (overrides auto-generated reply thread header)
- `references`: string, optional (overrides auto-generated references header)
- `attachments`: array of { filename: string, contentBase64: string }, optional

Response `data` fields:

- `account`: string - Account name used
- `uid`: string - UID of original email
- `folder`: string - Mailbox name used
- `sent`: boolean - `true` on success
- `to`: string[] - Reply recipients
- `cc`: string[] - CC recipients
- `attachmentCount`: integer - Number of attachments sent
- `priority`: string - Priority applied
- `readReceipt`: boolean - Read receipt setting applied
- `inReplyTo`: string - `In-Reply-To` header used
- `references`: string - `References` header used
- `subject`: string - Reply subject (with `Re:` prefix)

### 4.13. `mail_list.py`

List emails using IMAP search query.

Request `data` fields:

- `query`: string, optional, default `UNSEEN` (IMAP search syntax, e.g., "FROM user@example.com", "SUBJECT test", "ALL")
- `folder`: string, optional, default `INBOX`
- `maxResults`: integer, optional, default `10`

The script first tries `UID SEARCH CHARSET UTF-8 <query>`, then falls back to `UID SEARCH <query>` for compatibility.

Response `data` fields:

- `account`: string - Account name used
- `folder`: string - Mailbox name searched
- `query`: string - Search query executed
- `uids`: string[] - Matching email UIDs
- `count`: integer - Number of results returned
- `totalCount`: integer - Total number of matches before limiting by `maxResults`
- `hasMore`: boolean - `true` if more results exist beyond `maxResults`
- `summary`: array - Summary list:
  - `uid`: string
  - `subject`: string
  - `from`: string
  - `date`: string
  - `flags`: string[] - Raw IMAP flags reported by server
  - `systemTags`: string[] - System flags such as `\Seen`, `\Answered`, `\Flagged`
  - `keywords`: string[] - Non-system IMAP keywords/tags
  - `gmailLabels`: string[] - Gmail labels when server supports `X-GM-LABELS`
  - `tags`: string[] - Combined deduplicated list of flags and labels

### 4.14. `mail_send.py`

Send a new email.

Behavior notes:

- If both `bodyText` and `bodyHtml` are provided, clients typically display the HTML part and keep the text part as a compatibility fallback.
- If only `bodyHtml` is provided, the script derives a plain-text fallback automatically.

Request `data` fields:

- `to`: string or string[], required
- `subject`: string, required
- `bodyText`: string, optional
- `bodyHtml`: string, optional
- `cc`: string or string[], optional
- `bcc`: string or string[], optional
- `from`: string, optional, defaults to account email
- `priority`: string, optional, default `normal`. Allowed: `high`, `normal`, `low`
- `readReceipt`: boolean, optional, default `false`
- `inReplyTo`: string, optional
- `references`: string, optional
- `attachments`: array of { filename: string, contentBase64: string }, optional

Response `data` fields:

- `account`: string - Account name used
- `sent`: boolean - `true` on success
- `to`: string[] - Recipient list
- `cc`: string[] - CC recipient list
- `bccCount`: integer - Number of BCC recipients
- `attachmentCount`: integer - Number of attachments sent
- `priority`: string - Priority applied
- `readReceipt`: boolean - Read receipt setting applied
- `inReplyTo`: string - `In-Reply-To` header used
- `references`: string - `References` header used
- `subject`: string - Sent email subject

## 5. Examples

Suppose the mailbox is already configured.

**Windows PowerShell**

```powershell
# List new emails
@'
{"requestId":"req-list","schemaVersion":"1.0","data":{"maxResults":10}}
'@ | python scripts/mail_list.py

# Read the new email with UID `2`
@'
{"requestId":"req-read","schemaVersion":"1.0","data":{"uid":"2"}}
'@ | python scripts/mail_read.py

# Reply to the new email with UID `2`
@'
{"requestId":"req-reply","schemaVersion":"1.0","data":{"uid":"2","bodyText":"Thanks. Received and noted."}}
'@ | python scripts/mail_reply.py
```

**Linux/Mac Terminal**

```bash
# List new emails
echo '{"requestId":"req-list","schemaVersion":"1.0","data":{"maxResults":10}}' | python3 scripts/mail_list.py

# Read the new email with UID `2`
echo '{"requestId":"req-read","schemaVersion":"1.0","data":{"uid":"2"}}' | python3 scripts/mail_read.py

# Reply to the new email with UID `2`
echo '{"requestId":"req-reply","schemaVersion":"1.0","data":{"uid":"2","bodyText":"Thanks. Received and noted."}}' | python3 scripts/mail_reply.py
```