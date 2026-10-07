from plugins.datacite.management.commands import deposit_doi


class Command(deposit_doi.Command):
    """Deprecated misspelling of deposit_doi, kept for existing scripts."""
