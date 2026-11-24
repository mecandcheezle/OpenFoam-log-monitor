#!/usr/bin/env python3
"""플루언트 잔차 그래프가 부러워서 만듬 feat-챗지피리~

OpenFOAM 돌려놓고 긴 로그 훑다가 눈 아플 때 쓰면 짱이야 노안 방지 고트
로그 파일 하나 넣으면 어디까지 돌았는지랑 잔차가 어떻게 변하는지 한 화면에서 볼 수 있음 꽤 이쁜듯

실행 예시
    python3 foam_monitor.py /path/to/case/log.simpleFoam

경로 없이 실행하면 로그 위치를 물어봅니다.
q 누르면 모니터만 꺼짐
"""

import argparse
import curses
import math
import os
import re
import sys
import time
from collections import OrderedDict, deque

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TIME = re.compile(r"^Time\s*=\s*(" + NUMBER + r")\s*$")
RESIDUAL = re.compile(r"Solving for\s+(\S+),\s*Initial residual\s*=\s*(" + NUMBER + r"),\s*Final residual\s*=\s*(" + NUMBER + r")")
EXEC_TIME = re.compile(r"ExecutionTime\s*=\s*(" + NUMBER + r").*ClockTime\s*=\s*(" + NUMBER + r")")


def arguments():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", nargs="?", help="One log path; omit to enter absolute path interactively")
    p.add_argument("--case", help="Case directory containing system/controlDict")
    p.add_argument("--start", type=float, help="Progress range start; override controlDict")
    p.add_argument("--end", type=float, help="Progress range end; override controlDict")
    p.add_argument("--mode", choices=["auto", "steady", "transient", "mesh"], default="auto")
    p.add_argument("--interval", type=float, default=2.0, help="Refresh seconds (minimum 1; default 2)")
    p.add_argument("--once", action="store_true", help="Read current content once and exit")
    p.add_argument("--no-clear", action="store_true", help="Append snapshots instead of redrawing terminal")
    p.add_argument("--text", action="store_true", help="Plain text output instead of terminal dashboard")
    a = p.parse_args()
    if a.log is None:
        if not sys.stdin.isatty():
            p.error("Supply a log path when standard input is not a terminal")
        print("OpenFOAM monitor | No installation | Read-only")
        while True:
            try:
                value = input("Log absolute path (q to quit): ").strip()
            except (EOFError, KeyboardInterrupt):
                raise SystemExit(0)
            if value.lower() == "q":
                raise SystemExit(0)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            value = os.path.expanduser(value)
            if not os.path.isabs(value):
                print("Enter an absolute path, e.g. /path/to/case/log.snappyHexMesh")
                continue
            if os.path.isdir(value):
                print("That is a directory. Select one log file.")
                continue
            a.log = value
            break
    a.log = os.path.abspath(os.path.expanduser(a.log))
    a.case_explicit = bool(a.case)
    if not math.isfinite(a.interval) or a.interval < 1:
        p.error("--interval must be finite and at least 1 second")
    for value in (a.start, a.end):
        if value is not None and not math.isfinite(value):
            p.error("--start/--end must be finite")
    return a


def settings(a):
    data = {}
    if a.case:
        path = os.path.join(a.case, "system", "controlDict")
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.S)
        content = re.sub(r"//[^\n]*", "", content)
        depth = 0
        top = []
        for ch in content:
            if ch == "{":
                depth += 1
                top.append(" ")
            elif ch == "}":
                depth -= 1
                top.append(";")
            elif depth == 0:
                top.append(ch)
        for match in re.finditer(r"\b(application|startTime|endTime|startFrom|stopAt)\s+([^;]+);", "".join(top)):
            data[match.group(1)] = match.group(2).strip()
    def scalar(key):
        value = data.get(key, "")
        return float(value) if re.fullmatch(NUMBER, value) else None
    start = a.start if a.start is not None else scalar("startTime")
    end = a.end if a.end is not None else scalar("endTime")
    # 재시작이면 실제로 어디서 이어 돌렸는지 로그나 사용자 입력에서 확인합니다.
    if a.start is None and data.get("startFrom", "startTime") != "startTime":
        start = None
    if start is not None and end is not None and end <= start:
        raise ValueError("Progress end must exceed start")
    return data, start, end


