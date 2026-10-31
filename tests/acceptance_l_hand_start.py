"""Hand start (hand-start package, Increment 1 pre-hand gate).

Frozen UI and API contract (implementation must match):
- the room section shows the English button "Start hand" only when the room is
  full, both participants are Ready, and no hand has started or finished;
  it is hidden in every other state, in both participants' browsers
- POST /api/rooms/<id>/start by a seated participant of a full room with both
  Ready starts one hand and returns 200 with the room view
- a non-participant gets 403 with an English error and no state change
- a request when the room is not full, not both Ready, or already started
  returns 409 with an English error and no state change
- after a successful start, every later start returns 409 with no state change
- unmarking Ready or leaving after both are Ready hides the Start hand control
  and starts nothing
- every propagation bound is 3 seconds, asserted with time.monotonic()
"""
import json
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


LIMIT_SECONDS = 3.0


def unique_nickname(prefix):
    return prefix + uuid.uuid4().hex[:8]


def post_json(target, path, payload, cookie=None):
    headers = {'Content-Type': 'application/json'}
    if cookie:
        headers['Cookie'] = cookie
    request = Request(
        target + path,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
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


class HandStart(AcceptanceTest):
    def open_home(self):
        context = self.new_context()
        page = context.new_page()
        errors = self._browser_errors
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        expect(page.get_by_role('button', name='Create room')).to_be_visible(timeout=3000)
        return page, errors

    def create_room_in_browser(self, page, nickname):
        page.get_by_label('Nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Create room').click(timeout=3000)
        expect(page.get_by_text('waiting for an opponent', exact=False)).to_be_visible(timeout=3000)

    def join_room_in_browser(self, page, creator, nickname):
        join_button = page.locator('#room-list > li', has_text=creator).get_by_role(
            'button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click(timeout=3000)
        page.get_by_label('Join nickname', exact=True).fill(nickname)
        page.get_by_role('button', name='Join this room', exact=True).click(timeout=3000)
        expect(page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, nickname], timeout=3000)

    def full_room_pair(self, prefix_creator, prefix_joiner):
        creator = unique_nickname(prefix_creator)
        joiner = unique_nickname(prefix_joiner)
        creator_page, _ = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)
        joiner_page, _ = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)
        expect(creator_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, joiner], timeout=3000)
        expect(creator_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        expect(joiner_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        return {
            'creator': creator,
            'joiner': joiner,
            'room_id': room_id,
            'creator_page': creator_page,
            'joiner_page': joiner_page,
        }

    def mark_both_ready(self, pair):
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(creator_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        joiner_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(joiner_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        expect(creator_page.get_by_text('Ready to play', exact=True)).to_be_visible(timeout=3000)
        expect(joiner_page.get_by_text('Ready to play', exact=True)).to_be_visible(timeout=3000)

    def start_control(self, page):
        return page.get_by_role('button', name='Start hand', exact=True)

    def wait_until(self, predicate, message):
        """Poll predicate until true within LIMIT_SECONDS; return elapsed seconds."""
        started = time.monotonic()
        while True:
            if predicate():
                return time.monotonic() - started
            if time.monotonic() - started > LIMIT_SECONDS:
                raise AssertionError(message)
            time.sleep(0.1)

    def shows_start(self, page):
        return self.start_control(page).is_visible()

    def click_leave(self, page):
        control = page.get_by_role('button', name='Leave room', exact=True)
        self.assertEqual(control.count(), 1, 'a full room must offer exactly one Leave room control')
        control.click(timeout=3000)

    def shows_lobby(self, page):
        return page.get_by_role('button', name='Create room').is_visible()

    def test_start_control_visible_to_both_only_when_full_and_both_ready(self):
        pair = self.full_room_pair('a', 'b')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']

        self.assertEqual(self.start_control(creator_page).count(), 0,
                         'Start hand must be hidden before anyone is Ready')
        self.assertEqual(self.start_control(joiner_page).count(), 0)

        creator_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(creator_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        self.assertEqual(self.start_control(creator_page).count(), 0,
                         'Start hand must stay hidden while only one participant is Ready')
        self.assertEqual(self.start_control(joiner_page).count(), 0)

        joiner_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(joiner_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        self.wait_until(lambda: self.shows_start(creator_page),
                        'creator browser must show Start hand within 3 seconds once both are Ready')
        self.wait_until(lambda: self.shows_start(joiner_page),
                        'joiner browser must show Start hand within 3 seconds once both are Ready')
        self.assertEqual(self._browser_errors, [])

    def test_either_participant_starts_hand_and_non_participant_gets_403(self):
        pair = self.full_room_pair('c', 'd')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']
        self.mark_both_ready(pair)
        self.wait_until(lambda: self.shows_start(joiner_page),
                        'joiner must see Start hand before the participant start check')

        visitor, _ = self.open_home()
        expect(visitor.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        visitor_request = visitor.request
        response = visitor_request.post(
            self.target + '/api/rooms/' + room_id + '/start',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({}))
        self.assertEqual(response.status, 403, 'a non-participant start must be 403')
        self.assertTrue(str(response.json().get('error', '')).strip(),
                        'the 403 refusal must carry an English message')
        before = get_room(self.target, room_id)
        self.assertEqual(before.get('state'), 'full')
        self.assertEqual(before.get('ready'), [True, True])

        self.start_control(joiner_page).click(timeout=3000)
        self.wait_until(lambda: not self.shows_start(creator_page) and not self.shows_start(joiner_page),
                        'Start hand must disappear for both participants after a successful start')
        self.assertEqual(self._browser_errors, [])

    def test_request_when_not_both_ready_is_409_and_state_unchanged(self):
        pair = self.full_room_pair('e', 'f')
        room_id = pair['room_id']
        creator_page = pair['creator_page']
        creator_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(creator_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        self.wait_until(lambda: get_room(self.target, room_id).get('ready') == [True, False],
                        'creator ready must be stored before the not-both-ready start check')

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/start',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({}))
        self.assertEqual(response.status, 409, 'a start when not both Ready must be 409')
        self.assertTrue(str(response.json().get('error', '')).strip())
        room = get_room(self.target, room_id)
        self.assertEqual(room.get('ready'), [True, False], 'a refused start must not change Ready')
        self.assertEqual(room.get('state'), 'full')
        self.assertEqual(self._browser_errors, [])

    def test_request_when_room_not_full_is_409_and_state_unchanged(self):
        creator = unique_nickname('n')
        creator_page, _ = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/start',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({}))
        self.assertEqual(response.status, 409, 'a start in a waiting (not full) room must be 409')
        self.assertTrue(str(response.json().get('error', '')).strip())
        room = get_room(self.target, room_id)
        self.assertEqual(room.get('state'), 'waiting')
        self.assertEqual(room.get('players'), [creator])
        self.assertEqual(self._browser_errors, [])

    def test_first_start_begins_hand_and_later_start_is_409_without_state_change(self):
        pair = self.full_room_pair('x', 'y')
        room_id = pair['room_id']
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        self.mark_both_ready(pair)
        self.wait_until(lambda: self.shows_start(creator_page),
                        'creator must see Start hand before the once-only check')

        self.start_control(creator_page).click(timeout=3000)
        self.wait_until(lambda: not self.shows_start(joiner_page),
                        'joiner must lose Start hand after the hand starts')
        started_room = get_room(self.target, room_id)

        response = joiner_page.request.post(
            self.target + '/api/rooms/' + room_id + '/start',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({}))
        self.assertEqual(response.status, 409, 'a second start after the hand began must be 409')
        self.assertTrue(str(response.json().get('error', '')).strip())
        after = get_room(self.target, room_id)
        self.assertEqual(after, started_room, 'a refused second start must not change room state')
        self.assertEqual(self._browser_errors, [])

    def test_unmarking_ready_hides_start_and_starts_nothing(self):
        pair = self.full_room_pair('p', 'q')
        room_id = pair['room_id']
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        self.mark_both_ready(pair)
        self.wait_until(lambda: self.shows_start(joiner_page),
                        'joiner must see Start hand before the unmark check')

        joiner_page.get_by_role('button', name='Unmark ready', exact=True).click(timeout=3000)
        self.wait_until(lambda: not self.shows_start(creator_page) and not self.shows_start(joiner_page),
                        'Start hand must hide in both browsers after Ready is unmarked')
        self.assertEqual(get_room(self.target, room_id).get('state'), 'full')
        self.assertEqual(self._browser_errors, [])

    def test_leaving_after_both_ready_hides_start_and_starts_nothing(self):
        pair = self.full_room_pair('r', 's')
        room_id = pair['room_id']
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        self.mark_both_ready(pair)
        self.wait_until(lambda: self.shows_start(creator_page),
                        'creator must see Start hand before the leave check')

        self.click_leave(joiner_page)
        self.wait_until(lambda: self.shows_lobby(joiner_page),
                        'leaver must return to the lobby')
        self.wait_until(lambda: not self.shows_start(creator_page),
                        'Start hand must hide for the remaining participant after a leave')
        room = get_room(self.target, room_id)
        self.assertEqual(room.get('state'), 'waiting', 'leaving must return the room to waiting, not start a hand')
        self.assertEqual(room.get('players'), [pair['creator']])
        self.assertEqual(self._browser_errors, [])

    def test_lobby_baseline_create_join_and_ready_still_work_before_start(self):
        pair = self.full_room_pair('m', 'o')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        self.mark_both_ready(pair)
        self.assertEqual(get_room(self.target, pair['room_id']).get('state'), 'full')
        self.assertEqual(self._browser_errors, [])
