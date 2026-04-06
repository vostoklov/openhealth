"""Template connector for Health OS.

Copy this directory and modify it to create a new connector.
A connector ingests data from an external source and feeds it
into the Health OS pipeline via ``ingest_path``.

Connectors are intentionally simple Python modules — no abstract
base class is required.  The only contract is:

1. Accept a repo root ``Path`` and any connector-specific config.
2. Write one or more files into ``data/raw/inbox/<source-type>/``.
3. Call ``health_os.ingest.ingest_path()`` to run the standard
   parsing, archiving, and indexing flow.
"""

from pathlib import Path
from typing import Any, Dict

from health_os.ingest import ingest_path
from health_os.storage import ensure_repo_structure


def sync(
    root: Path,
    *,
    owner: str = "user",
    label: str | None = None,
    # Add connector-specific parameters here, for example:
    # api_key: str | None = None,
) -> Dict[str, Any]:
    """Pull data from the external source and ingest it.

    Parameters
    ----------
    root:
        Path to the Health OS repository root.
    owner:
        Owner label stored in the source manifest.
    label:
        Human-readable label for this import batch.

    Returns
    -------
    dict
        Summary returned by ``ingest_path``.
    """
    paths = ensure_repo_structure(root)

    # ------------------------------------------------------------------
    # Step 1: Fetch data from your source
    # ------------------------------------------------------------------
    # Example: call an API, read a local export, scrape a file, etc.
    #
    # raw_data = my_api_client.fetch(start, end)

    # ------------------------------------------------------------------
    # Step 2: Write fetched data to the inbox
    # ------------------------------------------------------------------
    # The inbox is the staging area for new files.  Each connector
    # should use its own subdirectory under ``data/raw/inbox/``.
    #
    # inbox_dir = paths.raw_inbox / "my-connector"
    # inbox_dir.mkdir(parents=True, exist_ok=True)
    # output_path = inbox_dir / "export.json"
    # output_path.write_text(json.dumps(raw_data), encoding="utf-8")

    # ------------------------------------------------------------------
    # Step 3: Ingest the file through the standard pipeline
    # ------------------------------------------------------------------
    # Replace "my-source-type" with one of the supported source types
    # defined in ``health_os.config.SOURCE_TYPES``, or add a new one.
    #
    # result = ingest_path(
    #     root=root,
    #     source_type="my-source-type",
    #     path=output_path,
    #     owner=owner,
    #     label=label,
    # )
    # return result

    raise NotImplementedError("Replace this with your connector logic.")
