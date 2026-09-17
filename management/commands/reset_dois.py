import csv

from django.core.management.base import BaseCommand, CommandError

from plugins.datacite import utils, plugin_settings
from submission import models as sm
from journal import models as jm
from identifiers import models as im


class Command(BaseCommand):
    """Clears existing DOIs for published articles in a journal, generates a
    Janeway-pattern DOI for each and deposits them with DataCite.

    The Janeway ID, old DOI and new DOI for every article processed are
    written to a CSV file.
    """

    help = (
        "Clear existing DOIs for published articles in a journal, generate a "
        "Janeway DOI and deposit it with DataCite. Results are written to CSV."
    )

    def add_arguments(self, parser):
        parser.add_argument('journal_code')
        parser.add_argument(
            '--article_id',
            type=int,
            default=None,
            help="Restrict the run to a single article (by Janeway ID). "
                 "Useful for a test run before processing the whole journal.",
        )
        parser.add_argument(
            '--output',
            default=None,
            help="Path to the CSV file to write. Defaults to "
                 "reset_dois_<journal_code>.csv in the current directory.",
        )
        parser.add_argument('--dry_run', action="store_true", default=False)

    @staticmethod
    def janeway_doi_for(article):
        """Build the standard Janeway-pattern DOI for an article."""
        return "{prefix}/{journal_code}.{article_id}".format(
            prefix=plugin_settings.DATACITE_PREFIX,
            journal_code=article.journal.code if plugin_settings.JOURNAL_PREFIX else '',
            article_id=article.pk,
        )

    def handle(self, *args, **options):
        journal_code = options.get('journal_code')
        dry_run = options.get('dry_run')
        article_id = options.get('article_id')
        output = options.get('output') or "reset_dois_{}.csv".format(journal_code)

        try:
            journal = jm.Journal.objects.get(code=journal_code)
        except jm.Journal.DoesNotExist:
            raise CommandError(
                "No journal found with code '{}'.".format(journal_code)
            )

        articles = sm.Article.objects.filter(
            journal=journal,
            date_published__isnull=False,
        )

        if article_id:
            articles = articles.filter(pk=article_id)
            if not articles.exists():
                raise CommandError(
                    "No published article #{pk} found in journal '{code}'.".format(
                        pk=article_id, code=journal_code,
                    )
                )

        rows = []
        for article in articles:
            old_doi = article.get_doi() or ''
            new_doi = self.janeway_doi_for(article)

            if dry_run:
                self.stdout.write(
                    "[dry run] Article #{pk}: {old} -> {new}".format(
                        pk=article.pk, old=old_doi or '(none)', new=new_doi,
                    )
                )
                rows.append((article.pk, old_doi, new_doi))
                continue

            # Replace the local identifier with the Janeway-pattern DOI before
            # depositing. With the new DOI in place, mint_datacite_doi routes
            # through its PUT (update) path: this updates the record if the DOI
            # already exists at DataCite (avoiding a "DOI already taken" error
            # on re-runs), and falls back to a POST (create) via its built-in
            # 404 handler when the DOI is genuinely new.
            im.Identifier.objects.filter(
                id_type='doi',
                article=article,
            ).delete()
            im.Identifier.objects.create(
                id_type='doi',
                identifier=new_doi,
                article=article,
            )

            success, text = utils.mint_datacite_doi(
                article,
                new_doi,
                event='publish',
            )

            if success:
                self.stdout.write(
                    "[ok] Article #{pk}: {old} -> {new}".format(
                        pk=article.pk, old=old_doi or '(none)', new=new_doi,
                    )
                )
                rows.append((article.pk, old_doi, new_doi))
            else:
                # Roll back to the previous state so we never leave a DOI that
                # was not successfully deposited.
                im.Identifier.objects.filter(
                    id_type='doi',
                    article=article,
                ).delete()
                if old_doi:
                    im.Identifier.objects.create(
                        id_type='doi',
                        identifier=old_doi,
                        article=article,
                    )
                self.stderr.write(
                    "[fail] Article #{pk}: {old} -> {new}: {text}".format(
                        pk=article.pk, old=old_doi or '(none)',
                        new=new_doi, text=text,
                    )
                )
                # Record the attempt with no new DOI minted.
                rows.append((article.pk, old_doi, ''))

        with open(output, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['JANEWAY ID', 'OLD DOI', 'NEW DOI'])
            writer.writerows(rows)

        self.stdout.write(
            "Wrote {count} row(s) to {output}.".format(
                count=len(rows), output=output,
            )
        )