def auto_settings(a, state=None):
    """로그 첫 부분에서 케이스 경로를 찾습니다."""
    candidate = a.case if a.case_explicit else getattr(state, "case_path", None)
    hint = getattr(state, "start_hint", None)
    if not candidate:
        try:
            with open(a.log, "rb") as f:
                header = f.read(131072).decode("utf-8", errors="replace")
            match = re.search(r"^Case\s*:\s*(.+?)\s*$", header, re.M)
            if match and os.path.isabs(match.group(1)):
                candidate = match.group(1)
            match = re.search(r"^Create mesh for time\s*=\s*(" + NUMBER + r")", header, re.M)
            if match and hint is None:
                hint = float(match.group(1))
        except OSError:
            pass
    if not candidate:
        parent = os.path.dirname(a.log)
        if os.path.isfile(os.path.join(parent, "system", "controlDict")):
            candidate = parent
    note = "Case: " + (candidate or "not found in log header")
    dictionary = os.path.join(candidate, "system", "controlDict") if candidate else None
    try:
        stat = os.stat(dictionary) if dictionary else None
        key = (candidate, stat.st_mtime_ns if stat else None, stat.st_size if stat else None, a.start, a.end)
        if key != getattr(a, "_settings_key", None):
            clone = argparse.Namespace(case=candidate, start=a.start, end=a.end)
            a._settings_value = settings(clone)
            a._settings_key = key
        data, start, end = a._settings_value
    except OSError:
        data = {}
        start, end = a.start, a.end
        note += " | controlDict unreadable; press e/s to enter range"
    if start is None and a.start is None and hint is not None:
        start = hint
    if a.start is None and hint is not None:
        start = hint
    if start is not None and end is not None and end <= start:
        raise ValueError("Target end must exceed actual start; check controlDict or --start/--end")
    return data, start, end, note


class State:
    def __init__(self):
        self.application = "unknown"
        self.case_path = None
        self.start_hint = None
        self.current = None
        self.residuals = OrderedDict()
        self.cpu = self.wall = None
        self.status = "Monitoring (not a Slurm state)"
        self.finished = False
        self.failed = False
        self.stage = "Waiting for log output"
        self.latest = ""
        self.updated = None
        self.history = deque(maxlen=2000)
        self.initial = OrderedDict()
        self.recent = deque(maxlen=60)
        self.mesh_cells = None

    def feed(self, line):
        text = line.strip()
        if not text:
            return
        self.updated = time.monotonic()
        self.latest = text[:180]
        if text.startswith("Exec") and ":" in text:
            self.__init__()
            command = text.split(":", 1)[1].strip().split()
            self.application = os.path.basename(command[0]) if command else "unknown"
            self.updated = time.monotonic()
        if re.match(r"^Case\s*:", text):
            candidate = text.split(":", 1)[1].strip()
            if os.path.isabs(candidate):
                self.case_path = candidate
        match = re.match(r"^Create mesh for time\s*=\s*(" + NUMBER + r")", text)
        if match:
            self.start_hint = float(match.group(1))
        self.recent.append(text[:300])
        match = re.search(r"\b(?:nCells|cells)\s*[:=]\s*(\d+)", text)
        if match:
            self.mesh_cells = int(match.group(1))
        match = TIME.match(text)
        if match:
            if self.current is not None:
                self.history.append((self.current, dict(self.initial)))
            self.current = float(match.group(1))
            self.residuals.clear()
            self.initial.clear()
            self.stage = "Solving"
        match = RESIDUAL.search(text)
        if match:
            self.residuals[match.group(1)] = (match.group(2), match.group(3))
            self.initial.setdefault(match.group(1), float(match.group(2)))
        match = EXEC_TIME.search(text)
        if match:
            self.cpu, self.wall = match.groups()
        if any(word in text.lower() for word in ("refinement iteration", "morph iteration", "snapping", "writing mesh", "mesh ok", "failed", "converged")):
            self.stage = text[:180]
        # trapFpe는 시작할 때 나오는 안내라 오류 목록에서 빼줍니다.
        if not text.startswith("trapFpe:") and any(word in text for word in ("FOAM FATAL", "Segmentation fault", "Floating point exception", "DUE TO TIME LIMIT", "Out Of Memory", "oom-kill")):
            self.failed = True
            self.status = "ERROR detected: " + text[:150]
        if text == "End" or text.startswith("End //"):
            self.finished = True
            if not self.failed:
                self.status = "End marker found; check convergence/quality separately"


