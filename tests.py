import csv
import os
import tempfile
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from plugins.datacite import forms, models, plugin_settings, utils
from identifiers import models as im
from journal.models import Journal
from utils import models as utils_models, setting_handler
from utils.install import update_settings
from utils.testing import helpers
from core.urls import urlpatterns as core_urlpatterns

# The plugin loader only registers installed plugins, so the view tests
# include the plugin's URLs directly.
urlpatterns = core_urlpatterns + [
    path('plugins/datacite/', include('plugins.datacite.urls')),
]


CONFIGURED = {
    'DATACITE_USERNAME': 'user',
    'DATACITE_PASSWORD': 'password',
    'DATACITE_PREFIX': '10.1234',
}


def configured(test):
    for name, value in CONFIGURED.items():
        test = patch.object(plugin_settings, name, value)(test)
    return test


def mock_response(status_code, json_data=None, content=b''):
    response = Mock(status_code=status_code, content=content)
    if json_data is None:
        response.json.side_effect = ValueError
    else:
        response.json.return_value = json_data
    return response


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


class DescribeErrorTest(TestCase):

    def test_errors_are_joined_with_their_source(self):
        response = mock_response(
            422,
            {
                'errors': [
                    {
                        'source': 'related_items',
                        'title': 'String at /0publicationYear does not '
                                 'match pattern: [\\d]{4}',
                    },
                    {'title': 'DOI has already been taken'},
                ]
            },
        )
        self.assertEqual(
            utils.describe_error(response),
            'related items: String at /0publicationYear does not match '
            'pattern: [\\d]{4}; DOI has already been taken',
        )

    def test_non_json_response_returns_text(self):
        response = mock_response(500, content=b'Server error')
        self.assertEqual(utils.describe_error(response), 'Server error')

    def test_empty_response_returns_status(self):
        response = mock_response(502)
        self.assertEqual(
            utils.describe_error(response),
            'DataCite returned status 502.',
        )


class MintDataciteDOITest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()
        cls.article = helpers.create_article(cls.journal)

    def test_unconfigured_does_not_call_datacite(self):
        with patch.object(plugin_settings, 'DATACITE_PREFIX', ''), \
                patch('plugins.datacite.utils.requests.post') as post:
            success, text = utils.mint_datacite_doi(
                self.article, '10.1234/x', 'register',
            )
        self.assertFalse(success)
        self.assertIn('have not been configured', text)
        post.assert_not_called()

    @configured
    @patch('plugins.datacite.utils.requests.post')
    def test_new_doi_is_posted(self, post):
        post.return_value = mock_response(201)
        success, _ = utils.mint_datacite_doi(
            self.article, '10.1234/TST.1', 'register',
        )
        self.assertTrue(success)
        post.assert_called_once()

    @configured
    @patch('plugins.datacite.utils.requests.post')
    @patch('plugins.datacite.utils.requests.put')
    def test_existing_doi_is_updated(self, put, post):
        im.Identifier.objects.create(
            id_type='doi', identifier='10.1234/TST.1', article=self.article,
        )
        put.return_value = mock_response(200)
        success, _ = utils.mint_datacite_doi(
            self.article, '10.1234/TST.1', 'register',
        )
        self.assertTrue(success)
        self.assertTrue(put.call_args.kwargs['url'].endswith('/10.1234/TST.1'))
        post.assert_not_called()

    @configured
    @patch('plugins.datacite.utils.requests.post')
    @patch('plugins.datacite.utils.requests.put')
    def test_missing_doi_on_test_journal_falls_back_to_test_api(self, put, post):
        self.journal.status = Journal.PublishingStatus.TEST
        self.journal.save()
        im.Identifier.objects.create(
            id_type='doi', identifier='10.1234/TST.1', article=self.article,
        )
        put.return_value = mock_response(404)
        post.return_value = mock_response(201)
        utils.mint_datacite_doi(self.article, '10.1234/TST.1', 'publish')
        self.assertEqual(
            post.call_args.kwargs['url'],
            plugin_settings.DATACITE_API_TEST_URL,
        )

    @configured
    @patch('plugins.datacite.utils.requests.post')
    def test_connection_error_is_reported(self, post):
        post.side_effect = requests.ConnectionError('timed out')
        success, text = utils.mint_datacite_doi(
            self.article, '10.1234/TST.1', 'register',
        )
        self.assertFalse(success)
        self.assertIn('Could not reach DataCite', text)


class AutomaticDepositTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()
        cls.section = helpers.create_section(cls.journal)
        cls.other_section = helpers.create_section(
            cls.journal, name='Review', plural='Reviews',
        )
        cls.article = helpers.create_article(cls.journal, section=cls.section)
        update_settings(file_path='plugins/datacite/install/settings.json')
        setting_handler.save_setting(
            'plugin:datacite', 'enable_datacite_auto', cls.journal, 'On',
        )

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_failure_is_logged_on_the_article(self, mock_mint):
        mock_mint.return_value = (False, 'DOI has already been taken')
        utils.register_doi_automatically(article=self.article)
        entry = utils_models.LogEntry.objects.get(types='DataCite Deposit')
        self.assertEqual(entry.level, 'Error')
        self.assertIn('DOI has already been taken', entry.description)
        self.assertFalse(self.article.get_doi())

    @patch('plugins.datacite.utils.mint_datacite_doi')
    def test_success_records_doi(self, mock_mint):
        mock_mint.return_value = (True, 'Okay')
        utils.register_doi_automatically(article=self.article)
        self.assertEqual(
            self.article.get_doi(), utils.generate_doi(self.article),
        )

    def test_section_mint_with_no_sections_allows_all(self):
        models.SectionMint.objects.create(journal=self.journal)
        self.assertTrue(
            utils.auto_deposit_enabled(self.journal, self.section),
        )

    def test_section_mint_restricts_to_selected_sections(self):
        section_mint = models.SectionMint.objects.create(journal=self.journal)
        section_mint.sections.add(self.other_section)
        self.assertFalse(
            utils.auto_deposit_enabled(self.journal, self.section),
        )


class DepositEventTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()

    def test_published_article_is_made_findable(self):
        article = helpers.create_article(
            self.journal, stage='Published', date_published=timezone.now(),
        )
        self.assertEqual(utils.deposit_event(article), 'publish')

    def test_unpublished_article_stays_draft(self):
        article = helpers.create_article(self.journal, stage='Typesetting')
        self.assertEqual(utils.deposit_event(article), 'register')


@configured
class DOIFormTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, _ = helpers.create_journals()
        cls.article = helpers.create_article(cls.journal)

    def get_form(self, doi):
        return forms.DOIForm({'identifier': doi}, article=self.article)

    def test_wrong_prefix_is_rejected(self):
        form = self.get_form('10.9999/TST.1')
        self.assertFalse(form.is_valid())
        self.assertIn('prefix', form.errors['identifier'][0])

    def test_doi_in_use_is_rejected(self):
        other = helpers.create_article(self.journal)
        im.Identifier.objects.create(
            id_type='doi', identifier='10.1234/TST.1', article=other,
        )
        self.assertFalse(self.get_form('10.1234/TST.1').is_valid())

    def test_valid_doi_is_accepted(self):
        self.assertTrue(self.get_form('10.1234/TST.1').is_valid())


@override_settings(ROOT_URLCONF='plugins.datacite.tests')
class ViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.press = helpers.create_press()
        cls.journal, cls.other_journal = helpers.create_journals()
        cls.article = helpers.create_article(cls.journal)
        cls.other_article = helpers.create_article(cls.other_journal)
        update_settings(file_path='plugins/datacite/install/settings.json')
        cls.staff = helpers.create_user('staff@example.com')
        cls.staff.is_staff = True
        cls.staff.is_active = True
        cls.staff.save()

    def setUp(self):
        self.client.force_login(self.staff)

    def test_export_without_doi_uses_generated_doi(self):
        response = self.client.get(
            reverse('datacite_article_export', args=[self.article.pk]),
        )
        self.assertEqual(
            response.json()['data']['id'],
            utils.generate_doi(self.article),
        )

    def test_export_of_other_journal_article_is_not_found(self):
        response = self.client.get(
            reverse('datacite_article_export', args=[self.other_article.pk]),
        )
        self.assertEqual(response.status_code, 404)

    def test_add_doi_for_other_journal_article_is_not_found(self):
        response = self.client.get(
            reverse('datacite_add_doi', args=[self.other_article.pk]),
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_live_site_does_not_claim_debug_mode(self):
        response = self.client.get(reverse('datacite_articles'))
        self.assertNotContains(response, 'debug mode')

    @override_settings(DEBUG=True)
    def test_debug_site_shows_debug_notice(self):
        response = self.client.get(reverse('datacite_articles'))
        self.assertContains(response, 'debug mode')

    @patch.object(plugin_settings, 'DATACITE_PREFIX', '')
    def test_unconfigured_plugin_shows_warning(self):
        response = self.client.get(reverse('datacite_index'))
        self.assertContains(response, 'have not been configured')

    @configured
    def test_add_doi_suggests_full_doi(self):
        response = self.client.get(
            reverse('datacite_add_doi', args=[self.article.pk]),
        )
        self.assertContains(response, utils.generate_doi(self.article))

    def test_saving_section_controls_confirms(self):
        response = self.client.post(
            reverse('datacite_section_mint_manager'),
            {'sections': []},
            follow=True,
        )
        self.assertContains(response, 'Section controls saved.')
