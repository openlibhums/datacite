import time
import requests
from requests.auth import HTTPBasicAuth
from pprint import pprint

from django.core.management.base import BaseCommand

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

        for doi in dois:
            url = '{}/{}'.format(
                plugin_settings.DATACITE_API_URL,
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
                print(response)
            time.sleep(2)
