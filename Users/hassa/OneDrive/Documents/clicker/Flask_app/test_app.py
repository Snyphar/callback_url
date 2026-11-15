import tempfile
import unittest
from pathlib import Path
from app import create_app

class LoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'DATABASE': str(Path(self.temp.name) / 'db.sqlite')}).test_client()

    def form(self):
        self.client.get('/verify')
        with self.client.session_transaction() as state:
            return {'csrf': state['csrf']}

    def test_checkbox_opens_login(self):
        data = self.form()
        response = self.client.post('/verify', data={**data, 'human': 'yes'})
        self.assertTrue(response.location.endswith('/login'))
        self.assertIn(b'name="password"', self.client.get('/login').data)
        self.assertEqual(self.client.post('/login', data={**data, 'username': 'demo', 'password': 'ChangeMe123!'}).status_code, 302)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_missing_checkbox_and_csrf(self):
        self.assertEqual(self.client.post('/verify', data=self.form()).status_code, 400)
        self.assertEqual(self.client.post('/verify', data={'human': 'yes'}).status_code, 400)
        self.assertTrue(self.client.get('/login').location.endswith('/verify'))

if __name__ == '__main__':
    unittest.main()
