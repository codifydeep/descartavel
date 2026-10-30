"""Ready marking (ready-mark increment, Increment 1).

Frozen UI and API contract (implementation must match):
- a full room (two players) shows, for the viewer when the viewer is a
  participant, a button named "Mark ready" while the viewer is not ready and
  "Unmark ready" while the viewer is ready; a waiting room and non-participants
  show no ready control
- each roster item (list aria-label "Roster") carries data-ready="true" or
  data-ready="false" for that participant
- a full room whose participants are not both ready shows the status text
  "Waiting for readiness" exactly
- POST /api/rooms/{id}/ready with JSON {"ready": true|false} sets only the
  caller's own flag; the caller is identified by the per-browser context
  cookie. Response is the room view.
- GET /api/rooms/{id} and POST join/ready responses carry "ready": [bool, bool],
  aligned with "players" (creator first).
- waiting room: 409 with an English message, state unchanged
- non-participant (no participant context): 403 with an English message,
  state unchanged
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


def ready_flags(target, room_id):
    """Return the room's ready list, or None when the server omits it (assertion-visible)."""
    return get_room(target, room_id).get('ready')


def room_id_for(target, creator):
    with urlopen(target + '/api/rooms', timeout=3) as response:
        rooms = json.load(response)['rooms']
    matches = [room['id'] for room in rooms if room.get('creator_nickname') == creator]
    if len(matches) != 1:
        raise AssertionError('expected exactly one waiting room for creator, got %d' % len(matches))
    return matches[0]


def roster_ready(page, nickname):
    """Return the data-ready attribute of the roster item for nickname, or None."""
    return page.evaluate(
        """(name) => {
            const items = Array.from(document.querySelectorAll('[aria-label="Roster"] li'));
            const item = items.find((li) => li.textContent === name);
            return item ? item.getAttribute('data-ready') : null;
        }""",
        nickname)


