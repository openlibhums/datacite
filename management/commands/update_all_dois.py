from django.conf import settings
import time
import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint

from django.core.management.base import BaseCommand

from journal.models import Journal
from plugins.datacite import plugin_settings
from identifiers import models


class Command(BaseCommand):
    """Updates all datacite DOIs in a batch."""

    help = "Updates all datacite DOIs in a batch. "

    def add_arguments(self, parser):
        parser.add_argument('--dry_run', action="store_true", default=False)

    def handle(self, *args, **options):
        dois = models.Identifier.objects.filter(
            id_type='doi',
        )

        if settings.DEBUG:
            print("Using DataCite test server because Janeway is in debug mode.")

        for i, doi in enumerate(dois):
            print(f"Updating {i}/{len(dois)}")

            api_url = plugin_settings.DATACITE_API_URL
            journal = doi.article.journal if doi.article else None
            if not settings.DEBUG and journal and hasattr(journal, "status"):
                if journal.status == Journal.PublishingStatus.TEST:
                    api_url = plugin_settings.DATACITE_API_TEST_URL
                    print("This journal has a publishing status of 'test',"
                          "so DOIs will be deposited with the DataCite test server.")
            url = '{}/{}'.format(
                api_url,
                doi.identifier,
            )
            headers = {"Content-Type": "application/vnd.api+json"}
            data = {
                "data": {
                    "id": doi.identifier,
                    "type": "dois",
                    "attributes": {
                        "url": doi.article.url,
                        "landingPage": {
                            "url": doi.article.url,
                        }
                    },
                }
            }
            if options.get('dry_run'):
                pprint(data)
            else:
                response = requests.put(
                    url=url,
                    json=data,
                    headers=headers,
                    auth=HTTPBasicAuth(plugin_settings.DATACITE_USERNAME,
                                       plugin_settings.DATACITE_PASSWORD)
                )
                if response.status_code == 200:
                    print('URL updated to ', response.json()['data']['attributes']['url'])
                time.sleep(2)
