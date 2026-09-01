"""CLI: delete approved evidence documents from both GCS and Discovery Engine.

Every approved document is dual-homed: a GCS object under `approved/...` plus a
Discovery Engine document that references it by `gs://` URI. Deleting only one
side leaves the other dangling (a search hit with no evidence, or an orphaned
GCS object) — this script always deletes both, for every document_id it finds.

Defaults to a dry run that only prints what would be deleted; pass --yes to
actually delete. There is no undo: the bucket has no versioning configured
(see README's bootstrap steps), so a deleted object or document is gone.

Needs PROJECT_ID, GCS_BUCKET, and DISCOVERYENGINE_DATA_STORE_ID set (see README).

Usage:

    # preview only (default)
    python -m scripts.purge_approved_documents --domain hindustantimes.com

    # actually delete everything for one account
    python -m scripts.purge_approved_documents --domain hindustantimes.com --yes

    # actually delete every approved document, across all accounts
    python -m scripts.purge_approved_documents --all --yes
"""

import argparse
import sys

from google.api_core.exceptions import NotFound

from app.indexing import gemini
from app.jobs.pending_index import collect_document_paths
from app.settings import settings
from app.storage import gcs


def main() -> int:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--domain", help="only purge documents under approved/<domain>/")
    scope.add_argument("--all", action="store_true", help="purge every approved document, all accounts")
    parser.add_argument("--yes", action="store_true", help="actually delete (default is dry-run preview only)")
    args = parser.parse_args()

    prefix = f"approved/{args.domain}/" if args.domain else "approved/"
    paths_by_document_id = collect_document_paths(prefix)

    if not paths_by_document_id:
        print(f"no documents found under gs://{settings.gcs_bucket}/{prefix}")
        return 0

    print(f"found {len(paths_by_document_id)} document(s) under {prefix}:")
    for document_id, path in paths_by_document_id.items():
        print(f"  {document_id}  {path}")

    if not args.yes:
        print("\ndry run only — pass --yes to delete these from GCS and Discovery Engine")
        return 0

    for document_id, path in paths_by_document_id.items():
        try:
            gemini.delete(document_id)
        except NotFound:
            pass
        gcs.delete(path)

    print(f"\ndeleted {len(paths_by_document_id)} document(s) from GCS and Discovery Engine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