def display(state, a, data, start, end, begun):
    app = state.application if state.application != "unknown" else data.get("application", "unknown")
    mode = a.mode
    if mode == "auto":
        if any(x in app.lower() for x in ("mesh", "surface", "decompose", "reconstruct")):
            mode = "mesh"
        elif app == "simpleFoam":
            mode = "steady"
        else:
            mode = "auto"
    lines = ["OpenFOAM log monitor | read-only | Ctrl+C stops monitor only", "Log: " + os.path.abspath(a.log), "Application: " + app, "Status: " + state.status]
    if mode == "mesh":
        lines.append("Overall progress: unavailable for meshing (adaptive work)")
    elif state.current is not None and start is not None and end is not None:
        raw = 100 * (state.current - start) / (end - start)
        percent = min(100.0, max(0.0, raw))
        filled = int(percent / 5)
        label = "iteration limit" if mode == "steady" else "configured Time range"
        lines.append("[" + "#" * filled + "-" * (20 - filled) + "] {:.1f}% of {}".format(percent, label))
        lines.append("Current Time: {:g} | range {:g} -> {:g} | NOT convergence % / wall-time %".format(state.current, start, end))
    else:
        lines.append("Progress: unavailable yet; provide --case or --start and --end")
    lines.append("Stage: " + state.stage)
    if state.wall is not None:
        lines.append("Reported ExecutionTime: {} s | ClockTime: {} s".format(state.cpu, state.wall))
    age = "no output" if state.updated is None else "{:.0f}s since last output".format(time.monotonic() - state.updated)
    lines.append("Monitor elapsed: {:.0f}s | {}".format(time.monotonic() - begun, age))
    if data.get("stopAt", "endTime") != "endTime":
        lines.append("WARNING: stopAt differs from endTime; run may stop before range end")
    if state.residuals:
        lines.append("Latest residuals in current Time: field | initial -> final")
        lines.extend("  {} | {} -> {}".format(k, *v) for k, v in state.residuals.items())
    lines.append("Latest: " + state.latest)
    if sys.stdout.isatty() and not a.no_clear:
        sys.stdout.write("\033[2J\033[H")
    else:
        lines.insert(0, "--- " + time.strftime("%Y-%m-%d %H:%M:%S") + " ---")
    print("\n".join(lines), flush=True)


def main(a=None):
    a = a or arguments()
    try:
        data, start, end, note = auto_settings(a)
        state = State()
        identity = None
        offset = 0
        pending = b""
        begun = time.monotonic()
        while True:
            cycle = time.monotonic()
            try:
                stat = os.stat(a.log)
                new_identity = (stat.st_dev, stat.st_ino)
                if identity != new_identity or stat.st_size < offset:
                    identity, offset, pending = new_identity, 0, b""
                    state = State()
                with open(a.log, "rb") as stream:
                    stream.seek(offset)
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        offset = stream.tell()
                        parts = (pending + chunk).split(b"\n")
                        pending = parts.pop()
                        for line in parts:
                            state.feed(line.decode("utf-8", errors="replace"))
                        if len(pending) > 1048576:
                            raise ValueError("Log contains a line over 1 MiB; select a text log")
            except FileNotFoundError:
                state.status = "Waiting for log file (job may be pending)"
            data, start, end, note = auto_settings(a, state)
            display(state, a, data, start, end, begun)
            if a.once or state.finished or state.failed:
                return 1 if state.failed else 0
            time.sleep(max(0, a.interval - (time.monotonic() - cycle)))
    except KeyboardInterrupt:
        print("\nMonitor stopped. No job was cancelled.")
        return 0
    except (OSError, ValueError) as exc:
        print("Monitor error: " + str(exc), file=sys.stderr)
        return 2


class LogReader:
    """지난번에 읽은 위치부터 로그를 이어서 읽습니다."""
    def __init__(self, path):
        self.path = path
        self.identity = None
        self.offset = 0
        self.pending = b""
        self.state = State()

    def poll(self):
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            self.state.status = "Waiting for log file (job may be pending)"
            return
        identity = stat.st_dev, stat.st_ino
        if self.identity != identity or stat.st_size < self.offset:
            self.identity, self.offset, self.pending = identity, 0, b""
            self.state = State()
        with open(self.path, "rb") as stream:
            stream.seek(self.offset)
            # 로그가 커도 화면이 버벅이지 않게 한 번에 4 MiB까지만 읽어요.
            remaining = 4 * 1024 * 1024
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                self.offset = stream.tell()
                parts = (self.pending + chunk).split(b"\n")
                self.pending = parts.pop()
                for line in parts:
                    self.state.feed(line.decode("utf-8", errors="replace"))
                if len(self.pending) > 1048576:
                    raise ValueError("Not a text log: line exceeds 1 MiB")
        self.catching_up = self.offset < stat.st_size


