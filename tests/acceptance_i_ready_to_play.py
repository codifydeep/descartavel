"""Ready to play (ready-to-play increment, Increment 2).

Frozen UI contract (implementation must match):
- the room status line (id "ready-status") shows "Waiting for readiness" while
  the room is full and not both participants are ready
- when both participants are ready, the same status line shows "Ready to play"
  in both participants' browsers, and "Waiting for readiness" is absent
- when either participant unmarks ready, both browsers show "Waiting for
  readiness" and "Ready to play" is absent
- status is derived from the existing per-slot ready flags; no new endpoint
  or server state, no timers, no auto-start
- every propagation bound is 3 seconds, asserted with time.monotonic()
"""
import json
import time
import uuid
from urllib.request import urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


LIMIT_SECONDS = 3.0


def unique_nickname(prefix):
    return prefix + uuid.uuid4().hex[:8]


def get_room(target, room_id):
    with urlopen(target + '/api/rooms/' + room_id, timeout=3) as response:
        return json.load(response)


def ready_flags(target, room_id):
    return get_room(target, room_id).get('ready')


def room_id_for(target, creator):
    with urlopen(target + '/api/rooms', timeout=3) as response:
        rooms = json.load(response)['rooms']
    matches = [room['id'] for room in rooms if room.get('creator_nickname') == creator]
    if len(matches) != 1:
        raise AssertionError('expected exactly one waiting room for creator, got %d' % len(matches))
    return matches[0]


