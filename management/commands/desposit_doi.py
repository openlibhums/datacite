import requests
from requests.auth import HTTPBasicAuth

from django.core.management.base import BaseCommand

from plugins.datacite import utils
from submission import models as sm


class Command(BaseCommand):
    """Updates all datacite DOIs in a batch."""

    help = "Updates all datacite DOIs in a batch. "

    def add_arguments(self, parser):
        parser.add_argument('article_id')
        parser.add_argument('action')

    def handle(self, *args, **options):
        article_id = options.get('article_id')
        article = sm.Article.objects.get(pk=article_id)
        action = options.get('action')
        doi = article.get_doi()
        text, success = None, None

        if action == 'publish':
            success, text = utils.mint_datacite_doi(
                article,
                doi,
                event='publish',
            )
        elif action == 'update':
            success, text = utils.mint_datacite_doi(
                article,
                doi,
                event='update',
            )
        if text:
            print(success, text)
