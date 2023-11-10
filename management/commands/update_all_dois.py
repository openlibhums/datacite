import time
import requests
from requests.auth import HTTPBasicAuth

from django.core.management.base import BaseCommand

from plugins.datacite import plugin_settings
from identifiers import models


class Command(BaseCommand):
    """Updates all datacite DOIs in a batch."""

    help = "Updates all datacite DOIs in a batch. "

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
                    "id": "10.7282/t3-7zhk-y459",
                    "type": "dois",
                    "attributes": {
                        "url": "https://example.org"
                    }
                }
            }
            response = requests.put(
                url=url,
                json=data,
                headers=headers,
                auth=HTTPBasicAuth(plugin_settings.DATACITE_USERNAME,
                                   plugin_settings.DATACITE_PASSWORD)
            )
            time.sleep(2)
