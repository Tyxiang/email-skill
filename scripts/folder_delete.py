from typing import Any
from common import SkillError, close_imap_safely, connect_imap, load_config, resolve_account, with_runtime


def handler(request: dict[str, Any]):
	data = request.get("data", {})
	name = data.get("name")
	if not isinstance(name, str) or not name.strip():
		raise SkillError("VALIDATION_ERROR", "data.name is required")
	name = name.strip()

	config = load_config()
	account_name, account_cfg = resolve_account(config, request.get("account"))

	client = connect_imap(account_cfg)
	try:
		status, detail = client.delete(name)
		if status != "OK":
			raise SkillError(
				"MAILBOX_ERROR",
				"Failed to delete mailbox",
				{"status": status, "detail": str(detail), "name": name},
			)
		return {"account": account_name, "name": name, "deleted": True}
	finally:
		close_imap_safely(client)


if __name__ == "__main__":
	raise SystemExit(with_runtime(handler))

