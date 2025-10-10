import requests
from requests.auth import HTTPBasicAuth

from django.core.management.base import BaseCommand

from plugins.datacite import utils
from submission import models as sm
from journal import models as jm


class Command(BaseCommand):
    """Updates DataCite DOIs for a single article or all articles in an issue."""

    help = ("Updates DataCite DOIs for a single article "
            "(--article) or all articles in an issue (--issue)."
            )

    def add_arguments(self, parser):
        parser.add_argument(
            '--article',
            type=int,
            help='Article ID to update',
        )
        parser.add_argument(
            '--issue',
            type=int,
            help='Issue ID to update all articles from',
        )
        parser.add_argument(
            'action',
            choices=['publish', 'update', 'register'],
            help='Action to perform on the DOI (publish or update)',
        )

    def handle(self, *args, **options):
        article_id = options.get('article')
        issue_id = options.get('issue')
        action = options.get('action')

        if not article_id and not issue_id:
            self.stderr.write(
                self.style.ERROR("You must specify either --article or --issue"),
            )
            return

        if article_id and issue_id:
            self.stderr.write(
                self.style.ERROR("Please specify only one of --article or --issue"),
            )
            return

        articles = []

        if article_id:
            try:
                article = sm.Article.objects.get(pk=article_id)
                articles = [article]
            except sm.Article.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Article {article_id} not found"))
                return

        if issue_id:
            try:
                issue = jm.Issue.objects.get(pk=issue_id)
                articles = list(issue.articles.all())
            except jm.Issue.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Issue {issue_id} not found"))
                return

        if not articles:
            self.stderr.write(self.style.WARNING("No articles found."))
            return

        success_count = 0
        fail_count = 0

        for article in articles:
            doi = article.get_doi()
            if not doi:
                self.stdout.write(
                    self.style.WARNING(f"Skipping Article {article.pk} — no DOI"),
                )
                continue

            success, text = utils.mint_datacite_doi(
                article,
                doi,
                event=action,
            )

            if success:
                self.stdout.write(self.style.SUCCESS(f"✓ Article {article.pk}: {text}"))
                success_count += 1
            else:
                self.stderr.write(self.style.ERROR(f"✗ Article {article.pk}: {text}"))
                fail_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Finished: {success_count} succeeded, {fail_count} failed",
            )
        )
