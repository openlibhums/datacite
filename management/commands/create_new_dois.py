from django.core.management.base import BaseCommand

from plugins.datacite import utils, plugin_settings
from submission import models as sm
from journal import models as jm
from identifiers import models as im


class Command(BaseCommand):
    """Creates DOIs for articles without DOIs."""

    help = "For all articles without a DOI create one. "

    def add_arguments(self, parser):
        parser.add_argument('journal_code')
        parser.add_argument('--dry_run', action="store_true", default=False)

    def handle(self, *args, **options):
        journal_code = options.get('journal_code')
        dry_run = options.get('dry_run')
        journal = jm.Journal.objects.get(code=journal_code)
        articles = sm.Article.objects.filter(
            journal=journal,
            date_published__isnull=False,
        )
        for article in articles:
            if not article.get_doi():
                doi_from_pattern = "{prefix}/{journal_code}.{article_id}".format(
                    prefix=plugin_settings.DATACITE_PREFIX,
                    journal_code=article.journal.code if plugin_settings.JOURNAL_PREFIX else '',
                    article_id=article.pk
                )
                if dry_run:
                    print(f"Creating DOI for article #{article.pk}: {doi_from_pattern}")
                else:
                    success, text = utils.mint_datacite_doi(
                        article,
                        doi_from_pattern,
                        event='publish',
                    )
                    im.Identifier.objects.get_or_create(
                        id_type='doi',
                        identifier=doi_from_pattern,
                        article=article,
                    )
                    print(f"[{success}] {text}")


