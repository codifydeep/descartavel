"""Truco Online lobby slice (S6 public, Increment 1): stdlib HTTP only.

Rooms are ephemeral and in memory. Routes: /health, /identity, /, /api/rooms.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
import time
import uuid

MAX_NICKNAME = 20

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Truco Online lobby</title>
<link rel="icon" href="data:,">
</head>
<body>
<h1>Truco Online lobby</h1>
<form id="create-form">
<label for="nickname">Nickname</label>
<input id="nickname" name="nickname" type="text" autocomplete="off">
<button type="submit">Create room</button>
</form>
<p id="form-error" role="alert" hidden></p>
<section id="my-room" hidden>
<p>Your room: <span id="my-room-status">waiting for an opponent</span></p>
<p>Creator: <span id="my-room-creator"></span></p>
</section>
<h2>Waiting rooms</h2>
<p id="empty-state" hidden>No waiting rooms right now. Create one to start.</p>
<ul id="room-list"></ul>
<script>
(function () {
  var form = document.getElementById('create-form');
  var input = document.getElementById('nickname');
  var formError = document.getElementById('form-error');
  var myRoom = document.getElementById('my-room');
  var myCreator = document.getElementById('my-room-creator');
  var list = document.getElementById('room-list');
  var empty = document.getElementById('empty-state');

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  function clearError() {
    formError.textContent = '';
    formError.hidden = true;
  }

  function renderRooms(rooms) {
    list.textContent = '';
    rooms.forEach(function (room) {
      var item = document.createElement('li');
      item.appendChild(document.createTextNode('Room by '));
      var name = document.createElement('strong');
      name.textContent = room.creator_nickname;
      item.appendChild(name);
      list.appendChild(item);
    });
    empty.hidden = rooms.length > 0;
  }

  function refresh() {
    fetch('/api/rooms', {cache: 'no-store'})
      .then(function (response) { return response.json(); })
      .then(function (body) { renderRooms(body.rooms || []); })
      .catch(function () {});
  }

  function localNicknameError(value) {
    var trimmed = value.trim();
    if (!trimmed) {
      return 'Nickname is required.';
    }
    if (trimmed.length > 20) {
      return 'Nickname must be 20 characters or fewer.';
    }
    return null;
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearError();
    var problem = localNicknameError(input.value);
    if (problem) {
      showError(problem);
      return;
    }
    fetch('/api/rooms', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nickname: input.value})
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return {ok: response.ok, body: body};
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showError(result.body.error || 'The room could not be created.');
          return;
        }
        myCreator.textContent = result.body.creator_nickname;
        myRoom.hidden = false;
        input.value = '';
        refresh();
      })
      .catch(function () {
        showError('The room could not be created. Please try again.');
      });
  });

  refresh();
  setInterval(refresh, 1000);
})();
</script>
</body>
</html>
"""


def log_event(**fields):
    print(json.dumps(fields, sort_keys=True), flush=True)


def validate_nickname(value):
    """Return (trimmed_nickname, None) or (None, English error message)."""
    if not isinstance(value, str):
        value = ''
    trimmed = value.strip()
    if not trimmed:
        return None, 'Nickname is required.'
    if len(trimmed) > MAX_NICKNAME:
        return None, 'Nickname must be 20 characters or fewer.'
    return trimmed, None


class RoomStore:
    """All rooms, guarded by one lock. Rooms are in memory only."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rooms = {}

    @staticmethod
    def _public(room):
        return {
            'id': room['id'],
            'creator_nickname': room['creator_nickname'],
            'players': list(room['players']),
            'state': room['state'],
        }

    def create(self, nickname):
        with self._lock:
            room = {
                'id': uuid.uuid4().hex,
                'creator_nickname': nickname,
                'players': [nickname],
                'state': 'waiting',
            }
            self._rooms[room['id']] = room
            log_event(event='room_created', room_id=room['id'], nickname_length=len(nickname))
            return self._public(room)

    def waiting(self):
        with self._lock:
            return [self._public(r) for r in self._rooms.values() if r['state'] == 'waiting']


STORE = RoomStore()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TrucoLobby'
    sys_version = ''

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def _dispatch(self, method):
        started = time.monotonic()
        path = self.path.split('?', 1)[0]
        if method == 'GET' and path == '/health':
            status, body = 200, {'status': 'ok'}
        elif method == 'GET' and path == '/identity':
            status, body = 200, {'source_sha': os.environ.get('FABRIQUINHA_SOURCE_SHA', '')}
        elif method == 'GET' and path == '/':
            self._send(200, PAGE.encode('utf-8'), 'text/html; charset=utf-8')
            return self._log(method, path, 200, started)
        elif method == 'GET' and path == '/api/rooms':
            status, body = 200, {'rooms': STORE.waiting()}
        elif method == 'POST' and path == '/api/rooms':
            status, body = self._create_room()
        else:
            status, body = 404, {'error': 'not found'}
        self._send_json(status, body)
        self._log(method, path, status, started)

    def _create_room(self):
        length = min(int(self.headers.get('Content-Length') or 0), 4096)
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        nickname, error = validate_nickname(payload.get('nickname'))
        if error:
            return 400, {'error': error}
        return 201, STORE.create(nickname)

    def _send_json(self, status, body):
        self._send(status, json.dumps(body).encode('utf-8'), 'application/json')

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _log(self, method, path, status, started):
        log_event(event='request', method=method, path=path, status=status,
                  duration_ms=round((time.monotonic() - started) * 1000, 2))

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', int(sys.argv[1])), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
