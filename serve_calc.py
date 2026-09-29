"""Local-only calculator QA fixture tied to the deployed source SHA."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from urllib.parse import parse_qs, urlsplit

import calc


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == '/health':
            body = {'status': 'ok'}
        elif parsed.path in ('/add', '/multiply', '/clamp'):
            function = getattr(calc, parsed.path[1:], None)
            if function is None:
                self.send_error(404)
                return
            fields = ('value', 'lower', 'upper') if parsed.path == '/clamp' else ('left', 'right')
            try:
                values = [int(query[field][0]) for field in fields]
                body = {'result': function(*values)}
            except (KeyError, ValueError, IndexError, TypeError):
                self.send_error(400)
                return
        else:
            self.send_error(404)
            return
        encoded = json.dumps({**body, 'source_sha': os.environ['SOURCE_SHA']}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
