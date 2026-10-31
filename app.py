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
BROWSER_COOKIE = 'lobby_browser'

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
<ul id="roster" aria-label="Roster"></ul>
<button type="button" id="cancel-room" hidden>Cancel room</button>
<p id="ready-status" hidden>Waiting for readiness</p>
<button type="button" id="ready-toggle" hidden>Mark ready</button>
<button type="button" id="leave-room" hidden>Leave room</button>
<button type="button" id="start-hand" hidden>Start hand</button>
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
  var myStatus = document.getElementById('my-room-status');
  var myCreator = document.getElementById('my-room-creator');
  var roster = document.getElementById('roster');
  var list = document.getElementById('room-list');
  var empty = document.getElementById('empty-state');
  var myRoomId = null;
  var knownRooms = {};
  var fullRooms = {};
  var rowEls = {};
  var openJoins = {};
  var cancelledRooms = {};
  var submitButtons = {};
  var cancelButton = document.getElementById('cancel-room');
  var readyToggle = document.getElementById('ready-toggle');
  var leaveButton = document.getElementById('leave-room');
  var readyStatus = document.getElementById('ready-status');
  var startButton = document.getElementById('start-hand');
  var myRoomIsMine = false;
  var myReady = [];
  var myViewer = null;

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  function clearError() {
    formError.textContent = '';
    formError.hidden = true;
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

  function postNickname(url, nickname) {
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nickname: nickname})
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    });
  }

  function renderRoster(players, ready) {
    roster.textContent = '';
    players.forEach(function (name, index) {
      var item = document.createElement('li');
      item.textContent = name;
      item.setAttribute('data-ready', ready[index] ? 'true' : 'false');
      roster.appendChild(item);
    });
  }

  function showRoom(room) {
    myRoomId = room.id;
    myRoom.hidden = false;
    myCreator.textContent = room.creator_nickname;
    myReady = room.ready || [];
    myViewer = typeof room.viewer === 'number' ? room.viewer : null;
    renderRoster(room.players, myReady);
    if (room.state === 'cancelled') {
      myStatus.textContent = 'cancelled';
    } else {
      myStatus.textContent = room.players.length >= 2 ? 'full' : 'waiting for an opponent';
    }
    cancelButton.hidden = !(myViewer === 0 && room.state === 'waiting' && room.players.length < 2);
    var full = room.state === 'full' && room.players.length >= 2;
    leaveButton.hidden = !(full && myViewer !== null);
    readyToggle.hidden = !(full && myViewer !== null);
    startButton.hidden = !(full && myViewer !== null && myReady[0] && myReady[1]);
    if (myViewer !== null) {
      readyToggle.textContent = myReady[myViewer] ? 'Unmark ready' : 'Mark ready';
    }
    if (full) {
      readyStatus.textContent = (myReady[0] && myReady[1]) ? 'Ready to play' : 'Waiting for readiness';
    } else {
      readyStatus.textContent = '';
    }
    readyStatus.hidden = !full;
  }

  function toggleReady() {
    clearError();
    if (myViewer === null || !myRoomId) {
      return;
    }
    var next = !myReady[myViewer];
    fetch('/api/rooms/' + myRoomId + '/ready', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ready: next})
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        showError(result.body.error || 'Ready could not be changed.');
        return;
      }
      showRoom(result.body);
    }).catch(function () {
      showError('Ready could not be changed. Please try again.');
    });
  }

  readyToggle.addEventListener('click', toggleReady);

  function startHand() {
    clearError();
    if (!myRoomId) {
      return;
    }
    fetch('/api/rooms/' + myRoomId + '/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}'
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        showError(result.body.error || 'The hand could not be started.');
        refreshRoom();
        return;
      }
      showRoom(result.body);
    }).catch(function () {
      showError('The hand could not be started. Please try again.');
    });
  }

  startButton.addEventListener('click', startHand);

  function cancelMyRoom() {
    clearError();
    fetch('/api/rooms/' + myRoomId + '/cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}'
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        showError(result.body.error || 'The room could not be cancelled.');
        return;
      }
      showRoom(result.body);
      refresh();
    }).catch(function () {
      showError('The room could not be cancelled. Please try again.');
    });
  }

  cancelButton.addEventListener('click', cancelMyRoom);

  function leaveMyRoom() {
    clearError();
    if (!myRoomId) {
      return;
    }
    myRoom.hidden = true;
    fetch('/api/rooms/' + myRoomId + '/leave', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}'
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        myRoom.hidden = false;
        showError(result.body.error || 'The room could not be left.');
        refreshRoom();
        return;
      }
      myRoomId = null;
      myRoomIsMine = false;
      myViewer = null;
      myReady = [];
      myRoom.hidden = true;
      refresh();
    }).catch(function () {
      myRoom.hidden = false;
      showError('The room could not be left. Please try again.');
      refreshRoom();
    });
  }

  leaveButton.addEventListener('click', leaveMyRoom);

  function refreshRoom() {
    if (!myRoomId) {
      return;
    }
    fetch('/api/rooms/' + myRoomId, {cache: 'no-store'})
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (room) { if (room) { showRoom(room); } })
      .catch(function () {});
  }

  function joinRoom(id, value) {
    clearError();
    if (cancelledRooms[id]) {
      showError('This room was cancelled.');
      return;
    }
    var problem = localNicknameError(value);
    if (problem) {
      showError(problem);
      return;
    }
    fetch('/api/rooms/' + id, {cache: 'no-store'})
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (room) {
        if (room && room.state === 'cancelled') {
          showError('This room was cancelled.');
          return null;
        }
        if (room && (room.state !== 'waiting' || room.players.length >= 2)) {
          showError('This room is full.');
          return null;
        }
        return postNickname('/api/rooms/' + id + '/join', value);
      })
      .then(function (result) {
        if (!result) {
          return;
        }
        if (!result.ok) {
          showError(result.body.error || 'The room could not be joined.');
          return;
        }
        delete openJoins[id];
        delete rowEls[id];
        myRoomIsMine = false;
        showRoom(result.body);
        refresh();
      })
      .catch(function () {
        showError('The room could not be joined. Please try again.');
      });
  }

  function buildRow(room, full) {
    var item = document.createElement('li');
    item.appendChild(document.createTextNode('Room by '));
    var name = document.createElement('strong');
    name.textContent = room.creator_nickname;
    item.appendChild(name);
    if (full) {
      var label = document.createElement('span');
      label.textContent = 'Full';
      item.appendChild(label);
      return item;
    }
    if (room.players.length === 1) {
      var seat = document.createElement('span');
      seat.textContent = 'Open seat';
      item.appendChild(seat);
    }
    if (room.id === myRoomId) {
      return item;
    }
    var joinButton = document.createElement('button');
    joinButton.type = 'button';
    joinButton.textContent = 'Join room';
    joinButton.addEventListener('click', function () {
      openJoins[room.id] = true;
      joinButton.hidden = true;
      var wrap = document.createElement('div');
      var label = document.createElement('label');
      var field = document.createElement('input');
      var submit = document.createElement('button');
      field.id = 'join-' + room.id;
      field.type = 'text';
      field.autocomplete = 'off';
      label.htmlFor = field.id;
      label.textContent = 'Join nickname';
      submit.type = 'button';
      submit.textContent = 'Join this room';
      submitButtons[room.id] = submit;
      if (cancelledRooms[room.id]) {
        submit.disabled = true;
      }
      submit.addEventListener('click', function () {
        joinRoom(room.id, field.value);
      });
      wrap.appendChild(label);
      wrap.appendChild(field);
      wrap.appendChild(submit);
      item.appendChild(wrap);
      field.focus();
    });
    item.appendChild(joinButton);
    return item;
  }

  function rowFor(room, full) {
    if (openJoins[room.id] && rowEls[room.id]) {
      var cached = rowEls[room.id];
      if (full && !cached.querySelector('.full-label')) {
        var fullLabel = document.createElement('span');
        fullLabel.className = 'full-label';
        fullLabel.textContent = 'Full';
        cached.appendChild(fullLabel);
      }
      return cached;
    }
    var item = buildRow(room, full);
    rowEls[room.id] = item;
    return item;
  }

  function renderRooms(waiting) {
    var children = waiting.map(function (room) { return rowFor(room, false); });
    Object.keys(fullRooms).forEach(function (id) {
      children.push(rowFor(fullRooms[id], true));
    });
    list.textContent = '';
    children.forEach(function (child) { list.appendChild(child); });
    empty.hidden = children.length > 0;
  }

  function resolveMissing(ids) {
    return Promise.all(ids.map(function (id) {
      return fetch('/api/rooms/' + id, {cache: 'no-store'})
        .then(function (response) { return response.ok ? response.json() : null; })
        .catch(function () { return null; })
        .then(function (room) {
          if (room && room.state === 'cancelled') {
            cancelledRooms[id] = true;
            if (submitButtons[id]) {
              submitButtons[id].disabled = true;
            }
          }
          if (room && room.players.length >= 2) {
            fullRooms[id] = room;
          } else {
            delete knownRooms[id];
            delete fullRooms[id];
            delete rowEls[id];
          }
        });
    }));
  }

  function refresh() {
    fetch('/api/rooms', {cache: 'no-store'})
      .then(function (response) { return response.json(); })
      .then(function (body) {
        var waiting = body.rooms || [];
        var present = {};
        waiting.forEach(function (room) {
          present[room.id] = true;
          knownRooms[room.id] = room;
          delete fullRooms[room.id];
        });
        var missing = Object.keys(knownRooms).filter(function (id) { return !present[id]; });
        return resolveMissing(missing).then(function () {
          renderRooms(waiting);
        });
      })
      .catch(function () {});
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearError();
    var problem = localNicknameError(input.value);
    if (problem) {
      showError(problem);
      return;
    }
    postNickname('/api/rooms', input.value)
      .then(function (result) {
        if (!result.ok) {
          showError(result.body.error || 'The room could not be created.');
          return;
        }
        myRoomIsMine = true;
        showRoom(result.body);
        input.value = '';
        refresh();
      })
      .catch(function () {
        showError('The room could not be created. Please try again.');
      });
  });

  refresh();
  setInterval(refresh, 1000);
  setInterval(refreshRoom, 1000);
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

    @staticmethod
    def _view(room, token):
        """Room view for one caller: adds per-slot ready flags and the caller's slot."""
        view = RoomStore._public(room)
        view['ready'] = list(room['ready'][:len(room['players'])])
        view['viewer'] = RoomStore._slot(room, token)
        return view

    @staticmethod
    def _slot(room, token):
        if not token:
            return None
        if token == room['creator_token']:
            return 0
        if room['joiner_token'] is not None and token == room['joiner_token']:
            return 1
        return None

    def create(self, nickname, creator_token):
        with self._lock:
            room = {
                'id': uuid.uuid4().hex,
                'creator_nickname': nickname,
                'creator_token': creator_token,
                'joiner_token': None,
                'players': [nickname],
                'ready': [False, False],
                'state': 'waiting',
            }
            self._rooms[room['id']] = room
            log_event(event='room_created', room_id=room['id'], nickname_length=len(nickname))
            return self._view(room, creator_token)

    def waiting(self):
        with self._lock:
            return [self._public(r) for r in self._rooms.values() if r['state'] == 'waiting']

    def get(self, room_id, token=None):
        with self._lock:
            room = self._rooms.get(room_id)
            return self._view(room, token) if room else None

    def cancel(self, room_id, creator_token):
        """Return (public_room, None) on success or (None, (status, message))."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, (404, 'Room not found.')
            if not creator_token or creator_token != room['creator_token']:
                return None, (403, 'Only the room creator can cancel this room.')
            if room['state'] != 'waiting' or len(room['players']) >= 2:
                return None, (409, 'This room can no longer be cancelled.')
            room['state'] = 'cancelled'
            log_event(event='room_cancelled', room_id=room_id)
            return self._public(room), None

    def join(self, room_id, nickname, joiner_token):
        """Return (public_room, None) on success or (None, (status, message)).

        Callers must pass a non-empty joiner_token; it is recorded as the joiner slot.
        """
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, (404, 'Room not found.')
            if room['state'] == 'cancelled':
                return None, (409, 'This room was cancelled.')
            if room['state'] != 'waiting' or len(room['players']) >= 2:
                return None, (409, 'This room is full.')
            room['players'].append(nickname)
            room['joiner_token'] = joiner_token
            room['state'] = 'full'
            log_event(event='room_joined', room_id=room_id, nickname_length=len(nickname))
            log_event(event='room_full', room_id=room_id)
            return self._view(room, joiner_token), None

    def leave(self, room_id, token):
        """Remove the caller from a full room. Return (public_room, None) or (None, (status, message)).

        Joiner leaves: creator stays owner. Creator leaves: remaining participant becomes owner.
        Either way the room becomes waiting and both Ready states are cleared.
        """
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None or room['state'] == 'cancelled':
                return None, (404, 'Room not found.')
            slot = self._slot(room, token)
            if slot is None:
                return None, (403, 'Only a participant of this room can leave it.')
            if room['state'] != 'full' or len(room['players']) < 2:
                return None, (409, 'Leave is available only when the room is full.')
            if slot == 0:
                room['creator_token'] = room['joiner_token']
                room['creator_nickname'] = room['players'][1]
                room['players'] = [room['players'][1]]
            else:
                room['players'] = [room['players'][0]]
            room['joiner_token'] = None
            room['ready'] = [False, False]
            room['state'] = 'waiting'
            log_event(event='room_left', room_id=room_id)
            return self._public(room), None

    def start(self, room_id, token):
        """Begin the room's one hand. Return (view, None) or (None, (status, message)).

        The check and the transition happen under the room lock, so the first
        successful start wins and every later start is refused with no state change.
        """
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, (404, 'Room not found.')
            slot = self._slot(room, token)
            if slot is None:
                return None, (403, 'Only a participant of this room can start the hand.')
            if room['state'] in ('playing', 'finished'):
                return None, (409, 'The hand has already started in this room.')
            if room['state'] != 'full' or len(room['players']) < 2:
                return None, (409, 'The hand can start only when the room is full.')
            if not (room['ready'][0] and room['ready'][1]):
                return None, (409, 'The hand can start only when both participants are Ready.')
            room['state'] = 'playing'
            log_event(event='hand_started', room_id=room_id)
            return self._view(room, token), None

    def set_ready(self, room_id, token, ready):
        """Set the caller's own ready flag. Return (view, None) or (None, (status, message))."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None, (404, 'Room not found.')
            slot = self._slot(room, token)
            if slot is None:
                return None, (403, 'Only a participant of this room can mark ready.')
            if room['state'] != 'full' or len(room['players']) < 2:
                return None, (409, 'Ready is available only when the room is full.')
            room['ready'][slot] = ready
            log_event(event='room_ready_changed', room_id=room_id)
            return self._view(room, token), None


