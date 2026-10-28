"""JOIN_ROOM: a second nicknamed visitor joins a listed room; both browser
contexts show the same two-player roster within 3 seconds, without reload.

Frozen UI contract (see acceptance_d_join_nickname_rules.py): join button
"Join room", join input "Join nickname", submit "Join this room". The room
view roster is a list with accessible name "Roster" whose items are the
player nicknames, in join order.
"""
import re
import time
import uuid

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def unique_nickname(prefix):
    return prefix + uuid.uuid4().hex[:8]


class JoinRoster(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        expect(page.get_by_role('button', name='Create room')).to_be_visible(timeout=3000)
        return page, errors

    def test_join_listed_room_shows_same_two_player_roster_in_both_contexts(self):
        creator_nickname = unique_nickname('a')
        joiner_nickname = unique_nickname('b')

        creator_page, creator_errors = self.open_home()
        creator_page.get_by_label('Nickname', exact=True).fill(creator_nickname)
        creator_page.get_by_role('button', name='Create room').click()
        expect(creator_page.get_by_text(re.compile(r'waiting for an opponent', re.IGNORECASE))).to_be_visible(timeout=3000)

        joiner_page, joiner_errors = self.open_home()
        join_button = joiner_page.locator('li', has_text=creator_nickname).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click()
        joiner_page.get_by_label('Join nickname', exact=True).fill(joiner_nickname)

        started = time.monotonic()
        joiner_page.get_by_role('button', name='Join this room', exact=True).click()

        expected = [creator_nickname, joiner_nickname]
        expect(joiner_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(expected, timeout=3000)
        expect(creator_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(expected, timeout=3000)
        elapsed = time.monotonic() - started
        self.assertLessEqual(elapsed, 3.0, 'both contexts must show the roster within 3 seconds')
        self.assertEqual(creator_errors, [])
        self.assertEqual(joiner_errors, [])
