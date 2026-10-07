import csv
import os
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from plugins.datacite import plugin_settings, utils
from identifiers import models as im
from utils.testing import helpers


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


class PrepDataCreatorsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()
        cls.article = helpers.create_article(
            cls.journal,
            date_published=timezone.now(),
            stage='Published',
        )
        cls.author = helpers.create_frozen_author(cls.article)
        cls.ror_affiliation = helpers.create_affiliation(
            institution='Birkbeck, University of London',
            department='Library',
            frozen_author=cls.author,
        )
        cls.ror_affiliation.organization.ror_id = '02mb95055'
        cls.ror_affiliation.organization.save()
        cls.plain_affiliation = helpers.create_affiliation(
            institution='Open Library of Humanities',
            department='Development',
            frozen_author=cls.author,
        )

    def get_creator(self):
        data = utils.prep_data(self.article, '10.1234/test.1')
        return data['data']['attributes']['creators'][0]

    def test_creator_includes_orcid(self):
        self.assertEqual(
            self.get_creator()['nameIdentifiers'],
            [
                {
                    'nameIdentifier': 'https://orcid.org/0000-0001-2345-6789',
                    'nameIdentifierScheme': 'ORCID',
                    'schemeUri': 'https://orcid.org',
                }
            ],
        )

    def test_creator_without_orcid_has_no_name_identifiers(self):
        self.author.frozen_orcid = ''
        self.author.save()
        self.assertNotIn('nameIdentifiers', self.get_creator())

    def test_affiliation_includes_ror(self):
        self.assertIn(
            {
                'name': 'Birkbeck, University of London',
                'affiliationIdentifier': 'https://ror.org/02mb95055',
                'affiliationIdentifierScheme': 'ROR',
                'schemeUri': 'https://ror.org',
            },
            self.get_creator()['affiliation'],
        )

    def test_affiliation_without_ror_is_name_only(self):
        self.assertIn(
            {'name': 'Development, Open Library of Humanities'},
            self.get_creator()['affiliation'],
        )

    def test_author_without_affiliations_has_empty_list(self):
        self.author.affiliations.delete()
        self.assertEqual(self.get_creator()['affiliation'], [])


class PrepDataUnpublishedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()
        cls.article = helpers.create_article(
            cls.journal,
            date_published=None,
        )

    def get_attributes(self):
        data = utils.prep_data(self.article, '10.1234/test.1', 'register')
        return data['data']['attributes']

    def test_related_item_year_falls_back_to_current_year(self):
        # DataCite rejects a related item whose year is not four digits,
        # which broke registration at acceptance.
        self.assertEqual(
            self.get_attributes()['relatedItems'][0]['publicationYear'],
            str(timezone.now().year),
        )

    def test_no_available_date_before_publication(self):
        self.assertEqual(self.get_attributes()['dates'], [])
