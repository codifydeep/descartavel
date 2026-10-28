"""NICK_REQUIRED and NICK_LIMIT on the create path (Increment 1)."""
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def unique_nickname(length=8):
    return 'n' + uuid.uuid4().hex[:length]


def fetch_rooms(target):
    try:
        with urlopen(target + '/api/rooms', timeout=3) as response:
            payload = json.load(response)
            return response.status, payload.get('rooms') if isinstance(payload, dict) else payload
    except HTTPError as error:
        return error.code, None
    except URLError:
        return None, None


class NicknameRules(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname')).to_be_visible(timeout=3000)
        expect(page.get_by_role('button', name='Create room')).to_be_visible(timeout=3000)
        return page, errors

    def assert_rejected_without_room(self, nickname_value):
        status, before = fetch_rooms(self.target)
        self.assertEqual(status, 200, 'GET /api/rooms must return 200 before submit')
        page, errors = self.open_home()
        page.get_by_label('Nickname').fill(nickname_value)
        page.get_by_role('button', name='Create room').click()
        expect(page.get_by_role('alert')).to_be_visible(timeout=3000)
        self.assertIn('nickname', page.get_by_role('alert').inner_text().lower())
        status, after = fetch_rooms(self.target)
        self.assertEqual(status, 200, 'GET /api/rooms must return 200 after rejected submit')
        self.assertEqual(after, before, 'rejected nickname must not create a room')
        self.assertEqual(errors, [])

    def test_empty_nickname_rejected_visibly_no_room_created(self):
        self.assert_rejected_without_room('')

    def test_whitespace_only_nickname_rejected_visibly_no_room_created(self):
        self.assert_rejected_without_room('   \t  ')

    def test_21_character_nickname_rejected_visibly_no_room_created(self):
        self.assert_rejected_without_room('x' * 21)

    def test_20_character_nickname_after_trim_accepted(self):
        nickname = unique_nickname(19)
        self.assertEqual(len(nickname), 20)
        page, errors = self.open_home()
        page.get_by_label('Nickname').fill('   ' + nickname + '   ')
        page.get_by_role('button', name='Create room').click()
        expect(page.get_by_text(nickname, exact=False).first).to_be_visible(timeout=3000)
        self.assertEqual(errors, [])
