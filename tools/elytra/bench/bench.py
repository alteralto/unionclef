"""Shared parts of the elytra bench: configuration, an MCP client for the mod, RCON to the test server,
the arena, and the helpers every test uses (reset a player, fly, watch a status).

Configuration comes from the environment, or from local.json next to this file (git-ignored):

    MC_SETTINGS     the clients' altoclef_settings.json (for the MCP token);
                    default <%APPDATA% or ~>/.minecraft/altoclef/altoclef_settings.json
    BENCH_CLIENTS   nick=mcp-url pairs, comma separated; the first one is the bot under test
                    default arcmlchikkk=http://127.0.0.1:25350/mcp, pyhtun_lead=...:25351, pyhtun_wing=...:25352
    RCON_HOST, RCON_PORT, RCON_PASSWORD   the test server (default 127.0.0.1:25575; the password may
                    also sit in rcon.secret next to this file)
    FFMPEG          ffmpeg for compile.py (default: ffmpeg on PATH)

Nothing here prints the MCP token or the RCON password.
"""
import json
import os
import shutil
import pathlib
import socket
import struct
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
_local = json.loads((HERE / "local.json").read_text(encoding="utf-8")) if (HERE / "local.json").exists() else {}


def conf(key, default=""):
    return os.environ.get(key) or _local.get(key) or default


_home = os.environ.get("APPDATA") or os.path.expanduser("~")
MC_SETTINGS = conf("MC_SETTINGS", os.path.join(_home, ".minecraft", "altoclef", "altoclef_settings.json"))
FFMPEG = conf("FFMPEG", "ffmpeg")
CLIENTS = dict(pair.split("=", 1) for pair in conf(
    "BENCH_CLIENTS",
    "arcmlchikkk=http://127.0.0.1:25350/mcp,pyhtun_lead=http://127.0.0.1:25351/mcp,"
    "pyhtun_wing=http://127.0.0.1:25352/mcp").split(","))
NICKS = list(CLIENTS)
BOT = NICKS[0]
G = -61          # the flat world's grass; feet stand at G + 1
F = G + 1


# ---- MCP (the mod's server: JSON-RPC tools/call over HTTP, bearer token) ----

_token = None


def _bearer():
    global _token
    if _token is None:
        _token = json.loads(pathlib.Path(MC_SETTINGS).read_text(encoding="utf-8")).get("mcpAuthToken", "")
    return _token


def mcp(tool, args=None, nick=None, timeout=90):
    """Call a mod tool on a client (the bot by default); the tool's JSON answer, or {"error": ...}."""
    url = CLIENTS[nick or BOT]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args or {}}}).encode("utf-8")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                             "Authorization": "Bearer " + _bearer()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode("utf-8")).get("result") or {}
        text = (res.get("content") or [{}])[0].get("text", "")
        return json.loads(text) if text.startswith(("{", "[")) else {"text": text}
    except Exception as e:  # a test reads a failed call as a failed step, not a crash
        return {"error": repr(e)[:200]}


def me(nick=None):
    return mcp("getGameState", nick=nick).get("self", {})


def pos(nick=None):
    s = me(nick)
    return [float(v) for v in s["pos"].split(",")] if s.get("pos") else None


# ---- RCON ----

