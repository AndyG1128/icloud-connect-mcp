from .errors import require

READ = frozenset({"connector_ping", "get_operation_status", "list_mail_folders", "search_messages",
                  "fetch_message", "fetch_attachment", "list_calendars", "get_events", "fetch_event"})
WRITE = frozenset({"send_message", "reply_message", "move_message", "set_message_read",
                   "create_event", "update_event", "delete_event", "expunge_messages"})


class Permissions:
    def __init__(self, config):
        self.config = config
        allowed = READ | (WRITE if config.profile == "full-access" else frozenset())
        if not config.permanent_expunge:
            allowed -= {"expunge_messages"}
        if config.permissions is not None:
            require(set(config.permissions) <= READ | WRITE, "CONFIG", "Unknown permission name.")
            allowed &= set(config.permissions)
        self.allowed = frozenset(allowed)

    def tool(self, name):
        require(name in self.allowed, "PERMISSION_DENIED", "Tool is not permitted by the operator profile.")

    def folder(self, folder):
        require(self.config.folders is None or folder in self.config.folders,
                "RESOURCE_DENIED", "Mail folder is not permitted by the operator.")

    def calendar(self, calendar_id):
        require(self.config.calendars is None or calendar_id in self.config.calendars,
                "RESOURCE_DENIED", "Calendar is not permitted by the operator.")
