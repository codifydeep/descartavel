"""CREATE_ROOM and LIST_WAITING across two independent browser contexts."""
import re
import time
import uuid

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def unique_nickname():
    return 'c' + uuid.uuid4().hex[:8]


class CreateAndList(AcceptanceTest):
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

    def test_create_shows_waiting_for_opponent_with_creator_nickname(self):
        nickname = unique_nickname()
        page, errors = self.open_home()
        page.get_by_label('Nickname').fill(nickname)
        page.get_by_role('button', name='Create room').click()
        expect(page.get_by_text(re.compile(r'waiting for an opponent', re.IGNORECASE))).to_be_visible(timeout=3000)
        expect(page.get_by_text(nickname, exact=False).first).to_be_visible(timeout=3000)
        self.assertEqual(errors, [])

    def test_second_context_sees_waiting_room_within_3_seconds_without_reload(self):
        observer_page, observer_errors = self.open_home()
        creator_nickname = unique_nickname()
        creator_page, creator_errors = self.open_home()
        creator_page.get_by_label('Nickname').fill(creator_nickname)
        creator_page.get_by_role('button', name='Create room').click()
        expect(creator_page.get_by_text(re.compile(r'waiting for an opponent', re.IGNORECASE))).to_be_visible(timeout=3000)

        started = time.monotonic()
        room = observer_page.get_by_text(creator_nickname, exact=False).first
        visible = False
        while time.monotonic() - started < 3.0:
            if room.count() > 0 and room.is_visible():
                visible = True
                break
            time.sleep(0.1)
        elapsed = time.monotonic() - started
        self.assertTrue(visible, 'room with creator nickname not visible in other context within 3s')
        self.assertLessEqual(elapsed, 3.0)
        self.assertEqual(observer_errors, [])
        self.assertEqual(creator_errors, [])