class Rcon:
    def __init__(self):
        pw = conf("RCON_PASSWORD") or (HERE / "rcon.secret").read_text(encoding="utf-8").strip()
        self.s = socket.create_connection((conf("RCON_HOST", "127.0.0.1"), int(conf("RCON_PORT", "25575"))), timeout=40)
        self.id = 0
        if self._req(3, pw)[0] == -1:
            raise SystemExit("rcon: wrong password")

    def _req(self, kind, body):
        self.id += 1
        data = struct.pack("<ii", self.id, kind) + body.encode("utf-8") + b"\x00\x00"
        self.s.sendall(struct.pack("<i", len(data)) + data)
        size = struct.unpack("<i", self._read(4))[0]
        rid, _ = struct.unpack("<ii", self._read(8))
        return rid, self._read(size - 8)[:-2].decode("utf-8", "replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("rcon closed")
            buf += chunk
        return buf

    def cmd(self, command):
        return self._req(2, command)[1]


_rc = None


def cmd(*commands):
    global _rc
    if _rc is None:
        _rc = Rcon()
    return [_rc.cmd(c) for c in commands]


# ---- the arena ----

RINGS = [(80, F + 18, 130), (140, F + 24, 136), (200, F + 16, 124), (260, F + 26, 132), (320, F + 20, 128),
         (380, F + 14, 130)]


def arena():
    cmd("forceload add -160 -160 560 160", "forceload add 560 -32 1100 32",
        "gamerule send_command_feedback false", "time set 6000", "weather clear")
    # a gazebo: plank roof four blocks up on fence posts
    cmd(f"fill -43 {F+3} -3 -37 {F+3} 3 minecraft:oak_planks",
        *[f"fill {x} {F} {z} {x} {F+2} {z} minecraft:oak_fence" for x in (-43, -37) for z in (-3, 3)])
    # a leaf canopy five blocks up over a trunk
    cmd(f"fill -5 {F+4} 55 5 {F+5} 65 minecraft:oak_leaves[persistent=true]",
        f"fill 0 {F} 60 0 {F+4} 60 minecraft:oak_log")
    # a strip of tall trees on the line of a low-level flight
    for x in range(30, 211, 15):
        cmd(f"fill {x} {F} -82 {x} {F+9} -82 minecraft:oak_log",
            f"fill {x-2} {F+7} -84 {x+2} {F+10} -80 minecraft:oak_leaves[persistent=true] keep")
    # a water tank 16 deep, open on top; its walls rise a block over the water (no way out there),
    # a ledge level with the water along the east wall is the one bank. ("hollow" alone builds a lid.)
    cmd(f"fill 58 {F} -62 82 {F+16} -38 minecraft:stone_bricks hollow",
        f"fill 59 {F} -61 81 {F+15} -39 minecraft:water",
        f"fill 59 {F+16} -61 81 {F+16} -39 minecraft:air",
        f"fill 81 {F+15} -61 81 {F+15} -39 minecraft:stone_bricks")
    # rings: square frames with a 7x7 opening across a lane at z ~130
    for x, y, z in RINGS:
        cmd(f"fill {x} {y-4} {z-4} {x} {y+4} {z+4} minecraft:yellow_concrete",
            f"fill {x} {y-3} {z-3} {x} {y+3} {z+3} minecraft:air")


def reset(x, z, rockets_in_hotbar=True, y=None, yaw=0, nick=None):
    """A clean start: creative, an elytra, 64 rockets (in the backpack if asked), at x, z."""
    nick = nick or BOT
    cmd(f"gamemode creative {nick}", f"clear {nick}", f"effect clear {nick}")
    if not rockets_in_hotbar:  # fill the hotbar so the rockets land in the backpack
        cmd(*[f"item replace entity {nick} hotbar.{i} with minecraft:cobblestone" for i in range(9)])
    cmd(f"give {nick} minecraft:elytra", f"give {nick} minecraft:firework_rocket 64",
        f"tp {nick} {x} {F if y is None else y} {z} {yaw} 0")
    mcp("ExecuteCommand", {"cmd": "@stop"}, nick=nick)
    mcp("flyStop", nick=nick)
    time.sleep(2)


def watch(status_tool, seconds, nick=None):
    """Poll a status tool until it leaves its running phases; the last status and the path flown."""
    t0, path, st = time.time(), [], {}
    while time.time() - t0 < seconds:
        st = mcp(status_tool, nick=nick)
        p = pos(nick)
        if p:
            path.append([round(v, 1) for v in p])
        if st.get("phase") in ("done", "failed", "idle", "stopped"):
            break
        time.sleep(0.4)
    st["seconds"] = round(time.time() - t0, 1)
    return st, path


class Video:
    """Recorded by the mod (recordStart): the game window only, 1920x1080, 20 fps. Needs the path of
    ffmpeg in <game>/altoclef/recorder_ffmpeg.txt; without it the test simply runs unfilmed."""

    def __init__(self, name, on=True, nick=None):
        self.nick, self.on = nick or BOT, on
        if not on:
            return
        self.stamp = f"{time.strftime('%m%d-%H%M%S')}-{name}"
        self.on = bool(mcp("recordStart", {"name": self.stamp, "fps": 20}, nick=self.nick).get("ok"))

    def stop(self):
        if not self.on:
            return None
        time.sleep(1.5)
        done = mcp("recordStop", nick=self.nick)
        if not done.get("file") or not os.path.exists(done["file"]):
            return None
        (OUT / "video").mkdir(parents=True, exist_ok=True)
        out = OUT / "video" / f"{self.stamp}.mp4"
        shutil.move(done["file"], out)
        return str(out)


def dist(a, x, z):
    return ((a[0] - x) ** 2 + (a[2] - z) ** 2) ** 0.5
