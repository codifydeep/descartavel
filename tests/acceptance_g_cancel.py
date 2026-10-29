"""Lobby cancellation (lobby-cancel increment).

Named to sort after acceptance_a_empty_list.py and acceptance_f_capacity.py,
so EMPTY_LIST still observes an empty server and this file's rooms never
leak into earlier cases.

Frozen UI contract (implementation must match):
- the creator's room view shows a button named "Cancel room" only while the
  room is waiting; it is absent or disabled once the room is full or cancelled
- the home list and room view show no "Cancel room" control to visitors
- a cancelled room leaves the home list; the room id still resolves with
  state "cancelled"
- a join on a cancelled room shows a role=alert containing
  "This room was cancelled." and the roster does not change

Creator identity is the existing per-browser creator context. Requests made
from the creator's page (page.evaluate fetch) carry that context; requests
made with plain urllib carry none and act as a visitor.
"""
import json
import re
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


CANCELLED_MESSAGE = 'This room was cancelled.'


def unique_nickname(prefix):
    return prefix + uuid.uuid4().hex[:8]


def post_json(target, path, payload):
    request = Request(
        target + path,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST')
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        body = error.read().decode('utf-8', 'replace')
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {'raw': body}


def get_room(target, room_id):
    with urlopen(target + '/api/rooms/' + room_id, timeout=3) as response:
        return json.load(response)


def waiting_room_ids(target):
    with urlopen(target + '/api/rooms', timeout=3) as response:
        return [room['id'] for room in json.load(response)['rooms']]


class CancelRoom(AcceptanceTest):
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

    def create_room_in_browser(self, page, nickname):
        page.get_by_label('Nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Create room').click()
        expect(page.get_by_text('waiting for an opponent', exact=False)).to_be_visible(timeout=3000)

    def room_id_for_creator(self, creator):
        with urlopen(self.target + '/api/rooms', timeout=3) as response:
            rooms = json.load(response)['rooms']
        matches = [room['id'] for room in rooms if room.get('creator_nickname') == creator]
        if len(matches) != 1:
            raise AssertionError('expected exactly one waiting room for creator, got %d' % len(matches))
        return matches[0]

    def test_creator_cancel_removes_waiting_room_from_home_list(self):
        creator = unique_nickname('k')
        page, errors = self.open_home()
        self.create_room_in_browser(page, creator)
        room_id = self.room_id_for_creator(creator)

        cancel = page.get_by_role('button', name='Cancel room', exact=True)
        expect(cancel).to_be_visible(timeout=3000)
        cancel.click()

        started = time.monotonic()
        while time.monotonic() - started <= 3.0:
            if room_id not in waiting_room_ids(self.target):
                break
            time.sleep(0.1)
        self.assertNotIn(room_id, waiting_room_ids(self.target), 'cancelled room must leave GET /api/rooms')
        self.assertEqual(get_room(self.target, room_id)['state'], 'cancelled')
        expect(page.locator('li', has_text=creator).get_by_role('button', name='Cancel room', exact=True)).to_have_count(0, timeout=3000)
        self.assertEqual(errors, [])

    def test_visitor_sees_no_cancel_control_and_non_creator_cancel_rejected(self):
        creator = unique_nickname('n')
        page, _ = self.open_home()
        self.create_room_in_browser(page, creator)
        room_id = self.room_id_for_creator(creator)

        visitor, visitor_errors = self.open_home()
        expect(visitor.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)).to_be_visible(timeout=3000)
        self.assertEqual(visitor.get_by_role('button', name='Cancel room', exact=True).count(), 0)

        status, body = post_json(self.target, '/api/rooms/' + room_id + '/cancel', {})
        self.assertEqual(status, 403, 'a request without the creator context must be rejected with 403')
        self.assertIsInstance(body.get('error'), str)
        self.assertTrue(body['error'].strip(), 'the 403 must carry an English message')
        self.assertEqual(get_room(self.target, room_id)['state'], 'waiting', 'rejected cancel must leave the room waiting')
        self.assertEqual(visitor_errors, [])

    def test_full_room_has_no_enabled_cancel_and_server_rejects_cancel_409(self):
        creator = unique_nickname('p')
        second = unique_nickname('q')
        page, errors = self.open_home()
        self.create_room_in_browser(page, creator)
        room_id = self.room_id_for_creator(creator)

        status, _ = post_json(self.target, '/api/rooms/' + room_id + '/join', {'nickname': second})
        self.assertEqual(status, 200, 'setup join must succeed')

        expect(page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text([creator, second], timeout=3000)
        cancel = page.get_by_role('button', name='Cancel room', exact=True)
        self.assertTrue(cancel.count() == 0 or cancel.first.is_disabled() or not cancel.first.is_visible(),
                        'a full room must show no enabled cancel control')

        response = page.request.post(
            self.target + '/api/rooms/' + room_id + '/cancel',
            headers={'Content-Type': 'application/json'},
            data='{}')
        result = {'status': response.status, 'body': response.json()}
        self.assertEqual(result['status'], 409, 'cancelling a full room must return 409')
        self.assertTrue(result['body'].get('error', '').strip(), 'the 409 must carry an English message')
        self.assertEqual(get_room(self.target, room_id)['players'], [creator, second], 'roster must be unchanged')
        self.assertEqual(get_room(self.target, room_id)['state'], 'full')
        self.assertEqual(errors, [])

    def test_cancel_propagates_to_second_context_home_list_within_3_seconds(self):
        creator = unique_nickname('r')
        page, _ = self.open_home()
        self.create_room_in_browser(page, creator)
        room_id = self.room_id_for_creator(creator)

        watcher, watcher_errors = self.open_home()
        watched = watcher.locator('li', has_text=creator)
        expect(watched.get_by_role('button', name='Join room', exact=True)).to_be_visible(timeout=3000)

        cancel = page.get_by_role('button', name='Cancel room', exact=True)
        expect(cancel).to_be_visible(timeout=3000)
        cancel.click()

        started = time.monotonic()
        while True:
            if watched.count() == 0 or watched.get_by_role('button', name='Join room', exact=True).count() == 0:
                break
            if time.monotonic() - started > 3.0:
                raise AssertionError('cancelled room must leave the home list within 3 seconds')
            time.sleep(0.1)
        self.assertLessEqual(time.monotonic() - started, 3.0)
        self.assertEqual(get_room(self.target, room_id)['state'], 'cancelled')
        self.assertEqual(watcher_errors, [])

    def test_join_cancelled_room_shows_english_message_and_roster_unchanged(self):
        creator = unique_nickname('u')
        visitor_nickname = unique_nickname('v')
        creator_page, creator_errors = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = self.room_id_for_creator(creator)

        visitor, visitor_errors = self.open_home()
        join_button = visitor.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click()
        visitor.get_by_label('Join nickname', exact=True).fill(visitor_nickname)

        # Freeze the visitor's home-list poll on the pre-cancel list so the
        # open join form stays on screen; the join still goes to the server,
        # which answers with the real cancelled state.
        stale_list = json.dumps({'rooms': [get_room(self.target, room_id)]})
        visitor.route(re.compile(r'/api/rooms$'),
                      lambda route: route.fulfill(status=200, content_type='application/json', body=stale_list))

        cancel = creator_page.get_by_role('button', name='Cancel room', exact=True)
        expect(cancel).to_be_visible(timeout=3000)
        cancel.click()
        expect(creator_page.get_by_text(re.compile('cancelled', re.IGNORECASE)).first).to_be_visible(timeout=3000)

        visitor.get_by_role('button', name='Join this room', exact=True).click(timeout=3000)
        expect(visitor.get_by_role('alert')).to_contain_text(CANCELLED_MESSAGE, timeout=3000)

        status, body = post_json(self.target, '/api/rooms/' + room_id + '/join', {'nickname': visitor_nickname})
        self.assertEqual(status, 409, 'join on a cancelled room must return 409')
        self.assertEqual(body.get('error'), CANCELLED_MESSAGE)
        self.assertEqual(get_room(self.target, room_id)['players'], [creator], 'roster must be unchanged')
        self.assertEqual(creator_errors, [])
        self.assertEqual(visitor_errors, [])
