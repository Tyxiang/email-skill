# email-skill

This skill provides script-based email operations for an agent. It includes functionalities for managing mailboxes and sending/replying to emails, allowing agents to perform email-related tasks programmatically.

## 1. Features

- IMAP mailbox operations: read, list, mark, move, delete, copy.
- SMTP mailbox operations: send, reply, forward.
- Attachment handling, signature appending, reply-all deduplication.
- Dual-format body handling: prefer HTML for capable clients while preserving plain-text fallbacks.
- Mailbox folder creation, deletion, renaming, listing.
- JSON requests received from stdin.
- JSON responses written to stdout.
- Structured errors and diagnostic logs written to stderr.
- Flexible local configuration via `config.sample.toml` and `config.toml`.
- Support Multi-account.
- Support authentication of username & password / username & app-password / OAuth2 .

## 2. Structure

```
scripts/
  common.py               # Common utilities and core logic.
  config.sample.toml      # Safe example config file (with detailed comments).
  config.toml             # Local runtime config (gitignored).
  folder_*.py             # Folder management scripts.
  mail_*.py               # Email operation scripts.
README.md                 # Project readme.
SKILL.md                  # Skill documentation (comprehensive guide).
tests/
  all.py                  # Orchestrates the full real-account test run.
  unit/
    folder_*.py           # Unit tests for folder management scripts.
    mail_*.py             # Unit tests for email operation scripts.
```

## 3. Main Scripts

- `folder_create.py` Create mailbox folders.
- `folder_delete.py` Delete mailbox folders.
- `folder_list.py` List mailbox folders.
- `folder_rename.py` Rename mailbox folders.
- `mail_copy.py` Copy emails between folders.
- `mail_delete.py` Delete emails.
- `mail_forward.py` Forward emails with optional extra attachments.
- `mail_list.py` List emails and return summaries.
- `mail_mark.py` Mark emails read, unread, flagged, spam, or junk.
- `mail_move.py` Move emails between folders.
- `mail_read.py` Read email content and metadata.
- `mail_reply.py` Reply to emails with optional reply-all and attachments.
- `mail_send.py` Send new emails with optional attachments and signatures.

## 4. Contribution & License

Issues and PRs are welcome!

MIT License - Tyxiang

