"""Open-seat discovery and replacement join (lobby-open-seat-join, Increment 2).

Frozen UI contract (implementation must match):
- the lobby list row of a waiting room with one participant shows the English
  open-seat indicator "Open seat" (exact text) next to a "Join room" button
- a full room's lobby row shows no "Open seat" indicator and no "Join room" button
- a browser not in any room joins the open seat through the existing join form
  ("Join room", "Join nickname", "Join this room")
- both browsers show the full two-player roster within 3 seconds
  (time.monotonic() bounded expectation)
- after replacement entry both Ready states are unmarked and the English status
  "Waiting for readiness" is shown; "Ready to play" is absent
- a join after replacement is refused by the existing capacity rule
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


class OpenSeatJoin(AcceptanceTest):
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
        creator_page, errors = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)
        joiner_page, _ = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)
        expect(creator_page.get_by_role('list', name='Roster').get_by_role('listitem')).to_have_text(
            [creator, joiner], timeout=3000)
        return {
            'creator': creator,
            'joiner': joiner,
            'room_id': room_id,
            'creator_page': creator_page,
            'joiner_page': joiner_page,
            'errors': errors,
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

    def click_leave(self, page):
        control = page.get_by_role('button', name='Leave room', exact=True)
        self.assertEqual(control.count(), 1, 'a full room must offer exactly one Leave room control')
        control.click(timeout=3000)

    def shows_lobby(self, page):
        return page.get_by_role('button', name='Create room').is_visible()

    def shows_roster(self, page, players):
        roster = page.get_by_role('list', name='Roster').get_by_role('listitem')
        return roster.all_inner_texts() == players

    def lobby_row(self, page, creator):
        return page.locator('#room-list > li', has_text=creator)

    def join_open_seat(self, page, creator, replacement):
        """Discover the open seat in the lobby list and join it through the join form."""
        row = self.lobby_row(page, creator)
        expect(row.get_by_text('Open seat', exact=True)).to_be_visible(timeout=3000)
        join_button = row.get_by_role('button', name='Join room', exact=True)
        expect(join_button).to_be_visible(timeout=3000)
        join_button.click(timeout=3000)
        page.get_by_label('Join nickname', exact=True).fill(replacement)
        page.get_by_role('button', name='Join this room', exact=True).click(timeout=3000)

    def test_waiting_room_shows_open_seat_and_join_control(self):
        creator = unique_nickname('o')
        creator_page, _ = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)

        visitor, errors = self.open_home()
        row = self.lobby_row(visitor, creator)
        expect(row).to_be_visible(timeout=3000)
        expect(row.get_by_text('Open seat', exact=True)).to_be_visible(timeout=3000)
        expect(row.get_by_role('button', name='Join room', exact=True)).to_be_visible(timeout=3000)

        self.assertEqual(get_room(self.target, room_id)['players'], [creator],
                         'the open seat must leave the room with one participant')
        self.assertEqual(errors, [])

    def test_full_room_shows_no_open_seat_and_no_join_control(self):
        creator = unique_nickname('f')
        joiner = unique_nickname('g')
        creator_page, _ = self.open_home()
        self.create_room_in_browser(creator_page, creator)

        visitor, errors = self.open_home()
        row = self.lobby_row(visitor, creator)
        expect(row.get_by_text('Open seat', exact=True)).to_be_visible(timeout=3000)

        joiner_page, _ = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)

        expect(row.get_by_text('Full', exact=True)).to_be_visible(timeout=3000)
        expect(row.get_by_text('Open seat', exact=True)).to_have_count(0)
        expect(row.get_by_role('button', name='Join room', exact=True)).to_have_count(0)
        self.assertEqual(errors, [])

    def test_independent_browser_fills_open_seat_and_both_show_full_within_3_seconds(self):
        pair = self.full_room_pair('q', 'w')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator = pair['creator']
        room_id = pair['room_id']

        self.click_leave(joiner_page)
        self.wait_until(lambda: self.shows_lobby(joiner_page), 'leaver must return to the lobby')
        self.wait_until(lambda: get_room(self.target, room_id)['players'] == [creator],
                        'departure must leave the creator as the only participant')

        replacement = unique_nickname('e')
        visitor, errors = self.open_home()
        self.join_open_seat(visitor, creator, replacement)

        started = time.monotonic()
        self.wait_until(lambda: self.shows_roster(creator_page, [creator, replacement]),
                        'creator browser must show the full room within 3 seconds')
        self.wait_until(lambda: self.shows_roster(visitor, [creator, replacement]),
                        'replacement browser must show the full room within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'full')
        self.assertEqual(room['players'], [creator, replacement])
        self.assertEqual(errors, [])
        self.assertEqual(self._browser_errors, [])

    def test_replacement_entry_clears_both_ready_states_and_shows_waiting_for_readiness(self):
        pair = self.full_room_pair('r', 's')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator = pair['creator']
        room_id = pair['room_id']

        creator_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(creator_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        joiner_page.get_by_role('button', name='Mark ready', exact=True).click(timeout=3000)
        expect(joiner_page.get_by_role('button', name='Unmark ready', exact=True)).to_be_visible(timeout=3000)
        expect(creator_page.get_by_text('Ready to play', exact=True)).to_be_visible(timeout=3000)

        self.click_leave(joiner_page)
        self.wait_until(lambda: self.shows_lobby(joiner_page), 'leaver must return to the lobby')

        replacement = unique_nickname('h')
        visitor, _ = self.open_home()
        self.join_open_seat(visitor, creator, replacement)

        self.wait_until(lambda: self.shows_roster(creator_page, [creator, replacement]),
                        'creator browser must show the replacement within 3 seconds')
        self.wait_until(lambda: self.shows_roster(visitor, [creator, replacement]),
                        'replacement browser must show the full room within 3 seconds')

        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'full')
        self.assertEqual(room['ready'], [False, False], 'replacement entry must start both Ready states unmarked')

        for page in (creator_page, visitor):
            expect(page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
            expect(page.get_by_text('Ready to play', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Mark ready', exact=True)).to_be_visible(timeout=3000)
            expect(page.get_by_role('button', name='Unmark ready', exact=True)).to_have_count(0)
        self.assertEqual(self._browser_errors, [])

    def test_third_join_after_replacement_refused_full_roster_unchanged(self):
        pair = self.full_room_pair('t', 'u')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        creator = pair['creator']
        room_id = pair['room_id']

        self.click_leave(joiner_page)
        self.wait_until(lambda: self.shows_lobby(joiner_page), 'leaver must return to the lobby')
        self.wait_until(lambda: get_room(self.target, room_id)['players'] == [creator],
                        'departure must leave the creator as the only participant')

        replacement = unique_nickname('v')
        visitor, _ = self.open_home()
        self.join_open_seat(visitor, creator, replacement)
        self.wait_until(lambda: self.shows_roster(creator_page, [creator, replacement]),
                        'creator browser must show the replacement within 3 seconds')
        self.assertEqual(get_room(self.target, room_id)['state'], 'full')

        status, body = post_json(self.target, '/api/rooms/' + room_id + '/join', {'nickname': unique_nickname('i')})
        self.assertEqual(status, 409, 'a join into the room after replacement must be refused by the capacity rule')
        self.assertTrue(str(body.get('error', '')).strip(), 'the refusal must carry an English message')

        room = get_room(self.target, room_id)
        self.assertEqual(room['state'], 'full')
        self.assertEqual(room['players'], [creator, replacement], 'refused join must leave the replacement roster unchanged')
