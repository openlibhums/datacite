import requests
from requests.auth import HTTPBasicAuth

from django.utils.html import strip_tags
from django.contrib import messages
from django.utils import timezone

from plugins.datacite import plugin_settings
from identifiers import models as ident_models
from submission import models as submission_models
from utils import setting_handler, models as utils_models
from utils.logger import get_logger
from journal.models import Journal

logger = get_logger(__name__)


def prep_affiliation(affiliation):
    """
    Build a DataCite affiliation, identified by ROR where the organization
    has a ROR ID.
    """
    organization = affiliation.organization
    if organization and organization.ror_id:
        return {
            'name': str(organization.name),
            'affiliationIdentifier': organization.uri,
            'affiliationIdentifierScheme': 'ROR',
            'schemeUri': 'https://ror.org',
        }
    return {
        'name': str(affiliation),
    }


def prep_creator(author):
    """
    Build a DataCite creator, including the author's ORCID and every
    affiliation they hold.
    """
    creator = {
        'name': author.full_name(),
        'nameType': 'Personal',
        'givenName': author.first_name,
        'familyName': author.last_name,
        'affiliation': [
            affiliation
            for affiliation in map(prep_affiliation, author.affiliations)
            if affiliation['name']
        ],
    }
    if author.orcid_uri:
        creator['nameIdentifiers'] = [
            {
                'nameIdentifier': author.orcid_uri,
                'nameIdentifierScheme': 'ORCID',
                'schemeUri': 'https://orcid.org',
            }
        ]
    return creator


def prep_data(
    article,
    doi,
    event=None,
):
    series_information = article.journal.name

    if article.issue:
        series_information = "{}, {}({})".format(
            article.journal.name,
            article.issue.volume,
            article.issue.issue,
        )
        if article.page_range:
            series_information = "{}, {}".format(
                series_information,
                article.page_range,
            )
    elif article.page_range:
        series_information = "{}, {}".format(
            series_information,
            article.page_range,
        )

    keywords = []
    for keyword in article.keywords.all():
        keywords.append(
            {
                'subject': keyword.word,
            }
        )

    formats = []
    if article.pdfs:
        formats.append("application/pdf")
    if article.xml_galleys:
        formats.append("application/xml")

    publicationYear = (
        article.date_published.year
        if article.date_published
        else timezone.now().year
    )

    article_data = {
        "data": {
            "id": doi,
            "type": "dois",
            "attributes": {
                "doi": doi,
                "creators": [
                    prep_creator(author)
                    for author in article.frozen_authors()
                ],
                "titles": [
                    {
                        "title": article.title,
                    }
                ],
                "publisher": article.journal.publisher,
                "publicationYear": publicationYear,
                "types": {
                    "resourceTypeGeneral": "JournalArticle",
                },
                "descriptions": [
                    {
                        "descriptionType": "Abstract",
                        "description": strip_tags(article.abstract) if article.abstract else '',
                    },
                    {
                        "descriptionType": "SeriesInformation",
                        "description": series_information,
                    },
                ],
                "subjects": keywords,
                "formats": formats,
                "url": article.url,
                "schemaVersion": "http://datacite.org/schema/kernel-4.4",
                "dates": [
                    {
                        "dateType": "Available",
                        "date": str(article.date_published.date()),
                    }
                ] if article.date_published else [],
            },
        }
    }

    related_item = {
        "relationType": "IsPublishedIn",
        "titles": f"{article.journal.name}",
        "publisher": f"{article.journal.publisher}",
        "publicationYear": f"{publicationYear}",
        "relatedItemType": "Journal",
    }

    if article.issue:
        related_item.update(
            {
                "issue": f"{article.issue.issue}",
                "volume": f"{article.issue.volume}",
            }
        )

    if article.first_page or article.last_page:
        related_item.update(
            {
                "firstPage": f"{article.first_page or ''}",
                "lastPage": f"{article.last_page or ''}",
            }
        )

    article_data["data"]["attributes"]["relatedItems"] = [related_item]

    if article.license:
        article_data["data"]["attributes"]["rightsList"] = [
            {
                "rights": article.license.name,
                "rightsUri": article.license.url,
            }
        ]

    if article.journal.issn:
        article_data["data"]["attributes"]["relatedIdentifiers"] = [
            {
                "relatedIdentifier": article.journal.issn,
                "relatedIdentifierType": "ISSN",
                "relationType": "IsPublishedIn",
                "resourceTypeGeneral": "Journal",
            }
        ]
        article_data["data"]["attributes"]["relatedItems"][0][
            "relatedItemIdentifier"
        ] = {
            "relatedItemIdentifier": f"{article.journal.issn}",
            "relatedItemIdentifierType": "ISSN",
        }

    if event:
        article_data["data"]["attributes"]["event"] = event

    return article_data


def is_configured():
    """
    Returns True when the DataCite credentials and prefix are set.
    """
    return all(
        [
            plugin_settings.DATACITE_USERNAME,
            plugin_settings.DATACITE_PASSWORD,
            plugin_settings.DATACITE_PREFIX,
        ]
    )


