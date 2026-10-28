"""NICK_REQUIRED and NICK_LIMIT on the join path (Increment 2).

Named to sort after acceptance_a_empty_list.py, so EMPTY_LIST still observes
an empty server first in the full-suite run.

Frozen UI contract for Increment 2 (implementation must match):
- each listed joinable room is an <li> containing the creator nickname and a
  button named "Join room"
- clicking it reveals an input labelled "Join nickname" and a button named
  "Join this room"
- a rejected join shows a role=alert message containing the word "nickname"
"""
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def unique_nickname(prefix, length=8):
    return prefix + uuid.uuid4().hex[:length]


def fetch_json(url):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None
    except URLError:
        return None, None


def create_room(target, nickname):
    request = Request(
        target + '/api/rooms',
        data=json.dumps({'nickname': nickname}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST')
    with urlopen(request, timeout=3) as response:
        return json.load(response)


class JoinNicknameRules(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        return page, errors

    def join_rejected_roster_unchanged(self, join_value):
        creator = unique_nickname('j')
        room = create_room(self.target, creator)
        status, before = fetch_json(self.target + '/api/rooms/' + room['id'])
        self.assertEqual(status, 200, 'GET /api/rooms/{id} must return 200 before join')
        self.assertEqual(before['players'], [creator])

        page, errors = self.open_home()
        join_button = page.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click()
        page.get_by_label('Join nickname', exact=True).fill(join_value)
        page.get_by_role('button', name='Join this room', exact=True).click()
        expect(page.get_by_role('alert')).to_be_visible(timeout=3000)
        self.assertIn('nickname', page.get_by_role('alert').inner_text().lower())

        status, after = fetch_json(self.target + '/api/rooms/' + room['id'])
        self.assertEqual(status, 200, 'GET /api/rooms/{id} must return 200 after rejected join')
        self.assertEqual(after['players'], [creator], 'rejected join nickname must not join the room')
        self.assertEqual(errors, [])

    def test_join_empty_nickname_rejected_visibly_roster_unchanged(self):
        self.join_rejected_roster_unchanged('')

    def test_join_whitespace_only_nickname_rejected_visibly_roster_unchanged(self):
        self.join_rejected_roster_unchanged('   \t  ')

    def test_join_21_character_nickname_rejected_visibly_roster_unchanged(self):
        self.join_rejected_roster_unchanged('y' * 21)

    def test_join_20_character_nickname_after_trim_accepted(self):
        creator = unique_nickname('j')
        room = create_room(self.target, creator)
        joiner = unique_nickname('k', 19)
        self.assertEqual(len(joiner), 20)

        page, errors = self.open_home()
        join_button = page.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click()
        page.get_by_label('Join nickname', exact=True).fill('   ' + joiner + '   ')
        page.get_by_role('button', name='Join this room', exact=True).click()

        roster = page.get_by_role('list', name='Roster')
        expect(roster.get_by_role('listitem')).to_have_text([creator, joiner], timeout=3000)
        status, after = fetch_json(self.target + '/api/rooms/' + room['id'])
        self.assertEqual(status, 200)
        self.assertEqual(after['players'], [creator, joiner])
        self.assertEqual(errors, [])
