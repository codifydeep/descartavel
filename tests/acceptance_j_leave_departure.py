"""Explicit leave of a full two-player room (lobby-leave-departure, Increment 1).

Frozen UI and API contract (implementation must match):
- POST /api/rooms/{id}/leave leaves the room for the caller's browser context.
- the "Leave room" button (role button, exact name) is shown only in a full
  room to its two participants; absent in a waiting room
- a leaver's browser returns to the lobby list (Create room form visible, own
  room section hidden) on a successful leave
- waiting-room leave: 409 with an English message, state unchanged
- non-participant or already-departed browser leave: 403 with an English
  message, state unchanged
- joiner leaves: creator stays owner; room is waiting with the creator only
- creator leaves: the remaining participant becomes owner and sees the
  "Cancel room" control; room is waiting
- any successful departure clears both Ready states
- remaining participant's view updates within 3 seconds (time.monotonic())
"""
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


LIMIT_SECONDS = 3.0


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


def room_id_for(target, creator):
    with urlopen(target + '/api/rooms', timeout=3) as response:
        rooms = json.load(response)['rooms']
    matches = [room['id'] for room in rooms if room.get('creator_nickname') == creator]
    if len(matches) != 1:
        raise AssertionError('expected exactly one waiting room for creator, got %d' % len(matches))
    return matches[0]


