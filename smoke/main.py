"""M0 throwaway: fetch today's NBA CDN scoreboard from Cloud Run and report what happened."""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with urllib.request.urlopen(URL, timeout=10) as r:
                body = json.load(r)
            out = {"status": r.status, "gameDate": body["scoreboard"]["gameDate"],
                   "games": len(body["scoreboard"]["games"])}
        except urllib.error.HTTPError as e:
            out = {"status": e.code, "error": str(e)}
        except Exception as e:  # report, don't crash: this is a probe
            out = {"status": None, "error": repr(e)}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


HTTPServer(("", int(os.environ.get("PORT", 8080))), H).serve_forever()
