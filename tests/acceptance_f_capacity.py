"""MAX_TWO and FULL_NOT_JOINABLE (Increment 2).

Frozen UI contract: a full room has no "Join room" button that is enabled; it
shows a "Full" label and is removed from the joinable list within 3 seconds.
A rejected third join returns a visible role=alert containing "full".
"""
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def unique_nickname(prefix):
    return prefix + uuid.uuid4().hex[:8]


def post_join(target, room_id, nickname):
    request = Request(
        target + '/api/rooms/' + room_id + '/join',
        data=json.dumps({'nickname': nickname}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST')
    try:
        with urlopen(request, timeout=3) as response:
            return response.status
    except HTTPError as error:
        return error.code


def room_id_for(target, creator):
    with urlopen(target + '/api/rooms', timeout=3) as response:
        rooms = json.load(response)['rooms']
    matches = [room['id'] for room in rooms if room.get('creator_nickname') == creator]
    if len(matches) != 1:
        raise AssertionError('expected exactly one waiting room for creator, got %d' % len(matches))
    return matches[0]


class JoinCapacity(AcceptanceTest):
    def room_id_for(self, creator):
        return room_id_for(self.target, creator)

    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        return page, errors

    def test_third_join_rejected_visibly_roster_unchanged(self):
        creator = unique_nickname('c')
        second = unique_nickname('s')
        third = unique_nickname('t')

        home, home_errors = self.open_home()
        home.get_by_label('Nickname', exact=True).fill(creator)
        home.get_by_role('button', name='Create room').click()
        expect(home.get_by_text('waiting for an opponent', exact=False)).to_be_visible(timeout=3000)

        room_id = self.room_id_for(creator)

        # Third visitor opens the join form while the room still has one player.
        third_page, third_errors = self.open_home()
        third_join = third_page.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(third_join).to_be_visible(timeout=3000)
        third_join.click()
        third_page.get_by_label('Join nickname', exact=True).fill(third)

        self.assertEqual(post_join(self.target, room_id, second), 200)

        third_page.get_by_role('button', name='Join this room', exact=True).click()
        expect(third_page.get_by_role('alert')).to_contain_text('full', timeout=3000)

        status = post_join(self.target, room_id, third)
        self.assertEqual(status, 409, 'third join must be rejected with 409')

        with urlopen(self.target + '/api/rooms/' + room_id, timeout=3) as response:
            roster = json.load(response)['players']
        self.assertEqual(roster, [creator, second], 'third join must not change the roster')
        self.assertEqual(home_errors, [])
        self.assertEqual(third_errors, [])

    def test_full_room_not_joinable_in_second_context_within_3_seconds(self):
        creator = unique_nickname('f')
        second = unique_nickname('g')

        create_request = Request(
            self.target + '/api/rooms',
            data=json.dumps({'nickname': creator}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST')
        with urlopen(create_request, timeout=3) as response:
            self.assertIn(response.status, (200, 201), 'setup POST /api/rooms must succeed')

        watcher, watcher_errors = self.open_home()
        expect(watcher.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)).to_be_visible(timeout=3000)

        room_id = self.room_id_for(creator)
        self.assertEqual(post_join(self.target, room_id, second), 200)

        started = time.monotonic()
        full_row = watcher.locator('li', has_text=creator)
        while True:
            if full_row.count() == 0:
                break
            full_label = full_row.get_by_text('Full', exact=True)
            join_buttons = full_row.get_by_role('button', name='Join room', exact=True)
            if full_label.count() and full_label.first.is_visible() and (join_buttons.count() == 0 or join_buttons.first.is_disabled()):
                break
            if time.monotonic() - started > 3.0:
                raise AssertionError('full room must be removed from the list or shown as Full with no enabled join control within 3 seconds')
            time.sleep(0.1)
        self.assertLessEqual(time.monotonic() - started, 3.0)
        self.assertEqual(watcher_errors, [])