class ReadyToPlay(AcceptanceTest):
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
        creator = unique_nickname(prefix_creator)
        joiner = unique_nickname(prefix_joiner)
        creator_page, creator_errors = self.open_home()
        self.create_room_in_browser(creator_page, creator)
        room_id = room_id_for(self.target, creator)
        joiner_page, joiner_errors = self.open_home()
        self.join_room_in_browser(joiner_page, creator, joiner)
        expect(creator_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        expect(joiner_page.get_by_text('Waiting for readiness', exact=True)).to_be_visible(timeout=3000)
        return {
            'creator': creator,
            'joiner': joiner,
            'room_id': room_id,
            'creator_page': creator_page,
            'joiner_page': joiner_page,
            'errors': creator_errors + joiner_errors,
        }

    def ready_button(self, page, label):
        return page.get_by_role('button', name=label, exact=True)

    def wait_until(self, predicate, message):
        """Poll predicate until true within LIMIT_SECONDS; return elapsed seconds."""
        started = time.monotonic()
        while True:
            if predicate():
                return time.monotonic() - started
            if time.monotonic() - started > LIMIT_SECONDS:
                raise AssertionError(message)
            time.sleep(0.1)

    def shows_ready_to_play(self, page):
        return page.get_by_text('Ready to play', exact=True).is_visible()

    def shows_waiting(self, page):
        return page.get_by_text('Waiting for readiness', exact=True).is_visible()

    def test_both_ready_shows_ready_to_play_in_both_browsers_within_3_seconds(self):
        pair = self.full_room_pair('r', 'p')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']

        self.ready_button(creator_page, 'Mark ready').click()
        expect(self.ready_button(creator_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: ready_flags(self.target, pair['room_id']) == [True, False],
                        'creator ready must be stored before the joiner marks ready')
        expect(creator_page.get_by_text('Ready to play', exact=True)).to_have_count(0)
        expect(joiner_page.get_by_text('Ready to play', exact=True)).to_have_count(0)

        self.ready_button(joiner_page, 'Mark ready').click()
        started = time.monotonic()
        self.wait_until(lambda: self.shows_ready_to_play(creator_page),
                        'creator browser must show Ready to play within 3 seconds')
        self.wait_until(lambda: self.shows_ready_to_play(joiner_page),
                        'joiner browser must show Ready to play within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        self.assertEqual(ready_flags(self.target, pair['room_id']), [True, True])
        self.assertEqual(creator_page.get_by_text('Waiting for readiness', exact=True).count(), 0,
                         'Waiting for readiness must be absent once both are ready')
        self.assertEqual(joiner_page.get_by_text('Waiting for readiness', exact=True).count(), 0,
                         'Waiting for readiness must be absent once both are ready')
        self.assertEqual(pair['errors'], [])

    def test_unmark_reverts_to_waiting_in_both_browsers_within_3_seconds(self):
        pair = self.full_room_pair('u', 'v')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']

        self.ready_button(creator_page, 'Mark ready').click()
        expect(self.ready_button(creator_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.ready_button(joiner_page, 'Mark ready').click()
        expect(self.ready_button(joiner_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: self.shows_ready_to_play(creator_page),
                        'creator browser must show Ready to play before the revert check')
        self.wait_until(lambda: self.shows_ready_to_play(joiner_page),
                        'joiner browser must show Ready to play before the revert check')

        self.ready_button(joiner_page, 'Unmark ready').click()
        started = time.monotonic()
        self.wait_until(lambda: self.shows_waiting(creator_page) and not self.shows_ready_to_play(creator_page),
                        'creator browser must revert to Waiting for readiness within 3 seconds')
        self.wait_until(lambda: self.shows_waiting(joiner_page) and not self.shows_ready_to_play(joiner_page),
                        'joiner browser must revert to Waiting for readiness within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        self.assertEqual(ready_flags(self.target, pair['room_id']), [True, False])
        self.assertEqual(creator_page.get_by_text('Ready to play', exact=True).count(), 0)
        self.assertEqual(joiner_page.get_by_text('Ready to play', exact=True).count(), 0)
        self.assertEqual(pair['errors'], [])

    def test_creator_unmark_reverts_to_waiting_in_both_browsers_within_3_seconds(self):
        pair = self.full_room_pair('c', 'd')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']

        self.ready_button(creator_page, 'Mark ready').click()
        expect(self.ready_button(creator_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.ready_button(joiner_page, 'Mark ready').click()
        expect(self.ready_button(joiner_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: self.shows_ready_to_play(creator_page),
                        'creator browser must show Ready to play before the revert check')
        self.wait_until(lambda: self.shows_ready_to_play(joiner_page),
                        'joiner browser must show Ready to play before the revert check')

        self.ready_button(creator_page, 'Unmark ready').click()
        started = time.monotonic()
        self.wait_until(lambda: self.shows_waiting(creator_page) and not self.shows_ready_to_play(creator_page),
                        'creator browser must revert to Waiting for readiness within 3 seconds')
        self.wait_until(lambda: self.shows_waiting(joiner_page) and not self.shows_ready_to_play(joiner_page),
                        'joiner browser must revert to Waiting for readiness within 3 seconds')
        self.assertLessEqual(time.monotonic() - started, LIMIT_SECONDS)

        self.assertEqual(ready_flags(self.target, pair['room_id']), [False, True])
        self.assertEqual(pair['errors'], [])

    def test_full_ready_room_keeps_two_player_roster_and_stays_unjoinable(self):
        pair = self.full_room_pair('k', 'l')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']

        self.ready_button(creator_page, 'Mark ready').click()
        expect(self.ready_button(creator_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.ready_button(joiner_page, 'Mark ready').click()
        expect(self.ready_button(joiner_page, 'Unmark ready')).to_be_visible(timeout=3000)
        self.wait_until(lambda: self.shows_ready_to_play(creator_page),
                        'creator browser must show Ready to play before the regression check')

        visitor, visitor_errors = self.open_home()
        expect(visitor.get_by_label('Nickname', exact=True)).to_be_visible(timeout=3000)
        self.assertEqual(visitor.locator('li', has_text=pair['creator']).get_by_role(
            'button', name='Join room', exact=True).count(), 0,
            'a full ready room must not be joinable by a visitor')
        for page in (creator_page, joiner_page):
            self.assertEqual(
                page.get_by_role('list', name='Roster').get_by_role('listitem').all_inner_texts(),
                [pair['creator'], pair['joiner']],
                'the roster must stay exactly the two participants with ready state set')
        self.assertEqual(ready_flags(self.target, room_id), [True, True])
        self.assertEqual(visitor_errors, [])
        self.assertEqual(pair['errors'], [])

    def test_single_ready_participant_never_shows_ready_to_play(self):
        pair = self.full_room_pair('g', 'h')
        creator_page = pair['creator_page']
        joiner_page = pair['joiner_page']
        room_id = pair['room_id']

        response = creator_page.request.post(
            self.target + '/api/rooms/' + room_id + '/ready',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({'ready': True}))
        self.assertEqual(response.status, 200, 'the creator, a participant, may mark ready in a full room')
        self.assertEqual(response.json().get('ready'), [True, False])
        self.wait_until(lambda: ready_flags(self.target, room_id) == [True, False],
                        'creator ready must be stored before the single-ready check')
        self.wait_until(lambda: self.shows_waiting(joiner_page) and not self.shows_ready_to_play(joiner_page),
                        'joiner browser must keep Waiting for readiness with one participant ready')
        self.assertFalse(self.shows_ready_to_play(creator_page),
                         'creator browser must not show Ready to play with only one participant ready')
        self.assertEqual(pair['errors'], [])