class ReadyMark(AcceptanceTest):
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

    def join_room_in_browser(self, page, creator, nickname):
        join_button = page.locator('li', has_text=creator).get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click()
        page.get_by_label('Join nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Join this room', exact=True).click()
        expect(page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, nickname], timeout=3000)

    def full_room_pair(self, prefix_creator, prefix_joiner):
        """Create a room in one browser and join it from a second; return the pieces."""
        creator = unique_nickname(prefix_creator)
        joiner = unique_nickname(prefix_joiner)
        creator_page, creator_errors = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)
        joiner_page, joiner_errors = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)
        return {
            'creator': creator,
            'joiner': joiner,
            'room_id': room_id,
            'creator_page': creator_page,
            'joiner_page': joiner_page,
            'errors': creator_errors + joiner_errors,
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

    def ready_button(self, page, label):
        return page.get_by_role('button', name=label, exact=True)

    def test_participant_marks_and_unmarks_own_ready_only(self):
        pair = self.full_room_pair('m', 'n')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator = pair['creator']
        joiner = pair['joiner']

        expect(self.ready_button(creator_page, 'Mark ready')).to_be_visible(timeout=3000)
        expect(self.ready_button(joiner_page, 'Mark ready')).to_be_visible(timeout=3000)
        expect(creator_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        expect(joiner_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)

        self.ready_button(creator_page, 'Mark ready').click()
        expect(self.ready_button(creator_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: ready_flags(self.target, pair['room_id']) == [True, False],
                        'creator ready must be stored for the creator slot only')
        self.assertEqual(ready_flags(self.target, pair['room_id']), [True, False])
        self.assertEqual(self.ready_button(joiner_page, 'Mark ready').count(), 1,
                         'joiner must still see their own Mark ready control')

        self.ready_button(joiner_page, 'Mark ready').click()
        expect(self.ready_button(joiner_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: ready_flags(self.target, pair['room_id']) == [True, True],
                        'joiner ready must be stored for the joiner slot only')

        self.ready_button(creator_page, 'Unmark ready').click()
        expect(self.ready_button(creator_page, 'Mark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: ready_flags(self.target, pair['room_id']) == [False, True],
                        'unmarking creator must not change the joiner ready state')
        self.assertEqual(ready_flags(self.target, pair['room_id']), [False, True])
        expect(self.ready_button(joiner_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.assertEqual(pair['errors'], [])

    def test_ready_controls_only_in_full_room_and_waiting_request_409(self):
        creator = unique_nickname('w')
        creator_page, creator_errors = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)

        self.assertEqual(self.ready_button(creator_page, 'Mark ready').count(), 0,
                         'a waiting room must show no Mark ready control')
        self.assertEqual(self.ready_button(creator_page, 'Unmark ready').count(), 0,
                         'a waiting room must show no Unmark ready control')

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/ready',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({'ready': True}))
        self.assertEqual(response.status, 409, 'ready on a waiting room must return 409')
        body = response.json()
        self.assertIsInstance(body.get('error'), str)
        self.assertTrue(body['error'].strip(), 'the 409 must carry an English message')
        room = get_room(self.target, room_id)
        self.assertEqual(room['players'], [creator], 'roster must be unchanged')
        self.assertEqual(ready_flags(self.target, room_id), [False], 'ready state must be unchanged')
        self.assertEqual(creator_errors, [])

    def test_non_participant_ready_request_403_and_no_control(self):
        pair = self.full_room_pair('x', 'y')
        room_id = pair['room_id']
        self.assertEqual(ready_flags(self.target, room_id), [False, False])

        status, body = post_json(self.target, '/api/rooms/' + room_id + '/ready', {'ready': True})
        self.assertEqual(status, 403, 'a non-participant ready request must return 403')
        self.assertIsInstance(body.get('error'), str)
        self.assertTrue(body['error'].strip(), 'the 403 must carry an English message')

        visitor, visitor_errors = self.open_home()
        visitor_response = visitor.request.post(
            self.target + '/api/rooms/' + room_id + '/ready',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({'ready': True}))
        self.assertEqual(visitor_response.status, 403, 'a visitor browser must be rejected with 403')
        self.assertTrue(visitor_response.json().get('error', '').strip())
        self.assertEqual(self.ready_button(visitor, 'Mark ready').count(), 0,
                         'a visitor must see no Mark ready control in a full room')

        self.assertEqual(ready_flags(self.target, room_id), [False, False],
                         'rejected requests must leave ready state unchanged')
        self.assertEqual(get_room(self.target, room_id).get('players'), [pair['creator'], pair['joiner']])
        self.assertEqual(visitor_errors, [])
        self.assertEqual(pair['errors'], [])

    def test_both_browsers_show_same_ready_state_within_3_seconds(self):
        pair = self.full_room_pair('s', 't')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator = pair['creator']
        joiner = pair['joiner']

        expect(creator_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_count(2, timeout=3000)
        self.wait_until(lambda: roster_ready(creator_page, creator) == 'false' and roster_ready(joiner_page, joiner) == 'false',
                        'both browsers must start with both participants not ready')

        started = time.monotonic()
        self.ready_button(creator_page, 'Mark ready').click()
        self.wait_until(lambda: roster_ready(joiner_page, creator) == 'true',
                        'joiner browser must show creator ready within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)
        self.assertEqual(roster_ready(creator_page, creator), 'true')
        self.assertEqual(roster_ready(creator_page, joiner), 'false')
        self.assertEqual(roster_ready(joiner_page, joiner), 'false')

        started = time.monotonic()
        self.ready_button(joiner_page, 'Mark ready').click()
        self.wait_until(lambda: roster_ready(creator_page, joiner) == 'true',
                        'creator browser must show joiner ready within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)
        self.assertEqual(roster_ready(joiner_page, joiner), 'true')
        self.assertEqual(roster_ready(joiner_page, creator), 'true')

        started = time.monotonic()
        self.ready_button(creator_page, 'Unmark ready').click()
        self.wait_until(lambda: roster_ready(joiner_page, creator) == 'false',
                        'joiner browser must show creator unmarked within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)
        self.assertEqual(roster_ready(creator_page, creator), 'false')
        self.assertEqual(roster_ready(creator_page, joiner), 'true')
        self.assertEqual(roster_ready(joiner_page, joiner), 'true')
        expect(creator_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        expect(joiner_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        self.assertEqual(pair['errors'], [])