STORE = RoomStore()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TrucoLobby'
    sys_version = ''
    _set_cookie = None

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
        elif method == 'GET' and path.startswith('/api/rooms/'):
            room = STORE.get(path[len('/api/rooms/'):], self._browser_token())
            status, body = (200, room) if room else (404, {'error': 'not found'})
        elif method == 'POST' and path.startswith('/api/rooms/') and path.endswith('/cancel'):
            room, failure = STORE.cancel(path[len('/api/rooms/'):-len('/cancel')], self._browser_token())
            status, body = (200, room) if room else (failure[0], {'error': failure[1]})
        elif method == 'POST' and path.startswith('/api/rooms/') and path.endswith('/join'):
            status, body = self._join_room(path[len('/api/rooms/'):-len('/join')])
        elif method == 'POST' and path.startswith('/api/rooms/') and path.endswith('/leave'):
            room, failure = STORE.leave(path[len('/api/rooms/'):-len('/leave')], self._browser_token())
            status, body = (200, room) if room else (failure[0], {'error': failure[1]})
        elif method == 'POST' and path.startswith('/api/rooms/') and path.endswith('/ready'):
            status, body = self._set_ready(path[len('/api/rooms/'):-len('/ready')])
        elif method == 'POST' and path.startswith('/api/rooms/') and path.endswith('/start'):
            room, failure = STORE.start(path[len('/api/rooms/'):-len('/start')], self._browser_token())
            status, body = (200, room) if room else (failure[0], {'error': failure[1]})
        else:
            status, body = 404, {'error': 'not found'}
        self._send_json(status, body)
        self._log(method, path, status, started)

    def _browser_token(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            name, _, value = part.strip().partition('=')
            if name == BROWSER_COOKIE and value:
                return value
        return None

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
        token = self._browser_token()
        if not token:
            token = uuid.uuid4().hex
            self._set_cookie = '%s=%s; Path=/; HttpOnly; SameSite=Lax' % (BROWSER_COOKIE, token)
        return 201, STORE.create(nickname, token)

    def _join_room(self, room_id):
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
        token = self._browser_token()
        if not token:
            token = uuid.uuid4().hex
            self._set_cookie = '%s=%s; Path=/; HttpOnly; SameSite=Lax' % (BROWSER_COOKIE, token)
        room, failure = STORE.join(room_id, nickname, token)
        if failure:
            return failure[0], {'error': failure[1]}
        return 200, room

    def _set_ready(self, room_id):
        length = min(int(self.headers.get('Content-Length') or 0), 4096)
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict) or not isinstance(payload.get('ready'), bool):
            return 400, {'error': 'Ready must be true or false.'}
        room, failure = STORE.set_ready(room_id, self._browser_token(), payload['ready'])
        if failure:
            return failure[0], {'error': failure[1]}
        return 200, room

    def _send_json(self, status, body):
        self._send(status, json.dumps(body).encode('utf-8'), 'application/json')

    def _send(self, status, data, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        if self._set_cookie:
            self.send_header('Set-Cookie', self._set_cookie)
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
