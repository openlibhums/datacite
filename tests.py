import csv
import os
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core import models as core_models
from plugins.datacite import plugin_settings, utils
from identifiers import models as im
from submission import models as submission_models
from utils.testing import helpers


class PrepDataMetadataTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, cls.other_journal = helpers.create_journals()
        cls.article = helpers.create_article(
            cls.journal,
            date_published=timezone.now(),
            stage='Published',
        )
        cls.orcid_author = helpers.create_frozen_author(cls.article)
        ror_organization = core_models.Organization.objects.create(
            ror_id='02mb95055',
        )
        core_models.OrganizationName.objects.create(
            value='University of Testing',
            custom_label_for=ror_organization,
        )
        core_models.ControlledAffiliation.objects.create(
            frozen_author=cls.orcid_author,
            organization=ror_organization,
        )
        cls.plain_author = helpers.create_frozen_author(
            cls.article,
            frozen_orcid='',
        )
        helpers.create_affiliation(
            institution='Unregistered Institute',
            frozen_author=cls.plain_author,
        )
        cls.legacy_author = helpers.create_frozen_author(
            cls.article,
            frozen_orcid='',
        )
        core_models.ControlledAffiliation.objects.create(
            frozen_author=cls.legacy_author,
            organization=None,
            department='Legacy Department',
        )
        cls.unaffiliated_author = helpers.create_frozen_author(
            cls.article,
            frozen_orcid='',
        )
        submission_models.ArticleFunding.objects.create(
            article=cls.article,
            name='Alpha Foundation',
            fundref_id='https://dx.doi.org/10.13039/501100021082',
            funding_id='ABC-123',
        )
        submission_models.ArticleFunding.objects.create(
            article=cls.article,
            name='Beta Trust',
        )
        cls.article_without_metadata = helpers.create_article(
            cls.journal,
            date_published=timezone.now(),
            stage='Published',
        )
        cls.doi = '10.0000/tst.1'

    def get_creators(self, article):
        data = utils.prep_data(article, self.doi)
        return data['data']['attributes']['creators']

    def test_creator_with_orcid_includes_name_identifier(self):
        creators = self.get_creators(self.article)
        self.assertEqual(
            creators[0]['nameIdentifiers'],
            [
                {
                    'nameIdentifier': 'https://orcid.org/0000-0001-2345-6789',
                    'nameIdentifierScheme': 'ORCID',
                    'schemeUri': 'https://orcid.org',
                }
            ],
        )

    def test_creator_without_orcid_has_no_name_identifiers(self):
        creators = self.get_creators(self.article)
        self.assertNotIn('nameIdentifiers', creators[1])

    def test_affiliation_with_ror_includes_identifier(self):
        creators = self.get_creators(self.article)
        self.assertEqual(
            creators[0]['affiliation'],
            [
                {
                    'name': 'University of Testing',
                    'affiliationIdentifier': 'https://ror.org/02mb95055',
                    'affiliationIdentifierScheme': 'ROR',
                    'schemeUri': 'https://ror.org',
                }
            ],
        )

    def test_affiliation_without_ror_is_name_only(self):
        creators = self.get_creators(self.article)
        self.assertEqual(
            creators[1]['affiliation'],
            [
                {
                    'name': 'Unregistered Institute',
                }
            ],
        )

    def test_affiliation_without_organization_falls_back_to_string(self):
        creators = self.get_creators(self.article)
        self.assertEqual(
            creators[2]['affiliation'],
            [
                {
                    'name': 'Legacy Department',
                }
            ],
        )

    def test_creator_without_affiliations_has_empty_affiliation(self):
        creators = self.get_creators(self.article)
        self.assertEqual(creators[3]['affiliation'], [])

    def test_article_without_authors_has_empty_creators(self):
        creators = self.get_creators(self.article_without_metadata)
        self.assertEqual(creators, [])

    def test_funding_references(self):
        data = utils.prep_data(self.article, self.doi)
        self.assertEqual(
            data['data']['attributes']['fundingReferences'],
            [
                {
                    'funderName': 'Alpha Foundation',
                    'funderIdentifier':
                        'https://dx.doi.org/10.13039/501100021082',
                    'funderIdentifierType': 'Crossref Funder ID',
                    'awardNumber': 'ABC-123',
                },
                {
                    'funderName': 'Beta Trust',
                },
            ],
        )

    def test_article_without_funders_has_empty_funding_references(self):
        data = utils.prep_data(self.article_without_metadata, self.doi)
        self.assertEqual(
            data['data']['attributes']['fundingReferences'],
            [],
        )


class ResetDOIsCommandTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, cls.other_journal = helpers.create_journals()
        cls.published_article = helpers.create_article(
            cls.journal,
            date_published=timezone.now(),
            stage='Published',
        )
        cls.unpublished_article = helpers.create_article(
            cls.journal,
            date_published=None,
        )

    def setUp(self):
        # An existing, non-Janeway DOI that should be cleared.
        self.old_identifier = im.Identifier.objects.create(
            id_type='doi',
            identifier='10.0000/legacy.doi',
            article=self.published_article,
        )
        self.tmp_csv = os.path.join(
            tempfile.mkdtemp(),
            'reset_dois.csv',
        )

    def expected_doi(self, article):
        return "{prefix}/{code}.{pk}".format(
            prefix=plugin_settings.DATACITE_PREFIX,
            code=article.journal.code,
            pk=article.pk,
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_old_doi_cleared_and_janeway_doi_minted(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')

        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
        )

        # Old DOI removed, new Janeway-pattern DOI created.
        self.assertFalse(
            im.Identifier.objects.filter(pk=self.old_identifier.pk).exists()
        )
        new_doi = self.expected_doi(self.published_article)
        self.assertTrue(
            im.Identifier.objects.filter(
                id_type='doi',
                identifier=new_doi,
                article=self.published_article,
            ).exists()
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_deposit_uses_publish_event(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')

        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
        )

        mock_mint.assert_called_once_with(
            self.published_article,
            self.expected_doi(self.published_article),
            event='publish',
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_unpublished_articles_are_skipped(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')

        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
        )

        called_articles = [call.args[0] for call in mock_mint.call_args_list]
        self.assertNotIn(self.unpublished_article, called_articles)

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_csv_output(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')

        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
        )

        with open(self.tmp_csv, newline='') as csv_file:
            rows = list(csv.reader(csv_file))

        self.assertEqual(rows[0], ['JANEWAY ID', 'OLD DOI', 'NEW DOI'])
        self.assertIn(
            [
                str(self.published_article.pk),
                '10.0000/legacy.doi',
                self.expected_doi(self.published_article),
            ],
            rows[1:],
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_article_id_restricts_to_single_article(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')
        other = helpers.create_article(
            self.journal,
            date_published=timezone.now(),
            stage='Published',
        )

        call_command(
            'reset_dois',
            self.journal.code,
            article_id=self.published_article.pk,
            output=self.tmp_csv,
        )

        called_articles = [call.args[0] for call in mock_mint.call_args_list]
        self.assertEqual(called_articles, [self.published_article])
        self.assertNotIn(other, called_articles)

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_failed_deposit_rolls_back_to_old_doi(self, mock_mint):
        mock_mint.return_value = (False, b'error')

        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
        )

        # The article is left with its original DOI and no Janeway DOI.
        dois = im.Identifier.objects.filter(
            id_type='doi',
            article=self.published_article,
        ).values_list('identifier', flat=True)
        self.assertEqual(list(dois), ['10.0000/legacy.doi'])

        with open(self.tmp_csv, newline='') as csv_file:
            rows = list(csv.reader(csv_file))
        self.assertIn(
            [str(self.published_article.pk), '10.0000/legacy.doi', ''],
            rows[1:],
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_dry_run_makes_no_changes(self, mock_mint):
        call_command(
            'reset_dois',
            self.journal.code,
            output=self.tmp_csv,
            dry_run=True,
        )

        # No deposit attempted and the old DOI is left untouched.
        mock_mint.assert_not_called()
        self.assertTrue(
            im.Identifier.objects.filter(pk=self.old_identifier.pk).exists()
        )

        # CSV still records the intended change.
        with open(self.tmp_csv, newline='') as csv_file:
            rows = list(csv.reader(csv_file))
        self.assertEqual(rows[0], ['JANEWAY ID', 'OLD DOI', 'NEW DOI'])
        self.assertIn(
            [
                str(self.published_article.pk),
                '10.0000/legacy.doi',
                self.expected_doi(self.published_article),
            ],
            rows[1:],
        )
