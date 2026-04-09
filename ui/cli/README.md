# CLI Interface

Command-line interface for OpenHealth. The first and simplest way to interact with the system.

## Commands

```
openhealth init              # Set up the local workspace and SQLite index
openhealth ingest            # Ingest a file or directory
openhealth refresh-contexts  # Rebuild contexts and insights from indexed records
openhealth whoop-auth-url    # Generate a WHOOP OAuth authorization URL
openhealth whoop-sync        # Sync WHOOP data into the local workspace
openhealth bot-start         # Start the Telegram intake bot (polling mode)
```

See `openhealth --help` for the full command list.
