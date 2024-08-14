from django.conf import settings

from utils import plugins
from events import logic as events_logic
from plugins.datacite import utils
from utils.install import update_settings

PLUGIN_NAME = 'Datacite Plugin'
DISPLAY_NAME = 'Datacite'
DESCRIPTION = 'Datacite DOI Deposit TOol.'
AUTHOR = 'Andy Byers'
VERSION = '0.1'
SHORT_NAME = 'datacite'
MANAGER_URL = 'datacite_articles'
JANEWAY_VERSION = "1.3.8"

DATACITE_USERNAME = ''
DATACITE_PASSWORD = ''
DATACITE_PREFIX = ''
DATACITE_API_URL = 'https://api.datacite.org/dois'
JOURNAL_PREFIX = True
MINT_AUTOMATICALLY = False
REDEPOSIT_BUTTON = False

if settings.DEBUG:
    DATACITE_API_URL = 'https://api.test.datacite.org/dois'  # Use test in debug mode.


class DatacitePlugin(plugins.Plugin):
    plugin_name = PLUGIN_NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    author = AUTHOR
    short_name = SHORT_NAME
    manager_url = MANAGER_URL

    version = VERSION
    janeway_version = JANEWAY_VERSION


def install():
    DatacitePlugin.install()
    update_settings(
        file_path='plugins/datacite/install/settings.json'
    )


def hook_registry():
    DatacitePlugin.hook_registry()


def register_for_events():
    events_logic.Events.register_for_event(
        events_logic.Events.ON_ARTICLE_ACCEPTED,
        utils.register_doi_automatically,
    )
    events_logic.Events.register_for_event(
        events_logic.Events.ON_ARTICLE_PUBLISHED,
        utils.publish_doi_automatically,
    )