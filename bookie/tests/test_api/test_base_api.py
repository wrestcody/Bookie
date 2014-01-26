"""Test that we're meeting delicious API specifications"""
# Need to create a new renderer that wraps the jsonp renderer and adds these
# heads to all responses. Then the api needs to be adjusted to use this new
# renderer type vs jsonp.
import logging
import json
import transaction
import unittest
from pyramid import testing

from bookie.bcelery import tasks
from bookie.models import DBSession
from bookie.tests import BOOKIE_TEST_INI
from bookie.tests import empty_db

GOOGLE_HASH = u'aa2239c17609b2'
BMARKUS_HASH = u'c5c21717c99797'
LOG = logging.getLogger(__name__)

API_KEY = None


class BookieAPITest(unittest.TestCase):
    """Test the Bookie API"""

    def setUp(self):
        from pyramid.paster import get_app
        app = get_app(BOOKIE_TEST_INI, 'bookie')
        from webtest import TestApp
        self.testapp = TestApp(app)
        testing.setUp()

        global API_KEY
        res = DBSession.execute(
            "SELECT api_key FROM users WHERE username = 'admin'").fetchone()
        API_KEY = res['api_key']

    def tearDown(self):
        """We need to empty the bmarks table on each run"""
        testing.tearDown()
        empty_db()

    def _check_cors_headers(self, res):
        """ Make sure that the request has proper CORS headers."""
        self.assertEqual(res.headers['access-control-allow-origin'], '*')
        self.assertEqual(
            res.headers['access-control-allow-headers'], 'X-Requested-With')

    def _get_good_request(self, content=False, second_bmark=False):
        """Return the basics for a good add bookmark request"""
        session = DBSession()

        # the main bookmark, added second to prove popular will sort correctly
        prms = {
            'url': u'http://google.com',
            'description': u'This is my google desc',
            'extended': u'And some extended notes about it in full form',
            'tags': u'python search',
            'api_key': API_KEY,
            'username': u'admin',
            'inserted_by': u'chrome_ext',
        }

        # if we want to test the readable fulltext side we want to make sure we
        # pass content into the new bookmark
        if content:
            prms['content'] = u"<p>There's some content in here dude</p>"

        # rself.assertEqualparams = urllib.urlencode(prms)
        res = self.testapp.post(
            '/api/v1/admin/bmark?',
            content_type='application/json',
            params=json.dumps(prms),
        )

        if second_bmark:
            prms = {
                'url': u'http://bmark.us',
                'description': u'Bookie',
                'extended': u'Exteded notes',
                'tags': u'bookmarks',
                'api_key': API_KEY,
                'username': u'admin',
                'inserted_by': u'chrome_ext',
            }

            # if we want to test the readable fulltext side we want to make
            # sure we pass content into the new bookmark
            prms['content'] = u"<h1>Second bookmark man</h1>"

            # rself.assertEqualparams = urllib.urlencode(prms)
            res = self.testapp.post(
                '/api/v1/admin/bmark?',
                content_type='application/json',
                params=json.dumps(prms)
            )

        session.flush()
        transaction.commit()
        # Run the celery task for indexing this bookmark.
        tasks.reindex_fulltext_allbookmarks(sync=True)
        return res

    def test_add_bookmark(self):
        """We should be able to add a new bookmark to the system"""
        # we need to know what the current admin's api key is so we can try to
        # add
        res = DBSession.execute(
            "SELECT api_key FROM users WHERE username = 'admin'").fetchone()
        key = res['api_key']

        test_bmark = {
            'url': u'http://bmark.us',
            'description': u'Bookie',
            'extended': u'Extended notes',
            'tags': u'bookmarks',
            'api_key': key,
        }

        res = self.testapp.post('/api/v1/admin/bmark',
                                params=test_bmark,
                                status=200)

        self.assertTrue(
            '"location":' in res.body,
            "Should have a location result: " + res.body)
        self.assertTrue(
            'description": "Bookie"' in res.body,
            "Should have Bookie in description: " + res.body)
        self._check_cors_headers(res)

    def test_add_bookmark_empty_body(self):
        """When missing a POST body we get an error response."""
        res = DBSession.execute(
            "SELECT api_key FROM users WHERE username = 'admin'").fetchone()
        key = res['api_key']

        res = self.testapp.post(
            str('/api/v1/admin/bmark?api_key={0}'.format(key)),
            params={},
            status=400)

        data = json.loads(res.body)
        self.assertTrue('error' in data)
        self.assertEqual(data['error'], 'Bad Request: No url provided')

    def test_add_bookmark_missing_url_in_JSON(self):
        """When missing the url in the JSON POST we get an error response."""
        res = DBSession.execute(
            "SELECT api_key FROM users WHERE username = 'admin'").fetchone()
        key = res['api_key']

        params = {
            'description': u'This is my test desc',
        }

        res = self.testapp.post(
            str('/api/v1/admin/bmark?api_key={0}'.format(key)),
            content_type='application/json',
            params=json.dumps(params),
            status=400)

        data = json.loads(res.body)
        self.assertTrue('error' in data)
        self.assertEqual(data['error'], 'Bad Request: No url provided')

    def test_bookmark_fetch(self):
        """Test that we can get a bookmark and it's details"""
        self._get_good_request(content=True)
        res = self.testapp.get('/api/v1/admin/bmark/{0}?api_key={1}'.format(
                               GOOGLE_HASH,
                               API_KEY),
                               status=200)

        # make sure we can decode the body
        bmark = json.loads(res.body)['bmark']
        self.assertEqual(
            GOOGLE_HASH,
            bmark[u'hash_id'],
            "The hash_id should match: " + str(bmark[u'hash_id']))

        self.assertTrue(
            u'tags' in bmark,
            "We should have a list of tags in the bmark returned")

        self.assertTrue(
            bmark[u'tags'][0][u'name'] in [u'python', u'search'],
            "Tag should be either python or search:" +
            str(bmark[u'tags'][0][u'name']))

        self.assertTrue(
            u'readable' not in bmark,
            "We should not have readable content")

        self.assertEqual(
            u'python search', bmark[u'tag_str'],
            "tag_str should be populated: " + str(dict(bmark)))

        # to get readble content we need to pass the flash with_content
        res = self.testapp.get(
            '/api/v1/admin/bmark/{0}?api_key={1}&with_content=true'.format(
                GOOGLE_HASH,
                API_KEY),
            status=200)

        # make sure we can decode the body
        bmark = json.loads(res.body)['bmark']

        self.assertTrue(
            u'readable' in bmark,
            "We should have readable content")

        self.assertTrue(
            'dude' in bmark['readable']['content'],
            "We should have 'dude' in our content: " +
            bmark['readable']['content'])
        self._check_cors_headers(res)

    def test_bookmark_fetch_fail(self):
        """Verify we get a failed response when wrong bookmark"""
        self._get_good_request()

        # test that we get a 404
        res = self.testapp.get(
            '/api/v1/admin/bmark/{0}?api_key={1}'.format(BMARKUS_HASH,
                                                         API_KEY),
            status=404)
        self._check_cors_headers(res)

    def test_bookmark_diff_user(self):
        """Verify that anon users can access the bookmark"""
        self._get_good_request()

        # test that we get a 404
        res = self.testapp.get(
            '/api/v1/admin/bmark/{0}'.format(GOOGLE_HASH),
            status=200)
        self._check_cors_headers(res)

    def test_bookmark_diff_user_authed(self):
        """Verify an auth'd user can fetch another's bookmark"""
        self._get_good_request()

        # test that we get a 404
        res = self.testapp.get(
            '/api/v1/admin/bmark/{0}'.format(GOOGLE_HASH, 'invalid'),
            status=200)
        self._check_cors_headers(res)

    def test_bookmark_remove(self):
        """A delete call should remove the bookmark from the system"""
        self._get_good_request(content=True, second_bmark=True)

        # now let's delete the google bookmark
        res = self.testapp.delete(
            '/api/v1/admin/bmark/{0}?api_key={1}'.format(
                GOOGLE_HASH,
                API_KEY),
            status=200)

        self.assertTrue(
            'message": "done"' in res.body,
            "Should have a message of done: " + res.body)

        # we're going to cheat like mad, use the sync call to get the hash_ids
        # of bookmarks in the system and verify that only the bmark.us hash_id
        # is in the response body
        res = self.testapp.get('/api/v1/admin/extension/sync',
                               params={'api_key': API_KEY},
                               status=200)

        self.assertTrue(
            GOOGLE_HASH not in res.body,
            "Should not have the google hash: " + res.body)
        self.assertTrue(
            BMARKUS_HASH in res.body,
            "Should have the bmark.us hash: " + res.body)
        self._check_cors_headers(res)

    def test_bookmark_recent_user(self):
        """Test that we can get list of bookmarks with details"""
        self._get_good_request(content=True)
        res = self.testapp.get('/api/v1/admin/bmarks?api_key=' + API_KEY,
                               status=200)

        # make sure we can decode the body
        bmark = json.loads(res.body)['bmarks'][0]
        self.assertEqual(
            GOOGLE_HASH,
            bmark[u'hash_id'],
            "The hash_id should match: " + str(bmark[u'hash_id']))

        self.assertTrue(
            u'tags' in bmark,
            "We should have a list of tags in the bmark returned")

        self.assertTrue(
            bmark[u'tags'][0][u'name'] in [u'python', u'search'],
            "Tag should be either python or search:" +
            str(bmark[u'tags'][0][u'name']))

        res = self.testapp.get(
            '/api/v1/admin/bmarks?with_content=true&api_key=' + API_KEY,
            status=200)
        self._check_cors_headers(res)

        # make sure we can decode the body
        # @todo this is out because of the issue noted in the code. We'll
        # clean this up at some point.
        # bmark = json.loads(res.body)['bmarks'][0]
        # self.assertTrue('here dude' in bmark[u'readable']['content'],
        #     "There should be content: " + str(bmark))

    def test_bookmark_recent(self):
        """Test that we can get list of bookmarks with details"""
        self._get_good_request(content=True)
        res = self.testapp.get('/api/v1/bmarks?api_key=' + API_KEY,
                               status=200)

        # make sure we can decode the body
        bmark = json.loads(res.body)['bmarks'][0]
        self.assertEqual(
            GOOGLE_HASH,
            bmark[u'hash_id'],
            "The hash_id should match: " + str(bmark[u'hash_id']))

        self.assertTrue(
            u'tags' in bmark,
            "We should have a list of tags in the bmark returned")

        self.assertTrue(
            bmark[u'tags'][0][u'name'] in [u'python', u'search'],
            "Tag should be either python or search:" +
            str(bmark[u'tags'][0][u'name']))

        res = self.testapp.get(
            '/api/v1/admin/bmarks?with_content=true&api_key=' + API_KEY,
            status=200)
        self._check_cors_headers(res)

        # make sure we can decode the body
        # @todo this is out because of the issue noted in the code. We'll
        # clean this up at some point.
        # bmark = json.loads(res.body)['bmarks'][0]
        # self.assertTrue('here dude' in bmark[u'readable']['content'],
        #     "There should be content: " + str(bmark))

    def test_bookmark_sync(self):
        """Test that we can get the sync list from the server"""
        self._get_good_request(content=True, second_bmark=True)

        # test that we only get one resultback
        res = self.testapp.get('/api/v1/admin/extension/sync',
                               params={'api_key': API_KEY},
                               status=200)

        self.assertEqual(
            res.status, "200 OK",
            msg='Get status is 200, ' + res.status)

        self.assertTrue(
            GOOGLE_HASH in res.body,
            "The google hash id should be in the json: " + res.body)
        self.assertTrue(
            BMARKUS_HASH in res.body,
            "The bmark.us hash id should be in the json: " + res.body)
        self._check_cors_headers(res)

    def test_search_api(self):
        """Test that we can get list of bookmarks ordered by clicks"""
        self._get_good_request(content=True, second_bmark=True)

        res = self.testapp.get('/api/v1/bmarks/search/google', status=200)

        # make sure we can decode the body
        bmark_list = json.loads(res.body)
        results = bmark_list['search_results']
        self.assertEqual(
            len(results),
            1,
            "We should have one result coming back: {0}".format(len(results)))

        bmark = results[0]

        self.assertEqual(
            GOOGLE_HASH,
            bmark[u'hash_id'],
            "The hash_id {0} should match: {1} ".format(
                str(GOOGLE_HASH),
                str(bmark[u'hash_id'])))

        self.assertTrue(
            'clicks' in bmark,
            "The clicks field should be in there")
        self._check_cors_headers(res)

    def test_bookmark_tag_complete(self):
        """Test we can complete tags in the system

        By default we should have tags for python, search, bookmarks

        """
        self._get_good_request(second_bmark=True)

        res = self.testapp.get(
            '/api/v1/admin/tags/complete',
            params={
                'tag': 'py',
                'api_key': API_KEY},
            status=200)

        self.assertTrue(
            'python' in res.body,
            "Should have python as a tag completion: " + res.body)

        # we shouldn't get python as an option if we supply bookmarks as the
        # current tag. No bookmarks have both bookmarks & python as tags
        res = self.testapp.get(
            '/api/v1/admin/tags/complete',
            params={
                'tag': u'py',
                'current': u'bookmarks',
                'api_key': API_KEY
            },
            status=200)

        self.assertTrue(
            'python' not in res.body,
            "Should not have python as a tag completion: " + res.body)
        self._check_cors_headers(res)

    def test_account_information(self):
        """Test getting a user's account information"""
        res = self.testapp.get(u'/api/v1/admin/account?api_key=' + API_KEY,
                               status=200)

        # make sure we can decode the body
        user = json.loads(res.body)

        self.assertEqual(
            user['username'], 'admin',
            "Should have a username of admin {0}".format(user))

        self.assertTrue(
            'password' not in user,
            'Should not have a field password {0}'.format(user))
        self.assertTrue(
            '_password' not in user,
            'Should not have a field password {0}'.format(user))
        self.assertTrue(
            'api_key' not in user,
            'Should not have a field password {0}'.format(user))
        self._check_cors_headers(res)

    def test_account_update(self):
        """Test updating a user's account information"""
        params = {
            'name': u'Test Admin'
        }
        res = self.testapp.post(
            str(u"/api/v1/admin/account?api_key=" + str(API_KEY)),
            content_type='application/json',
            params=json.dumps(params),
            status=200)

        # make sure we can decode the body
        user = json.loads(res.body)

        self.assertEqual(
            user['username'], 'admin',
            "Should have a username of admin {0}".format(user))
        self.assertEqual(
            user['name'], 'Test Admin',
            "Should have a new name of Test Admin {0}".format(user))

        self.assertTrue(
            'password' not in user,
            "Should not have a field password {0}".format(user))
        self.assertTrue(
            '_password' not in user,
            "Should not have a field password {0}".format(user))
        self.assertTrue(
            'api_key' not in user,
            "Should not have a field password {0}".format(user))
        self._check_cors_headers(res)

    def test_account_apikey(self):
        """Fetching a user's api key"""
        res = self.testapp.get(
            u"/api/v1/admin/api_key?api_key=" + str(API_KEY),
            status=200)

        # make sure we can decode the body
        user = json.loads(res.body)

        self.assertEqual(
            user['username'], 'admin',
            "Should have a username of admin {0}".format(user))
        self.assertTrue(
            'api_key' in user,
            "Should have an api key in there: {0}".format(user))
        self._check_cors_headers(res)

    def test_account_password_change(self):
        """Change a user's password"""
        params = {
            'current_password': 'admin',
            'new_password': 'not_testing'
        }

        res = self.testapp.post(
            "/api/v1/admin/password?api_key=" + str(API_KEY),
            params=params,
            status=200)

        # make sure we can decode the body
        user = json.loads(res.body)

        self.assertEqual(
            user['username'], 'admin',
            "Should have a username of admin {0}".format(user))
        self.assertTrue(
            'message' in user,
            "Should have a message key in there: {0}".format(user))

        params = {
            'current_password': 'not_testing',
            'new_password': 'admin'
        }
        res = self.testapp.post(
            "/api/v1/admin/password?api_key=" + str(API_KEY),
            params=params,
            status=200)

        self._check_cors_headers(res)

    def test_account_password_failure(self):
        """Change a user's password, in bad ways"""
        params = {
            'current_password': 'test',
            'new_password': 'not_testing'
        }

        res = self.testapp.post(
            "/api/v1/admin/password?api_key=" + str(API_KEY),
            params=params,
            status=403)

        # make sure we can decode the body
        user = json.loads(res.body)

        self.assertEqual(
            user['username'], 'admin',
            "Should have a username of admin {0}".format(user))
        self.assertTrue(
            'error' in user,
            "Should have a error key in there: {0}".format(user))
        self.assertTrue(
            'typo' in user['error'],
            "Should have a error key in there: {0}".format(user))
        self._check_cors_headers(res)

    def test_api_ping_success(self):
        """We should be able to ping and make sure we auth'd and are ok"""
        res = self.testapp.get('/api/v1/admin/ping?api_key=' + API_KEY,
                               status=200)
        ping = json.loads(res.body)

        self.assertTrue(ping['success'])

        self._check_cors_headers(res)

    def test_api_ping_failed_nouser(self):
        """If you don't supply a username, you've failed the ping"""
        res = self.testapp.get('/api/v1/ping?api_key=' + API_KEY,
                               status=200)
        ping = json.loads(res.body)

        self.assertTrue(not ping['success'])
        self.assertEqual(ping['message'], "Missing username in your api url.")
        self._check_cors_headers(res)

    def test_api_ping_failed_missing_api(self):
        """If you don't supply a username, you've failed the ping"""
        res = self.testapp.get('/ping?api_key=' + API_KEY,
                               status=200)
        ping = json.loads(res.body)

        self.assertTrue(not ping['success'])
        self.assertEqual(ping['message'], "The API url should be /api/v1")
        self._check_cors_headers(res)