class LeaveDeparture(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        expect(page.get_by_role('button', name='Create room')).to_be_visible(timeout=3000)
        return page

    def create_room_in_browser(self, page, nickname):
        page.get_by_label('Nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Create room').click(timeout=3000)
        expect(page.get_by_text('waiting for an opponent', exact=False)).to_be_visible(timeout=3000)

    def join_room_in_browser(self, page, creator, nickname):
        join_button = page.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click(timeout=3000)
        page.get_by_label('Join nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Join this room', exact=True).click(timeout=3000)
        expect(page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, nickname], timeout=3000)

    def full_room_pair(self, prefix_creator, prefix_joiner):
        creator = unique_nickname(prefix_creator)
        joiner = unique_nickname(prefix_joiner)
        creator_page = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)
        joiner_page = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)
        expect(creator_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, joiner], timeout=3000)
        return {
            'creator': creator,
            'joiner': joiner,
            'room_id': room_id,
            'creator_page': creator_page,
            'joiner_page': joiner_page,
        }

    def wait_until(self, predicate, message):
        """Poll predicate until true within LIMIT_SECONDS; return elapsed seconds."""
        started = time.monotonic()
        while True:
            if predicate():
                return time.monotonic() - started
            if time.monotonic() - started > LIMIT_SECONDS:
                raise AssertionError(message)
            time.sleep(0.1)

    def shows_lobby(self, page):
        return page.get_by_role('button', name='Create room').is_visible()

    def click_leave(self, page):
        control = page.get_by_role('button', name='Leave room', exact=True)
        self.assertEqual(control.count(), 1, 'a full room must offer exactly one Leave room control')
        control.click(timeout=3000)

    def assert_lobby(self, page, message):
        self.wait_until(lambda: self.shows_lobby(page), message)

    def shows_waiting_with_roster(self, page, players):
        roster = page.get_by_role('list', name='Roster').get_by_role('listitem')
        return (page.get_by_text('waiting for an opponent', exact=False).is_visible()
                and roster.all_inner_texts() == players)

    def test_waiting_room_has_no_leave_control_and_leave_is_409(self):
        creator = unique_nickname('w')
        creator_page = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)

        expect(creator_page.get_by_role('button', name='Leave room', exact=True)).to_have_count(0)

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/leave',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertEqual(response.status, 409, 'leaving a waiting room must return 409')
        self.assertTrue(response.json().get('error', '').strip(), 'the 409 must carry an English message')
        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'waiting', 'rejected leave must leave the room waiting')
        self.assertEqual(room['players'], [creator], 'rejected leave must leave the roster unchanged')

    def test_non_participant_leave_is_403_and_state_unchanged(self):
        creator = unique_nickname('n')
        joiner = unique_nickname('m')
        pair = self.full_room_pair('n', 'm')
        room_id = pair['room_id']

        status, body = post_json(self.target, '/api/rooms/' + room_id + '/leave', {})
        self.assertEqual(status, 403, 'a leave without participant context must be rejected with 403')
        self.assertTrue(str(body.get('error', '')).strip(), 'the 403 must carry an English message')
        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'full', 'rejected leave must leave the room full')
        self.assertEqual(room['players'], [pair['creator'], pair['joiner']])

    def test_second_leave_by_departed_browser_is_403(self):
        pair = self.full_room_pair('s', 't')
        room_id = pair['room_id']
        joiner_page = pair['joiner_page']

        self.click_leave(joiner_page)
        self.wait_until(lambda: get_room(self.target, room_id)['players'] == [pair['creator']],
                        'first leave must remove the joiner')

        response = joiner_page.request.post(
            self.target + '/api/rooms/' + room_id + '/leave',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertEqual(response.status, 403, 'a second leave by the departed browser must return 403')
        self.assertTrue(response.json().get('error', '').strip(), 'the 403 must carry an English message')
        room = get_room(self.target, room_id)
        self.assertEqual(room['players'], [pair['creator']], 'stale second leave must not change the roster')
        self.assertEqual(room['state'], 'waiting', 'stale second leave must not change the state')

    def test_cancelled_room_stale_leave_maps_to_existing_error_and_no_change(self):
        creator = unique_nickname('x')
        creator_page = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)

        cancel = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/cancel',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertEqual(cancel.status, 200, 'setup cancel must succeed')

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/leave',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertNotEqual(response.status, 200, 'a stale leave on a cancelled room must not succeed')
        self.assertTrue(response.json().get('error', '').strip(), 'the stale error must carry an English message')
        self.assertEqual(get_room(self.target, room_id)['state'], 'cancelled',
                         'a stale leave on a cancelled room must not change its state')

    def test_joiner_leave_returns_joiner_to_lobby_and_creator_stays_owner_within_3_seconds(self):
        pair = self.full_room_pair('j', 'k')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']

        self.click_leave(joiner_page)
        self.assert_lobby(joiner_page, 'a departed browser must return to the lobby list')
        self.assertEqual(joiner_page.get_by_role('button', name='Leave room', exact=True).count(), 0)

        started = time.monotonic()
        self.wait_until(lambda: self.shows_waiting_with_roster(creator_page, [pair['creator']]),
                        'creator browser must show the waiting room with only the creator within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'waiting')
        self.assertEqual(room['players'], [pair['creator']])
        expect(creator_page.get_by_role('button', name='Cancel room', exact=True)).to_be_visible(timeout=3000)
        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/cancel',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertEqual(response.status, 200, 'the creator must remain the owner and may cancel the waiting room')

    def test_creator_leave_transfers_ownership_and_cancel_control_within_3_seconds(self):
        pair = self.full_room_pair('c', 'd')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']

        self.click_leave(creator_page)
        self.assert_lobby(creator_page, 'a departed browser must return to the lobby list')

        started = time.monotonic()
        self.wait_until(lambda: self.shows_waiting_with_roster(joiner_page, [pair['joiner']]),
                        'remaining participant must show the waiting room with only itself within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        expect(joiner_page.get_by_role('button', name='Cancel room', exact=True)).to_be_visible(timeout=3000)
        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'waiting')
        self.assertEqual(room['players'], [pair['joiner']])
        response = joiner_page.request.post(
            self.target + '/api/rooms/' + room_id + '/cancel',
            headers={'Content-Type': 'application/json'},
            data='{}')
        self.assertEqual(response.status, 200, 'the remaining participant must become the owner with cancellation right')

    def test_departure_clears_both_ready_states(self):
        pair = self.full_room_pair('r', 's')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']

        creator_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(creator_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        joiner_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(joiner_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        self.assertEqual(get_room(self.target, room_id)['ready'], [True, True])

        self.click_leave(joiner_page)
        self.assert_lobby(joiner_page, 'a departed browser must return to the lobby list')

        self.wait_until(lambda: self.shows_waiting_with_roster(creator_page, [pair['creator']]),
                        'creator browser must show the waiting room within 3 seconds')
        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'waiting')
        self.assertFalse(any(room['ready']), 'no Ready state may persist into the waiting room')
        expect(creator_page.get_by_text('Ready to play', exact=True)).to_have_count(0)
        expect(creator_page.get_by_role('button', name='Mark ready', exact=True)).to_have_count(0)

    def test_create_and_join_flow_still_works(self):
        creator = unique_nickname('z')
        joiner = unique_nickname('y')
        status, body = post_json(self.target, '/api/rooms', {'nickname': creator})
        self.assertEqual(status, 201, 'create must keep returning 201')
        room_id = body['id']
        status, body = post_json(self.target, '/api/rooms/' + room_id + '/join', {'nickname': joiner})
        self.assertEqual(status, 200, 'join must keep returning 200')
        self.assertEqual(body['players'], [creator, joiner])
        self.assertEqual(body['state'], 'full')
