import requests
from requests.auth import HTTPBasicAuth

from django.utils.html import strip_tags
from django.utils import timezone

from plugins.datacite import plugin_settings
from identifiers import models as ident_models


def prep_data(article, doi, event=None):
    series_information = article.journal.name

    if article.issue:
        series_information = "{}, {}({})".format(
            article.journal.name,
            article.issue.volume,
            article.issue.issue,
            article.issue.date.year,
        )
        if article.page_range:
            series_information = "{}, {}".format(
                series_information,
                article.page_range,
            )

    keywords = []
    for keyword in article.keywords.all():
        keywords.append({'subject': keyword.word})

    formats = []
    if article.pdfs:
        formats.append("PDF")
    if article.xml_galleys:
        formats.append("XML")

    publicationYear = article.date_published.year if article.date_published else timezone.now().year

    article_data = {
        "data": {
            "id": doi,
            "type": "dois",
            "attributes": {
                "doi": doi,
                "creators": [{
                    'name': author.full_name(),
                    'nameType': 'Personal',
                    'givenName': author.first_name,
                    'familyName': author.last_name,
                    'affiliation': [
                        {
                            'name': author.affiliation(),
                        }
                    ]
                } for author in article.frozen_authors()],
                "titles": [{
                    "title": article.title,
                }],
                "publisher": article.journal.publisher,
                "publicationYear":  publicationYear,
                "types": {
                    "resourceTypeGeneral": "JournalArticle",
                },
                "descriptions": [
                    {
                        "descriptionType": "Abstract",
                        "description": strip_tags(article.abstract),
                    },
                    {
                        "descriptionType": "SeriesInformation",
                        "description": series_information,
                    }
                ],
                "rightsList": [
                    {
                        "rights": article.license.name,
                        "rightsUri": article.license.url
                    }
                ],
                "subjects": keywords,
                "formats": formats,
                "url": article.url,
                "schemaVersion": "http://datacite.org/schema/kernel-4.4",
                "dates": [
                    {
                        "dateType": "Available",
                        "date": str(article.date_published.date()) if article.date_published else '',
                    }
                ],
                "relatedItems": [
                    {
                        "relationType": "IsPublishedIn",
                        "issue": f"{article.issue.issue}",
                        "volume": f"{article.issue.volume}",
                        "titles": f"{article.journal.name}",
                        "publisher": f"{article.journal.publisher}",
                        "publicationYear": f"{article.date_published.year}",
                        "relatedItemType": "Journal",
                        "firstPage": f"{article.first_page if article.first_page else ''}",
                        "lastPage": f"{article.last_page if article.last_page else ''}",

                    }
                ]
            }
        }
    }

    if article.journal.issn:
        article_data["data"]["attributes"]["relatedIdentifiers"] = [
            {
                "relatedIdentifier": article.journal.issn,
                "relatedIdentifierType": "ISSN",
                "relationType": "IsPublishedIn",
                "resourceTypeGeneral": "Journal"
            }
        ]
        article_data["data"]["attributes"]["relatedItems"][0]["relatedItemIdentifier"] = {
            "relatedItemIdentifier": f"{article.journal.issn}",
            "relatedItemIdentifierType": "ISSN"
        }

    if event:
        article_data["data"]["attributes"]["event"] = event

    return article_data


def mint_datacite_doi(article, doi, event=None):
    headers = {"Content-Type": "application/vnd.api+json"}

    if event == 'publish' and article.get_doi():
        # The DOI will exists and we should use a PUT command
        url = '{}/{}'.format(plugin_settings.DATACITE_API_URL, article.get_doi())
        response = requests.put(
            url=url,
            json=prep_data(article, doi, event),
            headers=headers,
            auth=HTTPBasicAuth(plugin_settings.DATACITE_USERNAME, plugin_settings.DATACITE_PASSWORD)
        )
    else:
        response = requests.post(
            url=plugin_settings.DATACITE_API_URL,
            json=prep_data(article, doi),
            headers=headers,
            auth=HTTPBasicAuth(plugin_settings.DATACITE_USERNAME, plugin_settings.DATACITE_PASSWORD)
        )

    if response.status_code in [200, 201]:
        return True, 'Okay'
    else:
        return False, response.content


def register_doi_automatically(**kwargs):
    """
    Function called thru events framework.
    """
    article = kwargs.get('article')
    doi = "{prefix}/{journal_code}.{article_id}".format(
        prefix=plugin_settings.DATACITE_PREFIX,
        journal_code=article.journal.code if plugin_settings.JOURNAL_PREFIX else '',
        article_id=article.pk
    )
    success, text = mint_datacite_doi(article, doi, event='register')

    if success:
        ident_models.Identifier.objects.get_or_create(
            id_type='doi',
            identifier=doi,
            article=article,
        )


def publish_doi_automatically(**kwargs):
    article = kwargs.get('article')
    doi = "{prefix}/{journal_code}.{article_id}".format(
        prefix=plugin_settings.DATACITE_PREFIX,
        journal_code=article.journal.code if plugin_settings.JOURNAL_PREFIX else '',
        article_id=article.pk
    )
    success, text = mint_datacite_doi(article, doi, event='publish')

    if success:
        ident_models.Identifier.objects.get_or_create(
            id_type='doi',
            identifier=doi,
            article=article,
        )
