import requests
from requests.auth import HTTPBasicAuth

from plugins.datacite import plugin_settings


def prep_data(article, doi):
    series_information = article.journal.name

    if article.issue:
        series_information = "{} Volume {} Issue {} {}".format(
            article.journal.name,
            article.issue.volume,
            article.issue.issue,
            article.issue.date.year,
        )

    keywords = []
    for keyword in article.keywords.all():
        keywords.append({'subject': keyword.word})

    formats = []
    if article.pdfs:
        formats.append("PDF")
    if article.xml_galleys:
        formats.append("XML")

    article_data = {
        "data": {
            "id": doi,
            "type": "dois",
            "attributes": {
                "event": "publish",
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
                "publicationYear": article.date_published.year,
                "types": {
                    "resourceTypeGeneral": "JournalArticle",
                },
                "descriptions": [
                    {
                        "descriptionType": "Abstract",
                        "description": article.abstract,
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
                "language": article.language,
                "dates": [
                    {
                        "dateType": "Available",
                        "date": str(article.date_published.date()),
                    }
                ],
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

    return article_data


def mint_datacite_doi(article, doi):
    headers = {"Content-Type": "application/vnd.api+json"}
    response = requests.post(
        url=plugin_settings.DATACITE_API_URL,
        json=prep_data(article, doi),
        headers=headers,
        auth=HTTPBasicAuth(plugin_settings.DATACITE_USERNAME, plugin_settings.DATACITE_PASSWORD)
    )
    if response.status_code == 201:
        return True
    else:
        return False