def generate_doi(article):
    """
    Builds the Janeway pattern DOI for an article.
    """
    return "{prefix}/{journal_code}.{article_id}".format(
        prefix=plugin_settings.DATACITE_PREFIX,
        journal_code=article.journal.code if plugin_settings.JOURNAL_PREFIX else '',
        article_id=article.pk,
    )


def deposit_event(article):
    """
    Returns the event to deposit for an article: published articles are made
    findable, all others are registered as drafts.
    """
    if article.stage == submission_models.STAGE_PUBLISHED:
        return 'publish'
    return 'register'


def get_api_url(journal):
    if getattr(journal, 'status', None) == Journal.PublishingStatus.TEST:
        return plugin_settings.DATACITE_API_TEST_URL
    return plugin_settings.DATACITE_API_URL


def describe_error(response):
    """
    Turns a failed DataCite response into a message an editor can read.
    """
    try:
        errors = response.json().get('errors', [])
    except ValueError:
        errors = []

    descriptions = []
    for error in errors:
        title = error.get('title', '')
        source = error.get('source')
        if source:
            title = '{}: {}'.format(source.replace('_', ' '), title)
        descriptions.append(title)

    if descriptions:
        return '; '.join(descriptions)

    text = response.content.decode('utf-8', errors='replace').strip()
    return text or 'DataCite returned status {}.'.format(response.status_code)


def mint_datacite_doi(
    article,
    doi,
    event=None,
):
    if not is_configured():
        return False, (
            'The DataCite username, password and prefix have not been '
            'configured for this installation.'
        )

    headers = {"Content-Type": "application/vnd.api+json"}
    auth = HTTPBasicAuth(
        plugin_settings.DATACITE_USERNAME,
        plugin_settings.DATACITE_PASSWORD,
    )
    data = prep_data(article, doi, event)
    api_url = get_api_url(article.journal)

    try:
        response = None
        if article.get_doi() == doi:
            # The DOI should already exist at DataCite, so update it.
            response = requests.put(
                url='{}/{}'.format(api_url, doi),
                json=data,
                headers=headers,
                auth=auth,
            )
        # If the DOI doesn't exist for some reason (failed at accept) POST it
        if response is None or response.status_code == 404:
            response = requests.post(
                url=api_url,
                json=data,
                headers=headers,
                auth=auth,
            )
    except requests.RequestException as e:
        return False, 'Could not reach DataCite: {}'.format(e)

    if response.status_code in [200, 201]:
        return True, 'Okay'
    else:
        return False, describe_error(response)


def deposit_automatically(article, event, request=None):
    """
    Deposits the article's DOI and records the outcome so that failures are
    not silent.
    """
    doi = article.get_doi() or generate_doi(article)
    success, text = mint_datacite_doi(article, doi, event=event)

    if success:
        ident_models.Identifier.objects.get_or_create(
            id_type='doi',
            identifier=doi,
            article=article,
        )
        description = 'DataCite DOI {} deposited ({}).'.format(doi, event)
    else:
        description = 'DataCite DOI {} was not deposited ({}): {}'.format(
            doi,
            event,
            text,
        )
        logger.error(description)
        if request:
            messages.add_message(request, messages.ERROR, description)

    utils_models.LogEntry.add_entry(
        types='DataCite Deposit',
        description=description,
        level='Info' if success else 'Error',
        actor=request.user if request else None,
        request=request,
        target=article,
    )
    return success, text


def register_doi_automatically(**kwargs):
    """
    Function called thru events framework.
    """
    article = kwargs.get('article')
    if auto_deposit_enabled(article.journal, article.section):
        deposit_automatically(article, 'register', kwargs.get('request'))


def publish_doi_automatically(**kwargs):
    article = kwargs.get('article')
    if auto_deposit_enabled(article.journal, article.section):
        deposit_automatically(article, 'publish', kwargs.get('request'))


def get_settings(journal):
    settings = [
        {
            'name': 'enable_datacite_auto',
            'object': setting_handler.get_setting(
                'plugin:datacite',
                'enable_datacite_auto',
                journal
            ),
        }
    ]
    return settings


def auto_deposit_enabled(journal, section=None):
    """
    Check if auto-deposit is enabled for a given journal and optionally for
    a specific section.

    :param journal: The journal for which auto-deposit setting is checked.

    :param section: Optional. The specific section to check for auto-deposit.
                    Defaults to None.

    :return: True if auto-deposit is enabled for the journal
    (and section if provided), False otherwise.
    """
    if journal:
        # Check if the auto-deposit setting is enabled for the journal
        is_enabled = setting_handler.get_setting(
            setting_group_name='plugin:datacite',
            setting_name='enable_datacite_auto',
            journal=journal,
        ).processed_value

        if not is_enabled:
            return False

        # Check if the journal restricts minting to particular sections
        if section and hasattr(journal, 'sectionmint'):
            sections = journal.sectionmint.sections.all()
            # No sections selected means every section can mint
            if sections.exists():
                return section in sections

        # If no restriction is found or no section is provided, return True
        return True

    return False
