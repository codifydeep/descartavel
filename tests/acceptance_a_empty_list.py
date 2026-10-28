"""EMPTY_LIST: explicit English empty state.

Named to sort before every room-creating acceptance file so that unittest
discovery observes the server before any room exists.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fabriquinha_acceptance import AcceptanceTest
from playwright.sync_api import expect


def fetch_rooms(target):
    try:
        with urlopen(target + '/api/rooms', timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None
    except URLError:
        return None, None


class EmptyList(AcceptanceTest):
    def test_home_shows_empty_state_when_no_waiting_rooms(self):
        status, payload = fetch_rooms(self.target)
        self.assertEqual(status, 200, 'GET /api/rooms must return 200')
        rooms = payload.get('rooms') if isinstance(payload, dict) else payload
        self.assertEqual(rooms, [], 'EMPTY_LIST must observe a fresh app with no rooms')

        context = self.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(self.target + '/', wait_until='domcontentloaded')
        expect(page.get_by_text(re.compile(r'no waiting rooms', re.IGNORECASE))).to_be_visible(timeout=3000)
        self.assertEqual(errors, [])