def mode_for(a, state, data):
    if a.mode != "auto":
        return a.mode
    app = state.application if state.application != "unknown" else data.get("application", "unknown")
    if any(x in app.lower() for x in ("mesh", "surface", "decompose", "reconstruct")):
        return "mesh"
    return "steady" if app == "simpleFoam" else "transient" if app in ("pimpleFoam", "pisoFoam", "interFoam") else "auto"


def dashboard(screen, a, data, start, end):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(max(1000, int(a.interval * 1000)))
    colours = []
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        for i, colour in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                    curses.COLOR_MAGENTA, curses.COLOR_RED, curses.COLOR_BLUE, curses.COLOR_WHITE), 1):
            curses.init_pair(i, colour, background)
            colours.append(curses.color_pair(i))
    reader = LogReader(a.log)
    begun = time.monotonic()
    next_poll = 0
    paused = False
    selected = 0
    window_size = 300
    error = ""
    config_note = ""

    def put(y, x, text, colour=0):
        h, w = screen.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w - 1:
            return
        try:
            screen.addnstr(y, x, str(text), max(0, w-x-1), colour)
        except curses.error:
            pass

    while True:
        now = time.monotonic()
        if now >= next_poll and not paused:
            try:
                reader.poll()
                error = ""
            except (OSError, ValueError) as exc:
                error = str(exc)
            next_poll = now + a.interval
        s = reader.state
        try:
            data, start, end, config_note = auto_settings(a, s)
        except ValueError as exc:
            error = str(exc)
            data, start, end = {}, None, None
        mode = mode_for(a, s, data)
        screen.erase()
        h, w = screen.getmaxyx()
        put(0, 0, "OpenFOAM MONITOR | q: quit | space: pause | tab: field | +/-: history | e/s: end/start", curses.A_BOLD)
        put(1, 0, os.path.abspath(a.log))
        put(2, 0, "{} | {}{}".format(s.application, "PAUSED | " if paused else "", error or s.status))
        if mode == "mesh":
            progress = "Meshing: no reliable overall percentage"
        elif s.current is not None and start is not None and end is not None:
            pc = max(0, min(100, 100*(s.current-start)/(end-start)))
            bars = int(pc/5)
            unit = "iteration limit" if mode == "steady" else "physical-time range" if mode == "transient" else "configured Time range"
            progress = "[{}{}] {:.1f}% of {} | {:g} / {:g} (start {:g})".format("#"*bars, "-"*(20-bars), pc, unit, s.current, end, start)
        else:
            progress = "Progress unavailable: use --case or --start / --end (restart needs --start)"
        put(3, 0, progress, curses.A_BOLD)
        age = "no new output yet" if s.updated is None else "last update {:.0f}s ago".format(now-s.updated)
        put(4, 0, "NOT convergence % or wall-time % | monitor {:.0f}s | {} | ClockTime {}s".format(now-begun, age, s.wall or "?"))
        put(5, 0, "Stage: {}{}".format(s.stage, " | Reading log backlog" if getattr(reader, "catching_up", False) else ""))
        if h < 24 or w < 80:
            put(7, 0, "Enlarge terminal to at least 80 columns x 24 rows for graph.")
        elif mode == "mesh":
            put(7, 0, "MESH / SURFACE UTILITY | No fixed work total; overall % is not estimated", curses.A_BOLD)
            put(8, 0, "Last reported cell count: " + (str(s.mesh_cells) if s.mesh_cells is not None else "not reported yet"))
            put(10, 0, "Recent log output:", curses.A_BOLD)
            for index, line in enumerate(list(s.recent)[-max(1, h-15):]):
                put(11+index, 0, line)
        else:
            records = list(s.history)
            if s.current is not None and s.initial:
                records.append((s.current, dict(s.initial)))
            fields = list(OrderedDict.fromkeys(field for _, values in records for field in values))
            choices = [None] + fields
            selected %= len(choices)
            field_filter = choices[selected]
            visible = fields[:7] if field_filter is None else [field_filter]
            records = records[-window_size:]
            put(6, 0, "Initial residual (first solve per Time), log10 scale | {} | last {} samples".format(field_filter or "all (up to 7 fields)", window_size))
            top, bottom, left, right = 8, h-7, 10, w-3
            ph, pw = bottom-top, right-left
            values = [value for _, v in records for field, value in v.items()
                      if field in visible and math.isfinite(value) and value > 0]
            if values:
                lo = max(-300, min(-6, math.floor(math.log10(min(values)))))
                hi = min(300, max(0, math.ceil(math.log10(max(values)))))
            else:
                lo, hi = -6, 0
            ticks = min(6, ph)
            for tick in range(ticks+1):
                fraction = tick/ticks
                y = top+round(fraction*ph)
                exponent = hi-fraction*(hi-lo)
                put(y, 0, "1e{:+.1f}".format(exponent))
                put(y, left, "."*(pw+1), curses.A_DIM)
            if records:
                xmin, xmax = records[0][0], records[-1][0]
                if xmax <= xmin:
                    xmax = xmin + 1
                for index, field in enumerate(visible):
                    colour = colours[fields.index(field) % len(colours)] if colours else 0
                    previous = None
                    for t, values_for_time in records:
                        value = values_for_time.get(field)
                        if value is None or not math.isfinite(value) or value < 0:
                            previous = None
                            continue
                        # 0은 로그를 취할 수 없어서 그래프 맨 아래에 찍습니다.
                        logvalue = math.log10(value) if value > 0 else lo
                        x = left+round((t-xmin)/(xmax-xmin)*pw)
                        y = top+round((hi-max(lo, min(hi, logvalue)))/(hi-lo)*ph)
                        if previous:
                            px, py = previous
                            distance = max(abs(x-px), abs(y-py), 1)
                            for j in range(distance+1):
                                put(round(py+(y-py)*j/distance), round(px+(x-px)*j/distance), str((fields.index(field)+1) % 10), colour)
                        else:
                            put(y, x, str((fields.index(field)+1) % 10), colour)
                        previous = x, y
                put(bottom+1, left, "{:g}".format(xmin))
                put(bottom+1, max(left+10, right-16), "{:g} {}".format(records[-1][0], "iter" if mode == "steady" else "Time"))
            else:
                put(top+2, left+2, "Waiting for solver residuals (snappy has no field-residual plot).")
            legend = []
            for field in visible:
                val = s.residuals.get(field)
                legend.append("{}:{} {}".format((fields.index(field)+1) % 10, field, val[0] if val else "-"))
            put(h-4, 0, " | ".join(legend))
        put(h-3, 0, config_note)
        put(h-2, 0, "Latest: " + s.latest)
        put(h-1, 0, "End != convergence/mesh quality pass. No output != job stopped. Check squeue/sacct separately.")
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), ord('Q'), 27):
            break
        if key == ord(' '):
            paused = not paused
        if key == 9:
            selected += 1
        if key in (ord('+'), ord('=')):
            window_size = min(2000, window_size*2)
        if key == ord('-'):
            window_size = max(50, window_size//2)
        if key in (ord('e'), ord('s')):
            try:
                prompt = "Target end Time/iteration: " if key == ord('e') else "Start Time/iteration: "
                screen.move(h-1, 0)
                screen.clrtoeol()
                put(h-1, 0, prompt)
                screen.refresh()
                curses.echo()
                screen.timeout(-1)
                value = screen.getstr(h-1, len(prompt), 40).decode("ascii").strip()
                number = float(value)
                if math.isfinite(number):
                    if key == ord('e'):
                        a.end = number
                    else:
                        a.start = number
            except (ValueError, UnicodeError, curses.error):
                pass
            finally:
                curses.noecho()
                screen.timeout(max(1000, int(a.interval * 1000)))


def entry():
    a = arguments()
    if a.once or a.text or not sys.stdout.isatty():
        return main(a)
    try:
        data, start, end, note = auto_settings(a)
        curses.wrapper(dashboard, a, data, start, end)
        print("Monitor closed. No OpenFOAM/Slurm job was cancelled.")
        return 0
    except KeyboardInterrupt:
        print("Monitor closed. No OpenFOAM/Slurm job was cancelled.")
        return 0
    except (OSError, ValueError, curses.error) as exc:
        print("Monitor error: {}. Try --text for plain output.".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(entry())
