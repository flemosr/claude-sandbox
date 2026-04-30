#!/usr/bin/env python3
"""
Flutter Host Bridge

HTTP API server for controlling a Flutter app from a Docker container.
Uses only Python standard library.

Configuration is passed via command-line arguments.

Endpoints:
    GET    /health       - Health check (no auth)
    POST   /health       - Health check with auth (for token verification)
    GET    /status       - Bridge status (auth required)
    GET    /devices      - List available devices (auth required)
    POST   /launch       - Launch Flutter app (auth required)
    POST   /attach       - Attach to running Flutter app (auth required)
    POST   /detach       - Detach/stop Flutter app (auth required)
    POST   /hot-reload   - Hot reload (auth required)
    POST   /hot-restart  - Hot restart (auth required)
    POST   /stop         - Shutdown bridge
    POST   /restart      - Restart bridge process with same argv
    GET    /logs         - Recent log lines (auth required)
    GET    /screenshot   - Take screenshot, returns PNG (auth required)
    GET    /ios-simulator-probe - Probe fixed host iOS Simulator input capabilities
    GET    /ios-coordinate-map - Diagnose iOS Simulator coordinate mapping
    POST   /tap          - UI automation tap (auth required)
    POST   /type         - UI automation text input (auth required)
    POST   /press        - UI automation key press (auth required)
    POST   /scroll       - UI automation scroll (auth required)
    POST   /inspect      - UI automation inspect (auth required)
    POST   /wait         - UI automation wait (auth required)
"""

import argparse
import ctypes
import ctypes.util
import json
import math
import os
import re
import shutil
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


# ---- Threaded HTTP Server ----

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ---- Bridge State ----

def _read_pubspec_app_name(project_dir):
    pubspec = os.path.join(project_dir, "pubspec.yaml")
    try:
        with open(pubspec) as f:
            for line in f:
                m = re.match(r"^name:\s*(['\"]?)(\S+?)\1\s*$", line)
                if m:
                    return m.group(2)
    except (OSError, UnicodeDecodeError):
        pass
    return os.path.basename(project_dir)


class BridgeState:
    def __init__(self, token, project_dir, device_id, target, flutter_path,
                 run_args):
        self.token = token
        self.project_dir = project_dir
        self.device_id = device_id
        self.target = target
        self.flutter_path = flutter_path
        self.run_args = parse_run_args(run_args)

        self.process = None
        self.subprocess_type = None
        self.subprocess_lock = threading.Lock()
        self.log_buffer = deque(maxlen=1000)
        self.vm_service_url = None
        self._status = "idle"
        self._status_message = ""
        self.stop_event = threading.Event()
        self._cache_lock = threading.Lock()
        self._devices_cache = None
        self._devices_cache_time = 0
        self._devices_cache_error = None
        self._tools_cache = {}
        self.app_name = _read_pubspec_app_name(project_dir)

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    def to_status_dict(self):
        return {
            "status": self._status,
            "subprocess_type": self.subprocess_type,
            "vm_service_url": self.vm_service_url,
            "device_id": self.device_id,
            "app_name": self.app_name,
            "message": self._status_message,
            "screenshot": self.screenshot_status(),
            "ui_automation": self.ui_automation_status(),
        }

    def add_log(self, line):
        self.log_buffer.append(line)

    def get_logs(self):
        return list(self.log_buffer)

    def has_live_process(self):
        with self.subprocess_lock:
            return self.process is not None and self.process.poll() is None

    def update_devices_cache(self, devices):
        with self._cache_lock:
            self._devices_cache = devices
            self._devices_cache_time = time.time()
            self._devices_cache_error = None

    def update_devices_cache_error(self, error):
        with self._cache_lock:
            self._devices_cache_error = error
            self._devices_cache_time = time.time()

    def active_device_metadata(self):
        return find_device_metadata(
            self.device_id, self.devices_machine_cached()
        )

    def devices_machine_cached(self, ttl_seconds=5):
        if not self.device_id:
            return self._devices_cache or []

        now = time.time()
        with self._cache_lock:
            if self._devices_cache is not None:
                if now - self._devices_cache_time < ttl_seconds:
                    return self._devices_cache
                if find_device_metadata(self.device_id, self._devices_cache):
                    return self._devices_cache

        with self._cache_lock:
            had_cache = self._devices_cache is not None
        try:
            result = subprocess.run(
                [self.flutter_path, "devices", "--machine"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                if had_cache:
                    self.update_devices_cache_error(result.stderr.strip())
                with self._cache_lock:
                    return self._devices_cache or []
            devices = json.loads(result.stdout)
            if isinstance(devices, list):
                self.update_devices_cache(devices)
                return devices
            if had_cache:
                self.update_devices_cache_error(
                    "flutter devices returned non-list JSON"
                )
        except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
            if had_cache:
                self.update_devices_cache_error(str(e))
        with self._cache_lock:
            return self._devices_cache or []

    def tool_availability(self, backend):
        with self._cache_lock:
            if backend in self._tools_cache:
                return self._tools_cache[backend]
        tools = probe_backend_tools(backend)
        with self._cache_lock:
            self._tools_cache[backend] = tools
        return tools

    def ui_automation_status(self):
        metadata = self.active_device_metadata()
        target = classify_device(self.device_id, metadata)
        tools = self.tool_availability(target["backend"])
        status = build_ui_automation_status(
            bridge_status=self.status,
            has_process=self.has_live_process(),
            has_vm_service=bool(self.vm_service_url),
            device_id=self.device_id,
            target=target,
            tools=tools,
            device_error=self._devices_cache_error,
        )
        if status["ready"] and target["backend"] == "macos-desktop":
            window, error = _macos_get_app_window_info(self.app_name)
            if window:
                status["screen"] = _macos_window_screen_metadata(window)
            elif error:
                status["screen"] = {"error": error}
        elif status["ready"] and target["backend"] == "ios-simulator":
            device = target.get("device") or {}
            status["screen"] = _ios_simulator_screen_metadata(
                device_name=device.get("name")
            )
            _disable_ios_window_dependent_actions_when_unavailable(status)
            _disable_ios_host_keyboard_actions_when_unavailable(status)
            _disable_ios_content_match_actions_when_unavailable(status)
        return status

    def screenshot_status(self):
        metadata = self.active_device_metadata()
        target = classify_device(self.device_id, metadata)
        return build_screenshot_status(
            bridge_status=self.status,
            has_process=self.has_live_process(),
            device_id=self.device_id,
            target=target,
        )


# ---- UI Automation Capability and Validation Helpers ----

UI_ACTIONS = ("tap", "type", "press", "scroll", "inspect", "wait")

BASE_KEYS = {
    "enter", "tab", "escape", "backspace", "space",
    "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown",
}
MODIFIER_KEYS = {"command", "shift", "option", "control"}

# AppleScript key code mapping for non-typable named keys.
# typable single-character keys (a-z, 0-9, etc.) are sent via keystroke.
_APPLESCRIPT_KEY_CODES = {
    "enter": 36,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "backspace": 51,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


# CoreGraphics and CoreFoundation CDLL singletons — loaded once on first use
# so that repeated tap/screenshot/status calls don't re-resolve and re-open
# the dynamic libraries on every invocation.
_macos_libs_lock = threading.Lock()
_macos_cg = None
_macos_cf = None
_ios_tap_snapshot_lock = threading.Lock()
_ios_tap_snapshot_cache = {}


def _load_macos_libs():
    global _macos_cg, _macos_cf
    if _macos_cg is not None:
        return _macos_cg, _macos_cf
    with _macos_libs_lock:
        if _macos_cg is not None:
            return _macos_cg, _macos_cf
        cg_path = (
            ctypes.util.find_library("CoreGraphics")
            or "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cf_path = (
            ctypes.util.find_library("CoreFoundation")
            or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        cg = ctypes.CDLL(cg_path)
        cf = ctypes.CDLL(cf_path)
        cg.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32
        ]
        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CGEventPost.restype = None
        cg.CGWindowListCopyWindowInfo.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32
        ]
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
        ]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
        ]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        _macos_cg = cg
        _macos_cf = cf
    return _macos_cg, _macos_cf


def _escape_applescript_string(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace(
        "\r", "\\r"
    ).replace("\n", "\\n")


def _macos_targeted_script(app_name, command):
    return (
        f"tell application \"System Events\"\n"
        f"set frontmost of process "
        f"\"{_escape_applescript_string(app_name)}\" to true\n"
        f"{command}\n"
        f"end tell"
    )


def _run_osascript(script, timeout=5):
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return bridge_error(
                f"osascript failed: {result.stderr.strip()}", "BACKEND_ERROR"
            )
        return None
    except subprocess.TimeoutExpired:
        return bridge_error("osascript timed out", "BACKEND_ERROR")
    except OSError as e:
        return bridge_error(
            f"osascript invocation failed: {e}", "BACKEND_ERROR"
        )


def _run_osascript_capture(script, timeout=10):
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return None, bridge_error(
                f"osascript failed: {result.stderr.strip()}",
                "BACKEND_ERROR",
            )
        return result.stdout, None
    except subprocess.TimeoutExpired:
        return None, bridge_error("osascript timed out", "BACKEND_ERROR")
    except OSError as e:
        return None, bridge_error(
            f"osascript invocation failed: {e}", "BACKEND_ERROR"
        )


def _macos_press(app_name, key):
    parts = key.split("+")
    modifiers = parts[:-1]
    base = parts[-1]

    if modifiers:
        mod_str = "{" + ", ".join(f"{m} down" for m in modifiers) + "}"
        if base in _APPLESCRIPT_KEY_CODES:
            command = (
                f"key code {_APPLESCRIPT_KEY_CODES[base]} using {mod_str}"
            )
        else:
            command = (
                f"keystroke \"{_escape_applescript_string(base)}\" "
                f"using {mod_str}"
            )
    else:
        if base in _APPLESCRIPT_KEY_CODES:
            command = f"key code {_APPLESCRIPT_KEY_CODES[base]}"
        else:
            command = (
                f"keystroke \"{_escape_applescript_string(base)}\""
            )

    script = _macos_targeted_script(app_name, command)
    error = _run_osascript(script)
    if error:
        return error
    return {"action": "press", "key": key}


def _macos_type(app_name, text):
    command = (
        f"keystroke \"{_escape_applescript_string(text)}\""
    )
    script = _macos_targeted_script(app_name, command)
    error = _run_osascript(script)
    if error:
        return error
    return {"action": "type"}


def _ios_type_text(text):
    result = _macos_type("Simulator", text)
    if "error" in result:
        return result
    return {
        "action": "type",
        "text_length": len(text),
        "method": "host-keystroke-to-simulator",
    }


def _ios_press_key(key):
    result = _macos_press("Simulator", key)
    if "error" in result:
        return result
    return {
        "action": "press",
        "key": key,
        "method": "host-keypress-to-simulator",
    }


def _macos_inspect_script(app_name):
    escaped_app = _escape_applescript_string(app_name)
    return f'''
on replaceText(findText, replaceTextValue, sourceText)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to findText
    set textItems to text items of sourceText
    set AppleScript's text item delimiters to replaceTextValue
    set joinedText to textItems as text
    set AppleScript's text item delimiters to oldDelimiters
    return joinedText
end replaceText

on cleanField(fieldValue)
    if fieldValue is missing value then
        return ""
    end if
    try
        set textValue to fieldValue as text
    on error
        set textValue to ""
    end try
    set textValue to my replaceText(return, " ", textValue)
    set textValue to my replaceText(linefeed, " ", textValue)
    set textValue to my replaceText(tab, " ", textValue)
    return textValue
end cleanField

on emitElement(uiElement)
    set roleText to ""
    set subroleText to ""
    set nameText to ""
    set descriptionText to ""
    set valueText to ""
    set enabledText to ""
    set xText to ""
    set yText to ""
    set wText to ""
    set hText to ""

    try
        set roleText to my cleanField(role of uiElement)
    end try
    try
        set subroleText to my cleanField(subrole of uiElement)
    end try
    try
        set nameText to my cleanField(name of uiElement)
    end try
    try
        set descriptionText to my cleanField(description of uiElement)
    end try
    try
        set valueText to my cleanField(value of uiElement)
    end try
    try
        set enabledText to my cleanField(enabled of uiElement)
    end try
    try
        set elementPosition to position of uiElement
        set xText to my cleanField(item 1 of elementPosition)
        set yText to my cleanField(item 2 of elementPosition)
    end try
    try
        set elementSize to size of uiElement
        set wText to my cleanField(item 1 of elementSize)
        set hText to my cleanField(item 2 of elementSize)
    end try

    return roleText & tab & subroleText & tab & nameText & tab & descriptionText & tab & valueText & tab & enabledText & tab & xText & tab & yText & tab & wText & tab & hText
end emitElement

tell application "System Events"
    set targetProcess to process "{escaped_app}"
    set frontmost of targetProcess to true
    delay 0.1
    set outputLines to {{}}
    repeat with targetWindow in windows of targetProcess
        set outputLines to outputLines & {{my emitElement(targetWindow)}}
        try
            set elementList to entire contents of targetWindow
            repeat with uiElement in elementList
                set outputLines to outputLines & {{my emitElement(uiElement)}}
            end repeat
        end try
    end repeat
end tell

set oldDelimiters to AppleScript's text item delimiters
set AppleScript's text item delimiters to linefeed
set outputText to outputLines as text
set AppleScript's text item delimiters to oldDelimiters
return outputText
'''


def _macos_element_type(role):
    normalized = role.lower().replace("ax", "")
    if "button" in normalized:
        return "button"
    if "textfield" in normalized:
        return "text_field"
    if "statictext" in normalized or "text" in normalized:
        return "text"
    if "window" in normalized:
        return "window"
    if "group" in normalized:
        return "group"
    return normalized or "element"


def _parse_bool_text(value):
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _parse_number_text(value):
    try:
        if value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_number(value):
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return value


def _normalize_macos_rect(x, y, w, h, window):
    if None in (x, y, w, h):
        return None
    win_x, win_y, _, _ = window["bounds"]
    local_x = x - win_x if x >= win_x else x
    local_y = y - win_y if y >= win_y else y
    return {
        "x": _display_number(local_x),
        "y": _display_number(local_y),
        "w": _display_number(w),
        "h": _display_number(h),
    }


def _normalize_macos_field(value):
    text = str(value)
    if text == "missing value":
        return ""
    return text


def _parse_macos_inspect_output(stdout, window):
    elements = []
    for line in stdout.splitlines():
        fields = [_normalize_macos_field(field) for field in line.split("\t")]
        if len(fields) < 10:
            continue
        role, subrole, label, description, value, enabled = fields[:6]
        x, y, w, h = (
            _parse_number_text(fields[6]),
            _parse_number_text(fields[7]),
            _parse_number_text(fields[8]),
            _parse_number_text(fields[9]),
        )
        text = next(
            (candidate for candidate in (label, value, description)
             if candidate),
            "",
        )
        element = {
            "type": _macos_element_type(role),
            "text": text,
            "role": role,
            "subrole": subrole,
            "label": label,
            "description": description,
            "value": value,
            "enabled": _parse_bool_text(enabled),
            "rect": _normalize_macos_rect(x, y, w, h, window),
            "coordinate_space": "app-window-points",
        }
        elements.append(element)
    return elements


def _vm_service_get(vm_service_url, method, params=None, timeout=5):
    if not vm_service_url:
        return None, bridge_error(
            "Flutter VM service URL is unavailable", "UI_NOT_READY"
        )

    base_url = vm_service_url if vm_service_url.endswith("/") else f"{vm_service_url}/"
    query = urlencode(params or {})
    url = f"{base_url}{method}"
    if query:
        url = f"{url}?{query}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
    except (OSError, json.JSONDecodeError) as e:
        return None, bridge_error(
            f"Flutter VM service request failed: {e}",
            "BACKEND_ERROR",
            vm_method=method,
        )

    if "error" in payload:
        error = payload["error"]
        return None, bridge_error(
            f"Flutter VM service returned an error for {method}",
            "BACKEND_ERROR",
            vm_method=method,
            vm_error=error,
        )
    return payload.get("result"), None


def _flutter_vm_isolate_id(vm_service_url):
    vm, error = _vm_service_get(vm_service_url, "getVM")
    if error:
        return None, error
    for isolate in vm.get("isolates", []):
        isolate_id = isolate.get("id")
        if isolate_id:
            return isolate_id, None
    return None, bridge_error(
        "Flutter VM service did not report a live isolate", "UI_NOT_READY"
    )


def _flutter_inspector_root(vm_service_url, isolate_id, group_name):
    params = {"isolateId": isolate_id, "groupName": group_name}
    response, error = _vm_service_get(
        vm_service_url,
        "ext.flutter.inspector.getRootWidgetSummaryTreeWithPreviews",
        params,
        timeout=10,
    )
    if error:
        return None, error
    return response.get("result"), None


def _flutter_inspector_layout_tree(
    vm_service_url, isolate_id, group_name, root_id
):
    params = {
        "isolateId": isolate_id,
        "groupName": group_name,
        "id": root_id,
        "subtreeDepth": "100",
    }
    response, error = _vm_service_get(
        vm_service_url,
        "ext.flutter.inspector.getLayoutExplorerNode",
        params,
        timeout=10,
    )
    if error:
        return None, error
    return response.get("result"), None


def _flutter_debug_dump_app(vm_service_url, isolate_id):
    params = {"isolateId": isolate_id}
    response, error = _vm_service_get(
        vm_service_url,
        "ext.flutter.debugDumpApp",
        params,
        timeout=10,
    )
    if error:
        return None, error
    data = response.get("data") if isinstance(response, dict) else None
    if data is None:
        return None, bridge_error(
            "Flutter debugDumpApp did not return widget data", "BACKEND_ERROR"
        )
    return str(data), None


def _number_from_string(value):
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _flutter_node_size(node):
    size = node.get("size")
    if not isinstance(size, dict):
        return None
    width = _number_from_string(size.get("width"))
    height = _number_from_string(size.get("height"))
    if width is None or height is None:
        return None
    return width, height


def _flutter_offset_from_render_properties(node):
    render_object = node.get("renderObject")
    if not isinstance(render_object, dict):
        return None
    for prop in render_object.get("properties", []):
        if not isinstance(prop, dict) or prop.get("name") != "parentData":
            continue
        match = re.search(
            r"offset=Offset\((-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?)\)",
            str(prop.get("description", "")),
        )
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def _flutter_node_offset_info(node):
    parent_data = node.get("parentData")
    if isinstance(parent_data, dict):
        x = _number_from_string(parent_data.get("offsetX"))
        y = _number_from_string(parent_data.get("offsetY"))
        if x is not None and y is not None:
            return x, y, True

    offset = _flutter_offset_from_render_properties(node)
    if offset:
        return offset[0], offset[1], True
    return 0, 0, False


def _flutter_render_object_id(node):
    render_object = node.get("renderObject")
    if not isinstance(render_object, dict):
        return None
    return render_object.get("valueId")


def _flutter_node_offset(node):
    x, y, _ = _flutter_node_offset_info(node)
    return x, y


def _unescape_flutter_quoted_string(value):
    replacements = {
        r"\\": "\\",
        r"\"": '"',
        r"\'": "'",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
    }
    result = value
    for escaped, replacement in replacements.items():
        result = result.replace(escaped, replacement)
    return result


def _flutter_widget_type(node):
    widget_type = node.get("widgetRuntimeType")
    if widget_type:
        return str(widget_type)
    description = str(node.get("description") or "")
    return re.split(r"[-(]", description, maxsplit=1)[0]


def _normalize_flutter_key_value(value):
    value = value.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in ("'", '"')
    ):
        value = value[1:-1]
    return _unescape_flutter_quoted_string(value)


def _flutter_key_from_string(value):
    text = str(value or "")
    patterns = (
        r"-\[\s*<(?P<key>(?:\\.|[^>])*)>\s*\]",
        r"\bkey:\s*\[\s*<(?P<key>(?:\\.|[^>])*)>\s*\]",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            key = _normalize_flutter_key_value(match.group("key"))
            if key:
                return key
    return None


def _flutter_key_info_from_node(node):
    key = _flutter_key_from_string(node.get("description"))
    if not key:
        for prop in node.get("properties") or []:
            if not isinstance(prop, dict) or prop.get("name") != "key":
                continue
            key = _flutter_key_from_string(
                prop.get("description") or prop.get("value") or ""
            )
            if key:
                break
    if not key:
        return None
    return {
        "key": key,
        "widget_type": _flutter_widget_type(node),
        "source_field": "key",
    }


def _flutter_debug_widget_labels(debug_dump):
    if not debug_dump:
        return []

    labels = []
    pattern = re.compile(
        r"\b(?P<widget>[A-Za-z_][A-Za-z0-9_<>.]*)"
        r"\((?=[^\n]*\btooltip:\s*\"(?P<label>(?:\\.|[^\"\\])*)\")"
    )
    for line in debug_dump.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        label = _unescape_flutter_quoted_string(match.group("label"))
        if not label:
            continue
        labels.append({
            "text": label,
            "widget_type": match.group("widget"),
            "source_field": "tooltip",
        })
    return labels


def _flutter_summary_texts(root):
    texts = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        value_id = node.get("valueId")
        text = node.get("textPreview")
        if value_id and text:
            texts[value_id] = {
                "text": str(text),
                "widget_type": _flutter_widget_type(node),
            }
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return texts


def _flutter_summary_keys(root):
    keys = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        value_id = node.get("valueId")
        key_info = _flutter_key_info_from_node(node)
        if value_id and key_info:
            keys[value_id] = key_info
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return keys


def _flutter_summary_labels(root, debug_dump):
    labels_by_type = {}
    for label in _flutter_debug_widget_labels(debug_dump):
        labels_by_type.setdefault(label["widget_type"], []).append(label)

    labels = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        value_id = node.get("valueId")
        widget_type = _flutter_widget_type(node)
        candidates = labels_by_type.get(widget_type)
        if value_id and candidates:
            labels[value_id] = candidates.pop(0)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return labels


def _flutter_content_y_offset(window, layout_root):
    size = _flutter_node_size(layout_root) or (None, None)
    _, root_height = size
    if root_height is None:
        return 0
    _, _, _, window_height = window["bounds"]
    offset = window_height - root_height
    # Treat a gap up to 120px as window chrome (title bar / toolbar).
    # Standard macOS title bars are 28–52px; 120 is generous enough to cover
    # toolbars without misidentifying large content offsets as chrome.
    if 0 <= offset <= 120:
        return offset
    return 0


def _flutter_default_fab_rect(size, layout_root, chrome_y):
    root_size = _flutter_node_size(layout_root)
    if not size or not root_size:
        return None
    width, height = size
    root_width, root_height = root_size
    margin = 16
    return {
        "x": _display_number(root_width - margin - width),
        "y": _display_number(chrome_y + root_height - margin - height),
        "w": _display_number(width),
        "h": _display_number(height),
    }


def _flutter_inspector_elements_from_trees(
    summary_root, layout_root, window, debug_dump=None,
    coordinate_space="app-window-points",
):
    summary_texts = _flutter_summary_texts(summary_root)
    summary_labels = _flutter_summary_labels(summary_root, debug_dump)
    summary_keys = _flutter_summary_keys(summary_root)
    chrome_y = _flutter_content_y_offset(window, layout_root)
    elements = []

    def walk(node, origin_x=0, origin_y=0, applied_render_offsets=None):
        if not isinstance(node, dict):
            return
        applied_render_offsets = applied_render_offsets or frozenset()
        offset_x, offset_y, explicit_offset = _flutter_node_offset_info(node)
        render_object_id = _flutter_render_object_id(node)
        if explicit_offset and render_object_id in applied_render_offsets:
            offset_x = 0
            offset_y = 0
            explicit_offset = False
        x = origin_x + offset_x
        y = origin_y + offset_y
        child_applied_render_offsets = applied_render_offsets
        if explicit_offset and render_object_id:
            child_applied_render_offsets = (
                applied_render_offsets | {render_object_id}
            )

        value_id = node.get("valueId")
        text_info = summary_texts.get(value_id) or summary_labels.get(value_id)
        key_info = summary_keys.get(value_id) or _flutter_key_info_from_node(
            node
        )
        if text_info or key_info:
            size = _flutter_node_size(node)
            rect = None
            if size:
                width, height = size
                rect = {
                    "x": _display_number(x),
                    "y": _display_number(y + chrome_y),
                    "w": _display_number(width),
                    "h": _display_number(height),
                }
                if (
                    not explicit_offset
                    and text_info
                    and text_info.get("source_field") == "tooltip"
                    and text_info.get("widget_type") == "FloatingActionButton"
                ):
                    rect = _flutter_default_fab_rect(
                        size, layout_root, chrome_y
                    )
                    rect_source = "material-default-fab-location"
                else:
                    rect_source = "layout-offset"
            else:
                rect_source = None
            text = text_info["text"] if text_info else ""
            widget_type = (
                text_info.get("widget_type")
                if text_info
                else key_info.get("widget_type")
            )
            source_field = (
                text_info.get("source_field")
                if text_info
                else key_info.get("source_field")
            )
            element = {
                "type": "flutter_widget",
                "text": text,
                "role": "",
                "subrole": "",
                "label": text,
                "description": node.get("description", ""),
                "value": "",
                "enabled": None,
                "rect": rect,
                "coordinate_space": coordinate_space,
                "source": "flutter-inspector",
                "widget_type": widget_type,
                "value_id": value_id,
                "source_field": source_field,
                "rect_source": rect_source,
            }
            if key_info:
                element["key"] = key_info["key"]
                if text_info:
                    element["source_field"] = "text,key"
                elif not element["description"]:
                    element["description"] = key_info["widget_type"]
            elements.append({
                **element,
            })

        children = node.get("children") or []
        if _flutter_widget_type(node) == "ListView":
            child_y = 0
            for child in children:
                walk(child, x, y + child_y, child_applied_render_offsets)
                child_size = _flutter_node_size(child)
                if child_size:
                    child_y += child_size[1]
            return

        for child in children:
            walk(child, x, y, child_applied_render_offsets)

    walk(layout_root)
    return elements


def _flutter_inspector_snapshot(
    vm_service_url, window=None, coordinate_space="app-window-points",
):
    if window is None:
        window = {"window_id": None, "bounds": (0, 0, 0, 0)}
    isolate_id, error = _flutter_vm_isolate_id(vm_service_url)
    if error:
        return [], error
    group_name = f"workcell-{int(time.time() * 1000)}"
    summary_root, error = _flutter_inspector_root(
        vm_service_url, isolate_id, group_name
    )
    if error:
        return [], error
    if not isinstance(summary_root, dict) or not summary_root.get("valueId"):
        return [], bridge_error(
            "Flutter inspector did not return a widget tree", "BACKEND_ERROR"
        )
    layout_root, error = _flutter_inspector_layout_tree(
        vm_service_url, isolate_id, group_name, summary_root["valueId"]
    )
    if error:
        return [], error
    if not isinstance(layout_root, dict):
        return [], bridge_error(
            "Flutter inspector did not return a layout tree", "BACKEND_ERROR"
        )
    debug_dump, _ = _flutter_debug_dump_app(vm_service_url, isolate_id)
    elements = _flutter_inspector_elements_from_trees(
        summary_root, layout_root, window, debug_dump, coordinate_space
    )
    root_size = _flutter_node_size(layout_root)
    snapshot = {
        "elements": elements,
        "coordinate_space": coordinate_space,
    }
    if root_size:
        snapshot["root_size"] = {
            "width": _display_number(root_size[0]),
            "height": _display_number(root_size[1]),
        }
    return snapshot, None


def _flutter_inspector_elements(
    vm_service_url, window=None, coordinate_space="app-window-points",
):
    snapshot, error = _flutter_inspector_snapshot(
        vm_service_url, window, coordinate_space
    )
    if error:
        return [], error
    return snapshot["elements"], None


def _element_matches_text(element, text):
    needle = text.lower()
    haystack = " ".join(
        str(element.get(field) or "")
        for field in (
            "text", "label", "description", "value", "role", "subrole"
        )
    ).lower()
    return needle in haystack


def _element_matches_key(element, key):
    return element.get("key") == key


def _filter_elements_by_selector(elements, parsed):
    if "text" in parsed:
        return [
            element for element in elements
            if _element_matches_text(element, parsed["text"])
        ]
    if "key" in parsed:
        return [
            element for element in elements
            if _element_matches_key(element, parsed["key"])
        ]
    return elements


def _macos_inspect(app_name, parsed, vm_service_url=None):
    window, window_error = _macos_get_app_window_info(app_name)
    if window_error:
        return bridge_error(
            f"Failed to get app window: {window_error}", "BACKEND_ERROR"
        )

    stdout, error = _run_osascript_capture(_macos_inspect_script(app_name))
    if error:
        return error

    elements = _parse_macos_inspect_output(stdout, window)
    diagnostics = []
    if vm_service_url:
        flutter_elements, flutter_error = _flutter_inspector_elements(
            vm_service_url, window
        )
        if flutter_error:
            diagnostics.append({
                "source": "flutter-inspector",
                "code": flutter_error.get("code"),
                "error": flutter_error.get("error"),
            })
        else:
            elements.extend(flutter_elements)

    elements = _filter_elements_by_selector(elements, parsed)

    result = {
        "elements": elements,
        "match_count": len(elements),
        "coordinate_space": "app-window-points",
    }
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result


def _ios_inspect(parsed, vm_service_url=None):
    elements, error = _flutter_inspector_elements(
        vm_service_url, coordinate_space="flutter-logical-points"
    )
    if error:
        return error

    elements = _filter_elements_by_selector(elements, parsed)
    return {
        "elements": elements,
        "match_count": len(elements),
        "coordinate_space": "flutter-logical-points",
    }


def _macos_tap_selector(app_name, selector, value, vm_service_url=None):
    inspected = _macos_inspect(app_name, {selector: value}, vm_service_url)
    if "error" in inspected:
        return inspected

    candidates = [
        element for element in inspected["elements"]
        if element.get("rect")
        and element["rect"].get("w", 0) > 0
        and element["rect"].get("h", 0) > 0
        and element.get("enabled") is not False
    ]
    if not candidates:
        return bridge_error(
            "Element not found", "ELEMENT_NOT_FOUND", **{selector: value}
        )

    candidates.sort(
        key=lambda element: (
            0 if element.get("type") == "button" else 1,
            element["rect"]["y"],
            element["rect"]["x"],
        )
    )
    element = candidates[0]
    rect = element["rect"]
    x = rect["x"] + rect["w"] / 2
    y = rect["y"] + rect["h"] / 2
    tapped = _macos_tap_coordinates(app_name, x, y)
    if "error" in tapped:
        return tapped
    return {
        "action": "tap",
        selector: value,
        "element_found": True,
        "x": tapped["x"],
        "y": tapped["y"],
        "coordinate_space": tapped["coordinate_space"],
        "element": element,
    }


def _macos_tap_text(app_name, text, vm_service_url=None):
    return _macos_tap_selector(app_name, "text", text, vm_service_url)


def _macos_tap_key(app_name, key, vm_service_url=None):
    return _macos_tap_selector(app_name, "key", key, vm_service_url)


def _ios_tap_selector(selector, value, vm_service_url=None, device_id=None,
                      device_name=None):
    inspector_snapshot, inspector_error = _flutter_inspector_snapshot(
        vm_service_url, coordinate_space="flutter-logical-points"
    )
    snapshot_source = "live"
    if inspector_error:
        cache_key = (vm_service_url, device_id)
        with _ios_tap_snapshot_lock:
            cached = _ios_tap_snapshot_cache.get(cache_key)
        if (
            not cached
            or time.time() - cached["timestamp"] > 60
            or not cached.get("snapshot")
        ):
            return inspector_error
        inspector_snapshot = cached["snapshot"]
        snapshot_source = "cached-after-inspector-error"
    else:
        cache_key = (vm_service_url, device_id)
        with _ios_tap_snapshot_lock:
            _ios_tap_snapshot_cache[cache_key] = {
                "timestamp": time.time(),
                "snapshot": inspector_snapshot,
            }

    candidates = _filter_elements_by_selector(
        inspector_snapshot["elements"], {selector: value}
    )
    candidates = [
        element for element in candidates
        if element.get("rect")
        and element["rect"].get("w", 0) > 0
        and element["rect"].get("h", 0) > 0
        and element.get("enabled") is not False
    ]
    if not candidates:
        return bridge_error(
            "Element not found", "ELEMENT_NOT_FOUND", **{selector: value}
        )

    candidates.sort(
        key=lambda element: (
            0 if element.get("type") == "button" else 1,
            element["rect"]["y"],
            element["rect"]["x"],
        )
    )
    element = candidates[0]
    root_size = inspector_snapshot.get("root_size")
    if not root_size:
        return bridge_error(
            "Flutter inspector root size is unavailable",
            "BACKEND_ERROR",
            **{selector: value},
        )

    xcrun = shutil.which("xcrun")
    if not xcrun:
        return bridge_error(
            "xcrun is not available on the host PATH",
            "UNSUPPORTED_TARGET",
            **{selector: value},
        )

    window, window_error = _ios_first_simulator_window(device_name=device_name)
    if window_error:
        return bridge_error(
            f"Failed to get Simulator window: {window_error}",
            "BACKEND_ERROR",
            **{selector: value},
        )

    content_match = _ios_host_window_content_match_probe(
        xcrun, device_id=device_id, window=window
    )
    matched_rect = _matched_content_rect(content_match)
    if not matched_rect:
        return bridge_error(
            "Failed to map Flutter coordinates to Simulator window: " +
            str(content_match.get("error") or "no content match"),
            "BACKEND_ERROR",
            **{selector: value},
        )

    center = _rect_center(element["rect"])
    scale_x = float(matched_rect["w"]) / root_size["width"]
    scale_y = float(matched_rect["h"]) / root_size["height"]
    x = float(matched_rect["x"]) + center["x"] * scale_x
    y = float(matched_rect["y"]) + center["y"] * scale_y
    tapped = _ios_tap_coordinates(x, y, device_name=device_name)
    if "error" in tapped:
        return tapped

    return {
        "action": "tap",
        selector: value,
        "element_found": True,
        "x": _display_number(x),
        "y": _display_number(y),
        "coordinate_space": "simulator-window-points",
        "method": "flutter-inspector-sampled-image-match",
        "inspector_snapshot": snapshot_source,
        "match_score_mean_abs_rgb": content_match.get("score_mean_abs_rgb"),
        "content_rect": matched_rect,
        "element": element,
    }


def _macos_wait(app_name, parsed, vm_service_url=None):
    timeout_ms = parsed["timeout_ms"]
    selector = "key" if "key" in parsed else "text"
    selector_value = parsed[selector]
    deadline = time.time() + timeout_ms / 1000
    while True:
        # Check before calling inspect so a slow inspect call that overshoots
        # the deadline still results in a TIMEOUT rather than a silent extra
        # iteration.
        if deadline - time.time() <= 0:
            return bridge_error(
                "Timed out waiting for element",
                "TIMEOUT",
                **{selector: selector_value},
                timeout_ms=timeout_ms,
            )
        inspected = _macos_inspect(
            app_name, {selector: selector_value}, vm_service_url
        )
        if "error" in inspected:
            return inspected
        if inspected["match_count"] > 0:
            return {
                "action": "wait",
                selector: selector_value,
                "element_found": True,
                "match_count": inspected["match_count"],
            }
        remaining = deadline - time.time()
        if remaining <= 0:
            return bridge_error(
                "Timed out waiting for element",
                "TIMEOUT",
                **{selector: selector_value},
                timeout_ms=timeout_ms,
            )
        time.sleep(min(0.25, remaining))


def _ios_wait(parsed, vm_service_url=None):
    timeout_ms = parsed["timeout_ms"]
    selector = "key" if "key" in parsed else "text"
    selector_value = parsed[selector]
    deadline = time.time() + timeout_ms / 1000
    while True:
        if deadline - time.time() <= 0:
            return bridge_error(
                "Timed out waiting for element",
                "TIMEOUT",
                **{selector: selector_value},
                timeout_ms=timeout_ms,
            )
        inspected = _ios_inspect({selector: selector_value}, vm_service_url)
        if "error" in inspected:
            return inspected
        if inspected["match_count"] > 0:
            return {
                "action": "wait",
                selector: selector_value,
                "element_found": True,
                "match_count": inspected["match_count"],
            }
        remaining = deadline - time.time()
        if remaining <= 0:
            return bridge_error(
                "Timed out waiting for element",
                "TIMEOUT",
                **{selector: selector_value},
                timeout_ms=timeout_ms,
            )
        time.sleep(min(0.25, remaining))


def _normalize_device_title(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _ios_first_simulator_window(device_name=None):
    windows = _ios_simulator_window_candidates()
    if "error" in windows:
        return None, windows["error"]
    candidates = windows.get("candidates") or []
    if not candidates:
        return None, "no visible Simulator window found"

    normalized_name = _normalize_device_title(device_name)
    if normalized_name:
        for candidate in candidates:
            title = _normalize_device_title(candidate.get("name"))
            if title and (title == normalized_name or normalized_name in title):
                candidate = dict(candidate)
                candidate["selection"] = "device-name-match"
                return candidate, None
        if len(candidates) > 1:
            return (
                None,
                f"no visible Simulator window matched device '{device_name}'",
            )

    if len(candidates) == 1:
        candidate = dict(candidates[0])
        candidate["selection"] = (
            "single-window-fallback" if normalized_name else "largest-window"
        )
        return candidate, None
    return candidates[0], None


def _ios_simulator_screen_metadata(device_name=None):
    window, error = _ios_first_simulator_window(device_name=device_name)
    if error:
        return {"error": error}
    return {"simulator_window": window}


def _scale_report(from_unit, to_unit, scale_x, scale_y, model=None):
    report = {
        "from": from_unit,
        "to": to_unit,
        "scale_x": _display_number(scale_x),
        "scale_y": _display_number(scale_y),
    }
    if model:
        report["model"] = model
    return report


def _rect_center(rect):
    if not isinstance(rect, dict):
        return None
    try:
        return {
            "x": _display_number(float(rect["x"]) + float(rect["w"]) / 2),
            "y": _display_number(float(rect["y"]) + float(rect["h"]) / 2),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _ios_coordinate_map_element(
    element, logical_to_window, logical_to_matched_window=None
):
    mapped = dict(element)
    center = _rect_center(element.get("rect"))
    if center:
        mapped["center"] = center
    if center and logical_to_window:
        mapped["estimated_simulator_window_center"] = {
            "x": _display_number(center["x"] * logical_to_window["scale_x"]),
            "y": _display_number(center["y"] * logical_to_window["scale_y"]),
        }
    if center and logical_to_matched_window:
        mapped["matched_simulator_window_center_estimate"] = {
            "x": _display_number(
                logical_to_matched_window["offset_x"] +
                center["x"] * logical_to_matched_window["scale_x"]
            ),
            "y": _display_number(
                logical_to_matched_window["offset_y"] +
                center["y"] * logical_to_matched_window["scale_y"]
            ),
        }
    return mapped


def _ios_simulator_accessibility_snapshot(device_name=None):
    window, window_error = _ios_first_simulator_window(
        device_name=device_name
    )
    if window_error:
        return {"error": window_error}
    if not shutil.which("osascript"):
        return {"error": "osascript is not available on the host PATH"}

    stdout, error = _run_osascript_capture(_macos_inspect_script("Simulator"))
    if error:
        return {"error": error.get("error"), "code": error.get("code")}

    raw_lines = [
        line for line in stdout.splitlines()
        if line.strip()
    ]
    bounds = window["bounds"]
    normalized_window = {
        "bounds": (
            bounds["x"],
            bounds["y"],
            bounds["width"],
            bounds["height"],
        )
    }
    elements = _parse_macos_inspect_output(stdout, normalized_window)
    framed_elements = []
    unframed_sample = []
    for element in elements:
        rect = element.get("rect")
        element = dict(element)
        element["coordinate_space"] = "simulator-window-points"
        if rect:
            framed_elements.append(element)
            continue
        if len(unframed_sample) < 20:
            unframed_sample.append(element)

    return {
        "window": window,
        "raw_line_count": len(raw_lines),
        "parsed_element_count": len(elements),
        "element_count": len(framed_elements),
        "elements": framed_elements[:120],
        "unframed_sample": unframed_sample,
        "truncated": len(framed_elements) > 120,
    }


def _run_screencapture_window_probe(window):
    if not window:
        return {"error": "Simulator window is unavailable"}
    if not shutil.which("screencapture"):
        return {"error": "screencapture is not available on the host PATH"}

    fd, tmp_path = tempfile.mkstemp(
        suffix=".png", prefix="simulator_window_screenshot_"
    )
    os.close(fd)
    try:
        result = _run_probe_command(
            _macos_screencapture_command(window["window_id"], tmp_path),
            timeout=12,
        )
        dimensions = _png_dimensions(tmp_path)
        if dimensions:
            result["image"] = dimensions
            try:
                result["image"]["size_bytes"] = os.path.getsize(tmp_path)
            except OSError:
                pass
        result["window"] = window
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ios_coordinate_map(vm_service_url=None, device_id=None, device_name=None):
    xcrun = shutil.which("xcrun")
    result = {
        "available": bool(xcrun),
        "xcrun": xcrun,
        "coordinate_spaces": {
            "inspect": "flutter-logical-points",
            "tap": "simulator-window-points",
            "native_screenshot": "native-device-pixels",
        },
        "notes": [
            "This diagnostic reports measurement data and linear estimates; "
            "it does not enable selector taps.",
            "The full-window Flutter-to-window estimate can be wrong when "
            "the Simulator window includes host chrome, bezels, or letterboxing.",
        ],
    }
    if not xcrun:
        result["error"] = "xcrun is not available on the host PATH"
        return result

    if device_id:
        result["device_id"] = device_id
    if device_name:
        result["device_name"] = device_name

    screen = _ios_simulator_screen_metadata(device_name=device_name)
    result["screen"] = screen
    screenshot = _run_simctl_screenshot_probe(xcrun, device_id=device_id)
    result["native_screenshot"] = screenshot
    window = screen.get("simulator_window") if isinstance(screen, dict) else None
    result["host_window_screenshot"] = _run_screencapture_window_probe(window)
    content_match = _ios_host_window_content_match_probe(
        xcrun, device_id=device_id, window=window
    )
    result["device_content_match"] = content_match
    result["simulator_accessibility"] = (
        _ios_simulator_accessibility_snapshot(device_name=device_name)
    )

    inspector_snapshot = None
    if vm_service_url:
        inspector_snapshot, inspector_error = _flutter_inspector_snapshot(
            vm_service_url, coordinate_space="flutter-logical-points"
        )
        if inspector_error:
            result["flutter_inspector"] = {
                "error": inspector_error.get("error"),
                "code": inspector_error.get("code"),
            }
        else:
            result["flutter_inspector"] = {
                "coordinate_space": inspector_snapshot["coordinate_space"],
                "root_size": inspector_snapshot.get("root_size"),
                "element_count": len(inspector_snapshot["elements"]),
            }
    else:
        result["flutter_inspector"] = {
            "error": "No Flutter VM service is attached",
            "code": "UI_NOT_READY",
        }

    image = screenshot.get("image") if isinstance(screenshot, dict) else None
    mapping = {}
    logical_to_window = None
    logical_to_matched_window = None
    root_size = (
        inspector_snapshot.get("root_size") if inspector_snapshot else None
    )
    if image and root_size:
        root_w = root_size["width"]
        root_h = root_size["height"]
        mapping["flutter_logical_to_native_pixels"] = _scale_report(
            "flutter-logical-points",
            "native-device-pixels",
            image["width"] / root_w,
            image["height"] / root_h,
        )

    if image and window:
        bounds = window["bounds"]
        image_w = image["width"]
        image_h = image["height"]
        win_w = bounds["width"]
        win_h = bounds["height"]
        mapping["window_points_to_native_pixels"] = _scale_report(
            "simulator-window-points",
            "native-device-pixels",
            image_w / win_w,
            image_h / win_h,
        )
        mapping["native_pixels_to_window_points"] = _scale_report(
            "native-device-pixels",
            "simulator-window-points",
            win_w / image_w,
            win_h / image_h,
        )

        if root_size:
            root_w = root_size["width"]
            root_h = root_size["height"]
            logical_to_window = {
                "scale_x": win_w / root_w,
                "scale_y": win_h / root_h,
            }
            mapping["flutter_logical_to_window_points_estimate"] = (
                _scale_report(
                    "flutter-logical-points",
                    "simulator-window-points",
                    logical_to_window["scale_x"],
                    logical_to_window["scale_y"],
                    model="full-window-linear-estimate",
                )
            )
    matched_rect = _matched_content_rect(content_match)
    if matched_rect and root_size:
        root_w = root_size["width"]
        root_h = root_size["height"]
        logical_to_matched_window = {
            "offset_x": float(matched_rect["x"]),
            "offset_y": float(matched_rect["y"]),
            "scale_x": float(matched_rect["w"]) / root_w,
            "scale_y": float(matched_rect["h"]) / root_h,
        }
        mapping["flutter_logical_to_window_points_matched_estimate"] = {
            **_scale_report(
                "flutter-logical-points",
                "simulator-window-points",
                logical_to_matched_window["scale_x"],
                logical_to_matched_window["scale_y"],
                model="sampled-image-match",
            ),
            "offset_x": _display_number(
                logical_to_matched_window["offset_x"]
            ),
            "offset_y": _display_number(
                logical_to_matched_window["offset_y"]
            ),
        }
    result["mapping"] = mapping

    if inspector_snapshot:
        result["elements"] = [
            _ios_coordinate_map_element(
                element, logical_to_window, logical_to_matched_window
            )
            for element in inspector_snapshot["elements"]
            if element.get("rect")
        ]
    return result


def _disable_ios_window_dependent_actions_when_unavailable(status):
    screen = status.get("screen") or {}
    error = screen.get("error")
    if not error:
        return status
    status["actions"]["tap"] = {
        "supported": False,
        "selectors": [],
        "reason": f"Simulator window unavailable: {error}",
    }
    return status


def _disable_ios_host_keyboard_actions_when_unavailable(status):
    tools = status.get("tools") or {}
    if tools.get("osascript"):
        return status
    reason = "Host osascript is unavailable"
    for action_name in ("type", "press", "scroll"):
        status["actions"][action_name] = {
            "supported": False,
            "selectors": [],
            "reason": reason,
        }
    return status


def _disable_ios_content_match_actions_when_unavailable(status):
    tools = status.get("tools") or {}
    if tools.get("screencapture"):
        return status
    tap = dict(status["actions"].get("tap") or {})
    selectors = [
        selector for selector in tap.get("selectors", [])
        if selector == "coordinates"
    ]
    tap["selectors"] = selectors
    tap["selector_reason"] = "Host screencapture is unavailable"
    status["actions"]["tap"] = tap
    return status


def _macos_window_screen_metadata(window):
    x, y, w, h = window["bounds"]
    return {
        "app_window": {
            "id": window["window_id"],
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        }
    }


def _ios_tap_coordinates(x, y, device_name=None):
    window, window_error = _ios_first_simulator_window(
        device_name=device_name
    )
    if window_error:
        return bridge_error(
            f"Failed to get Simulator window: {window_error}",
            "BACKEND_ERROR",
        )

    bounds = window["bounds"]
    win_x = bounds["x"]
    win_y = bounds["y"]
    win_w = bounds["width"]
    win_h = bounds["height"]
    if x >= win_w or y >= win_h:
        return bridge_error(
            "Tap coordinates are outside the Simulator window",
            "INVALID_BODY",
            x=x,
            y=y,
            window=window,
        )

    screen_x = win_x + x
    screen_y = win_y + y
    error = _macos_post_mouse_click(screen_x, screen_y)
    if error:
        return error
    return {
        "action": "tap",
        "x": x,
        "y": y,
        "coordinate_space": "simulator-window-points",
        "screen_x": screen_x,
        "screen_y": screen_y,
        "window": window,
    }


def _macos_post_mouse_click(screen_x, screen_y):
    cg, cf = _load_macos_libs()

    # kCGHIDEventTap, kCGEventLeftMouseDown/Up, kCGMouseButtonLeft
    event_tap = 0
    left_mouse_down = 1
    left_mouse_up = 2
    left_button = 0
    point = _CGPoint(float(screen_x), float(screen_y))

    down = cg.CGEventCreateMouseEvent(
        None, left_mouse_down, point, left_button
    )
    if not down:
        return bridge_error(
            "CoreGraphics failed to create mouse-down event", "BACKEND_ERROR"
        )
    up = None
    try:
        up = cg.CGEventCreateMouseEvent(
            None, left_mouse_up, point, left_button
        )
        if not up:
            return bridge_error(
                "CoreGraphics failed to create mouse-up event",
                "BACKEND_ERROR",
            )
        cg.CGEventPost(event_tap, down)
        time.sleep(0.05)
        cg.CGEventPost(event_tap, up)
    finally:
        cf.CFRelease(down)
        if up:
            cf.CFRelease(up)

    return None


def _macos_tap_coordinates(app_name, x, y):
    window, window_error = _macos_get_app_window_info(app_name)
    if window_error:
        return bridge_error(
            f"Failed to get app window: {window_error}", "BACKEND_ERROR"
        )

    win_x, win_y, win_w, win_h = window["bounds"]
    if x >= win_w or y >= win_h:
        return bridge_error(
            "Tap coordinates are outside the app window",
            "INVALID_BODY",
            x=x,
            y=y,
            window=_macos_window_screen_metadata(window)["app_window"],
        )

    screen_x = win_x + x
    screen_y = win_y + y
    error = _macos_post_mouse_click(screen_x, screen_y)
    if error:
        return error
    return {
        "action": "tap",
        "x": x,
        "y": y,
        "coordinate_space": "app-window-points",
        "screen_x": screen_x,
        "screen_y": screen_y,
        "window": _macos_window_screen_metadata(window)["app_window"],
    }


def _scroll_key_from_parsed(parsed):
    move = parsed.get("move")
    if move == "top":
        return "home"
    if move == "up":
        return "pageup"
    if move == "down":
        return "pagedown"
    return None


def _macos_scroll(app_name, parsed):
    key = _scroll_key_from_parsed(parsed)

    if not key:
        return bridge_error(
            "'move' must be one of top, up, down", "INVALID_BODY", **parsed
        )

    result = _macos_press(app_name, key)
    if "error" in result:
        return result
    return {
        "action": "scroll",
        **parsed,
        "dispatch": "key",
        "key": key,
        "scroll_model": "key-approximation",
    }


def _ios_scroll(parsed):
    key = _scroll_key_from_parsed(parsed)

    if not key:
        return bridge_error(
            "'move' must be one of top, up, down", "INVALID_BODY", **parsed
        )

    result = _ios_press_key(key)
    if "error" in result:
        return result
    return {
        "action": "scroll",
        **parsed,
        "dispatch": "key",
        "key": key,
        "scroll_model": "key-approximation",
        "method": "host-keypress-to-simulator",
    }


def _ui_backend_status(result):
    if "error" not in result:
        return 200
    code = result.get("code")
    if code == "INVALID_BODY":
        return 400
    if code == "UNSUPPORTED_TARGET":
        return 501
    if code == "TIMEOUT":
        return 408
    if code == "ELEMENT_NOT_FOUND":
        return 404
    return 500


def _macos_desktop_dispatch(app_name, action, parsed, vm_service_url=None):
    if action == "press":
        result = _macos_press(app_name, parsed["key"])
        return result, _ui_backend_status(result)
    if action == "type":
        result = _macos_type(app_name, parsed["text"])
        return result, _ui_backend_status(result)
    if action == "tap" and "x" in parsed:
        result = _macos_tap_coordinates(app_name, parsed["x"], parsed["y"])
        return result, _ui_backend_status(result)
    if action == "tap" and "text" in parsed:
        result = _macos_tap_text(app_name, parsed["text"], vm_service_url)
        return result, _ui_backend_status(result)
    if action == "tap" and "key" in parsed:
        result = _macos_tap_key(app_name, parsed["key"], vm_service_url)
        return result, _ui_backend_status(result)
    if action == "scroll":
        result = _macos_scroll(app_name, parsed)
        return result, _ui_backend_status(result)
    if action == "inspect":
        result = _macos_inspect(app_name, parsed, vm_service_url)
        return result, _ui_backend_status(result)
    if action == "wait":
        result = _macos_wait(app_name, parsed, vm_service_url)
        return result, _ui_backend_status(result)
    return (
        bridge_error(
            f"Action '{action}' not implemented for macOS desktop backend",
            "UNSUPPORTED_TARGET",
            **parsed,
        ),
        501,
    )


def _ios_simulator_dispatch(
    action, parsed, vm_service_url=None, device_name=None, device_id=None
):
    if action == "tap" and "x" in parsed:
        result = _ios_tap_coordinates(
            parsed["x"], parsed["y"], device_name=device_name
        )
        return result, _ui_backend_status(result)
    if action == "tap" and "text" in parsed:
        result = _ios_tap_selector(
            "text",
            parsed["text"],
            vm_service_url=vm_service_url,
            device_id=device_id,
            device_name=device_name,
        )
        return result, _ui_backend_status(result)
    if action == "tap" and "key" in parsed:
        result = _ios_tap_selector(
            "key",
            parsed["key"],
            vm_service_url=vm_service_url,
            device_id=device_id,
            device_name=device_name,
        )
        return result, _ui_backend_status(result)
    if action == "type":
        result = _ios_type_text(parsed["text"])
        return result, _ui_backend_status(result)
    if action == "press":
        result = _ios_press_key(parsed["key"])
        return result, _ui_backend_status(result)
    if action == "scroll":
        result = _ios_scroll(parsed)
        return result, _ui_backend_status(result)
    if action == "inspect":
        result = _ios_inspect(parsed, vm_service_url)
        return result, _ui_backend_status(result)
    if action == "wait":
        result = _ios_wait(parsed, vm_service_url)
        return result, _ui_backend_status(result)
    return (
        bridge_error(
            f"Action '{action}' not implemented for iOS Simulator backend",
            "UNSUPPORTED_TARGET",
            **parsed,
        ),
        501,
    )


def _macos_get_process_id(app_name):
    script = (
        f'tell application "System Events"\n'
        f'set frontmost of process '
        f'"{_escape_applescript_string(app_name)}" to true\n'
        f'return unix id of process '
        f'"{_escape_applescript_string(app_name)}"\n'
        f'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None, result.stderr.strip()
        return int(result.stdout.strip()), None
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        return None, str(e)


def _select_macos_app_window(windows, pid):
    for window in windows:
        if window.get("pid") != pid:
            continue
        if window.get("layer") not in (None, 0):
            continue
        if window.get("onscreen") is False:
            continue
        if window.get("alpha", 1) <= 0:
            continue

        bounds = window.get("bounds")
        window_id = window.get("window_id")
        if not bounds or window_id is None:
            continue
        x, y, w, h = bounds
        if w <= 0 or h <= 0:
            continue
        return {
            "window_id": int(window_id),
            "bounds": (int(x), int(y), int(w), int(h)),
        }
    return None


def _macos_coregraphics_windows():
    cg, cf = _load_macos_libs()

    encoding_utf8 = 0x08000100
    number_double = 13

    def cf_string(text):
        return cf.CFStringCreateWithCString(
            None, text.encode("utf-8"), encoding_utf8
        )

    def dict_get(dictionary, key_text):
        key = cf_string(key_text)
        try:
            return cf.CFDictionaryGetValue(dictionary, key)
        finally:
            if key:
                cf.CFRelease(key)

    def number_value(ref):
        if not ref:
            return None
        value = ctypes.c_double()
        if not cf.CFNumberGetValue(
            ref, number_double, ctypes.byref(value)
        ):
            return None
        return value.value

    def string_value(ref):
        if not ref:
            return None
        buffer = ctypes.create_string_buffer(1024)
        if not cf.CFStringGetCString(
            ref, buffer, len(buffer), encoding_utf8
        ):
            return None
        return buffer.value.decode("utf-8", errors="replace")

    def bool_value(ref):
        if not ref:
            return None
        return bool(cf.CFBooleanGetValue(ref))

    def bounds_value(ref):
        if not ref:
            return None
        x = number_value(dict_get(ref, "X"))
        y = number_value(dict_get(ref, "Y"))
        w = number_value(dict_get(ref, "Width"))
        h = number_value(dict_get(ref, "Height"))
        if None in (x, y, w, h):
            return None
        return (x, y, w, h)

    # kCGWindowListOptionOnScreenOnly
    window_array = cg.CGWindowListCopyWindowInfo(1, 0)
    if not window_array:
        return []

    try:
        windows = []
        for idx in range(cf.CFArrayGetCount(window_array)):
            info = cf.CFArrayGetValueAtIndex(window_array, idx)
            windows.append({
                "window_id": number_value(
                    dict_get(info, "kCGWindowNumber")
                ),
                "pid": number_value(dict_get(info, "kCGWindowOwnerPID")),
                "owner_name": string_value(
                    dict_get(info, "kCGWindowOwnerName")
                ),
                "name": string_value(dict_get(info, "kCGWindowName")),
                "layer": number_value(dict_get(info, "kCGWindowLayer")),
                "alpha": number_value(dict_get(info, "kCGWindowAlpha")),
                "onscreen": bool_value(
                    dict_get(info, "kCGWindowIsOnscreen")
                ),
                "bounds": bounds_value(dict_get(info, "kCGWindowBounds")),
            })
        return windows
    finally:
        cf.CFRelease(window_array)


def _macos_get_app_window_info(app_name):
    pid, error = _macos_get_process_id(app_name)
    if error:
        return None, f"failed to get app process id: {error}"
    try:
        window = _select_macos_app_window(_macos_coregraphics_windows(), pid)
    except OSError as e:
        return None, f"failed to query CoreGraphics windows: {e}"
    if not window:
        return None, f"no visible app window found for process id {pid}"
    return window, None


def _macos_screencapture_command(window_id, output_path):
    return ["screencapture", "-x", f"-l{int(window_id)}", output_path]


def dispatch_ui_action(state, action, parsed, automation=None):
    automation = automation or state.ui_automation_status()
    backend = automation["backend"]
    if backend == "macos-desktop":
        return _macos_desktop_dispatch(
            state.app_name, action, parsed, state.vm_service_url
        )
    if backend == "ios-simulator":
        device = (automation or {}).get("device") or {}
        return _ios_simulator_dispatch(
            action,
            parsed,
            state.vm_service_url,
            device_name=device.get("name"),
            device_id=state.device_id,
        )
    return (
        bridge_error(
            f"UI automation not implemented for backend '{backend}'",
            "UNSUPPORTED_TARGET",
            action=action,
            **parsed,
        ),
        501,
    )


def bridge_error(message, code, **extra):
    data = {"error": message, "code": code}
    data.update(extra)
    return data


def find_device_metadata(device_id, devices):
    if not device_id:
        return None
    for device in devices or []:
        if not isinstance(device, dict):
            continue
        if device.get("id") == device_id or device.get("name") == device_id:
            return device
    return None


def classify_device(device_id, metadata=None):
    metadata = metadata if isinstance(metadata, dict) else {}
    device_id_text = (device_id or "").lower()
    name = str(metadata.get("name", "")).lower()
    platform = str(
        metadata.get("targetPlatform")
        or metadata.get("platform")
        or metadata.get("platformType")
        or ""
    ).lower()
    category = str(metadata.get("category", "")).lower()
    sdk = str(metadata.get("sdk", "")).lower()
    is_emulator = bool(metadata.get("emulator"))
    combined = " ".join([device_id_text, name, platform, category, sdk])

    target_platform = "unknown"
    device_kind = "unknown"
    backend = "unsupported"

    if "ios" in combined:
        target_platform = "ios"
        if is_emulator or "simulator" in combined or device_id_text == "ios":
            device_kind = "simulator"
            backend = "ios-simulator"
        else:
            device_kind = "physical"
    elif (
        "darwin" in platform
        or "macos" in combined
        or device_id_text == "macos"
    ):
        target_platform = "macos"
        device_kind = "desktop"
        backend = "macos-desktop"
    elif "android" in combined:
        target_platform = "android"
        device_kind = "emulator" if is_emulator else "device"
    elif "linux" in combined:
        target_platform = "linux"
        device_kind = "desktop"
    elif "windows" in combined:
        target_platform = "windows"
        device_kind = "desktop"

    return {
        "backend": backend,
        "target_platform": target_platform,
        "device_kind": device_kind,
        "device": metadata or None,
    }


def probe_backend_tools(backend):
    if backend == "ios-simulator":
        return {
            "xcrun": bool(shutil.which("xcrun")),
            "osascript": bool(shutil.which("osascript")),
            "screencapture": bool(shutil.which("screencapture")),
        }
    if backend == "macos-desktop":
        return {
            "osascript": bool(shutil.which("osascript")),
        }
    return {}


def unsupported_actions(reason):
    return {
        action: {"supported": False, "selectors": [], "reason": reason}
        for action in UI_ACTIONS
    }


def _macos_desktop_action_capabilities():
    return {
        "tap": {
            "supported": True,
            "selectors": ["coordinates", "text", "key"],
            "coordinate_space": "app-window-points",
        },
        "type": {"supported": True, "selectors": []},
        "press": {"supported": True, "selectors": []},
        "scroll": {
            "supported": True,
            "selectors": [],
            "moves": ["top", "up", "down"],
        },
        "inspect": {
            "supported": True,
            "selectors": ["text", "key"],
        },
        "wait": {
            "supported": True,
            "selectors": ["text", "key"],
        },
    }


def _macos_desktop_capabilities():
    return {
        "screenshot": {
            "supported": True,
            "method": "screencapture-window",
            "scope": "app-window-only",
            "requires": [
                "visible Flutter app window",
                "macOS Screen Recording permission",
            ],
        },
        "ui_actions": _macos_desktop_action_capabilities(),
    }


def _mobile_capabilities():
    return {
        "screenshot": {
            "supported": True,
            "method": "flutter screenshot",
            "scope": "device-screen",
            "requires": ["Flutter target available"],
        },
        "ui_actions": unsupported_actions("No verified backend"),
    }


def _unsupported_capabilities():
    reason = (
        "No verified screenshot backend for this target; macOS desktop "
        "uses app-window capture and mobile targets use flutter screenshot"
    )
    return {
        "screenshot": {
            "supported": False,
            "method": None,
            "scope": None,
            "reason": reason,
        },
        "ui_actions": unsupported_actions("No verified backend"),
    }


def _target_capabilities(target):
    if target["backend"] == "macos-desktop":
        return _macos_desktop_capabilities()
    if target["target_platform"] in {"ios", "android"}:
        return _mobile_capabilities()
    return _unsupported_capabilities()


def _backend_action_capabilities(backend):
    if backend == "macos-desktop":
        return _macos_desktop_capabilities()["ui_actions"]
    if backend == "ios-simulator":
        actions = unsupported_actions("No verified input backend")
        actions["tap"] = {
            "supported": True,
            "selectors": ["coordinates", "text", "key"],
            "coordinate_space": "simulator-window-points",
            "method": "coregraphics-simulator-window",
            "selector_method": "flutter-inspector-sampled-image-match",
        }
        actions["type"] = {
            "supported": True,
            "selectors": [],
            "method": "host-keystroke-to-simulator",
            "requires": ["focused text field"],
        }
        actions["press"] = {
            "supported": True,
            "selectors": [],
            "method": "host-keypress-to-simulator",
        }
        actions["scroll"] = {
            "supported": True,
            "selectors": [],
            "moves": ["top", "up", "down"],
            "method": "host-keypress-to-simulator",
            "scroll_model": "key-approximation",
        }
        actions["inspect"] = {
            "supported": True,
            "selectors": ["text", "key"],
            "coordinate_space": "flutter-logical-points",
            "method": "flutter-inspector",
        }
        actions["wait"] = {
            "supported": True,
            "selectors": ["text", "key"],
            "method": "flutter-inspector",
        }
        return actions
    return unsupported_actions("No verified backend")


def backend_permissions(backend):
    if backend == "macos-desktop":
        return {
            "accessibility": "unknown",
        }
    if backend == "ios-simulator":
        return {
            "accessibility": "unknown",
        }
    return {}


def _truncate_text(value, limit=6000):
    text = value if isinstance(value, str) else str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _run_probe_command(command, timeout=8):
    started = time.time()
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "ok": result.returncode == 0,
            "stdout": _truncate_text(result.stdout),
            "stderr": _truncate_text(result.stderr),
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "command": command,
            "returncode": None,
            "ok": False,
            "stdout": _truncate_text(e.stdout or ""),
            "stderr": _truncate_text(e.stderr or ""),
            "error": "command timed out",
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except OSError as e:
        return {
            "command": command,
            "returncode": None,
            "ok": False,
            "stdout": "",
            "stderr": "",
            "error": str(e),
            "elapsed_ms": int((time.time() - started) * 1000),
        }


def _probe_output(*results):
    return "\n".join(
        f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        for result in results
        if isinstance(result, dict)
    ).lower()


def _contains_word(text, word):
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _simctl_input_conclusions(commands):
    help_text = _probe_output(
        *(
            result
            for name, result in commands.items()
            if name.startswith("simctl")
        )
    )
    has_io = _contains_word(help_text, "io")
    has_ui = _contains_word(help_text, "ui")
    mentions_tap = (
        _contains_word(help_text, "tap")
        or _contains_word(help_text, "gesture")
        or _contains_word(help_text, "pointer")
        or re.search(r"\btouch\b(?!\s*id\b)", help_text) is not None
    )
    mentions_keyboard = any(
        _contains_word(help_text, word)
        for word in ("keyboard", "typetext", "type_text", "textinput")
    )

    coordinate_tap_viable = bool(mentions_tap)
    text_input_viable = bool(mentions_keyboard)

    coordinate_reason = (
        "simctl help mentions a touch/tap/gesture primitive; verify command "
        "syntax and coordinate semantics before enabling bridge input"
        if coordinate_tap_viable
        else "simctl help did not expose a coordinate tap/touch primitive"
    )
    text_reason = (
        "simctl help mentions keyboard/text input; verify command syntax "
        "before enabling bridge typing"
        if text_input_viable
        else "simctl help did not expose a direct text-entry primitive"
    )

    return {
        "features": {
            "simctl_io_subcommand": has_io,
            "simctl_ui_subcommand": has_ui,
            "mentions_touch_or_tap": mentions_tap,
            "mentions_keyboard_or_text": mentions_keyboard,
        },
        "input_backend": {
            "coordinate_tap": {
                "viable": coordinate_tap_viable,
                "reason": coordinate_reason,
            },
            "text_entry": {
                "viable": text_input_viable,
                "reason": text_reason,
            },
        },
    }


def _png_dimensions(path):
    try:
        with open(path, "rb") as f:
            header = f.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return {
        "width": int.from_bytes(header[16:20], "big"),
        "height": int.from_bytes(header[20:24], "big"),
    }


def _png_paeth_predictor(left, up, up_left):
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def _png_decode_rgb(path, max_pixels=5_000_000):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, f"failed to read PNG: {e}"

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None, "not a PNG file"

    offset = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, \
                interlace = struct.unpack(">IIBBBBB", chunk_data)
            if compression != 0 or filter_method != 0 or interlace != 0:
                return None, "unsupported PNG compression/filter/interlace"
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not width or not height:
        return None, "PNG is missing IHDR"
    if width * height > max_pixels:
        return None, "PNG is too large to decode for matching"
    if bit_depth != 8 or color_type not in (0, 2, 4, 6):
        return None, "unsupported PNG color format"

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        return None, f"failed to decompress PNG: {e}"

    expected = (stride + 1) * height
    if len(raw) < expected:
        return None, "PNG image data is truncated"

    previous = bytearray(stride)
    rows = []
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scanline = bytearray(raw[pos:pos + stride])
        pos += stride
        recon = bytearray(stride)
        for i, value in enumerate(scanline):
            left = recon[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 0:
                recon[i] = value
            elif filter_type == 1:
                recon[i] = (value + left) & 0xFF
            elif filter_type == 2:
                recon[i] = (value + up) & 0xFF
            elif filter_type == 3:
                recon[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                recon[i] = (
                    value + _png_paeth_predictor(left, up, up_left)
                ) & 0xFF
            else:
                return None, f"unsupported PNG filter type {filter_type}"
        rows.append(recon)
        previous = recon

    rgb = bytearray(width * height * 3)
    out = 0
    for row in rows:
        for x in range(width):
            i = x * channels
            if color_type == 0:
                r = g = b = row[i]
            elif color_type == 2:
                r, g, b = row[i], row[i + 1], row[i + 2]
            elif color_type == 4:
                r = g = b = row[i]
            else:
                r, g, b = row[i], row[i + 1], row[i + 2]
            rgb[out:out + 3] = bytes((r, g, b))
            out += 3

    return {"width": width, "height": height, "pixels": bytes(rgb)}, None


def _rgb_at(image, x, y):
    x = min(max(int(x), 0), image["width"] - 1)
    y = min(max(int(y), 0), image["height"] - 1)
    i = (y * image["width"] + x) * 3
    pixels = image["pixels"]
    return pixels[i], pixels[i + 1], pixels[i + 2]


def _sampled_crop_score(native, host, crop, columns=12, rows=24):
    diff = 0
    samples = 0
    for row in range(rows):
        v = (row + 0.5) / rows
        native_y = int(v * native["height"])
        host_y = crop["y"] + int(v * crop["height"])
        for column in range(columns):
            u = (column + 0.5) / columns
            native_x = int(u * native["width"])
            host_x = crop["x"] + int(u * crop["width"])
            nr, ng, nb = _rgb_at(native, native_x, native_y)
            hr, hg, hb = _rgb_at(host, host_x, host_y)
            diff += abs(nr - hr) + abs(ng - hg) + abs(nb - hb)
            samples += 3
    return diff / samples if samples else math.inf


def _ios_content_match_search(native, host, region, samples=(10, 18),
                              step=8, height_step=12,
                              focus=None):
    aspect = native["width"] / native["height"]
    region_x = int(round(region["x"]))
    region_y = int(round(region["y"]))
    region_w = int(round(region["width"]))
    region_h = int(round(region["height"]))
    min_h = min(region_h, max(20, int(region_h * 0.70)))
    max_h = region_h

    if focus:
        h_start = max(min_h, focus["height"] - height_step)
        h_end = min(max_h, focus["height"] + height_step)
        x_start = max(0, focus["local_x"] - step * 2)
        x_end = min(region_w, focus["local_x"] + step * 2)
        y_start = max(0, focus["local_y"] - step * 2)
        y_end = min(region_h, focus["local_y"] + step * 2)
    else:
        h_start, h_end = min_h, max_h
        x_start, x_end = 0, region_w
        y_start, y_end = 0, region_h

    best = None
    columns, rows = samples
    heights = list(range(h_start, h_end + 1, max(1, height_step)))
    if h_end not in heights:
        heights.append(h_end)
    for height in heights:
        width = int(round(height * aspect))
        if width <= 0 or width > region_w:
            continue
        max_local_x = region_w - width
        max_local_y = region_h - height
        for local_y in range(y_start, min(y_end, max_local_y) + 1, step):
            for local_x in range(x_start, min(x_end, max_local_x) + 1, step):
                crop = {
                    "x": region_x + local_x,
                    "y": region_y + local_y,
                    "width": width,
                    "height": height,
                }
                score = _sampled_crop_score(
                    native, host, crop, columns=columns, rows=rows
                )
                if not best or score < best["score"]:
                    best = {
                        "score": score,
                        "crop": crop,
                        "local_x": local_x,
                        "local_y": local_y,
                        "width": width,
                        "height": height,
                    }
    return best


def _estimate_ios_host_window_content_match(native, host, window):
    bounds = window.get("bounds") or {}
    try:
        window_w = int(round(float(bounds["width"])))
        window_h = int(round(float(bounds["height"])))
    except (KeyError, TypeError, ValueError):
        return {"error": "Simulator window bounds are unavailable"}

    if window_w <= 0 or window_h <= 0:
        return {"error": "Simulator window bounds are invalid"}

    margin_left = max(0, int(round((host["width"] - window_w) / 2)))
    margin_top = max(0, int(round((host["height"] - window_h) / 2)))
    region = {
        "x": margin_left,
        "y": margin_top,
        "width": min(window_w, host["width"] - margin_left),
        "height": min(window_h, host["height"] - margin_top),
    }
    if region["width"] <= 0 or region["height"] <= 0:
        return {"error": "host window screenshot is smaller than search region"}

    coarse = _ios_content_match_search(
        native, host, region, samples=(8, 14), step=8, height_step=16
    )
    if not coarse:
        return {"error": "no candidate content rectangle could be searched"}
    refined = _ios_content_match_search(
        native,
        host,
        region,
        samples=(14, 24),
        step=2,
        height_step=2,
        focus=coarse,
    ) or coarse

    crop = refined["crop"]
    local_x = crop["x"] - margin_left
    local_y = crop["y"] - margin_top
    return {
        "available": True,
        "method": "sampled-normalized-rgb-png-match",
        "score_mean_abs_rgb": _display_number(refined["score"]),
        "score_note": "Lower is better; 0 means exact sampled RGB match.",
        "native_image": {
            "width": native["width"],
            "height": native["height"],
        },
        "host_window_image": {
            "width": host["width"],
            "height": host["height"],
        },
        "capture_margin_estimate": {
            "left": margin_left,
            "top": margin_top,
            "right": max(0, host["width"] - margin_left - window_w),
            "bottom": max(0, host["height"] - margin_top - window_h),
            "coordinate_space": "host-window-screenshot-pixels",
        },
        "search_region": {
            **region,
            "coordinate_space": "host-window-screenshot-pixels",
        },
        "best_match": {
            "screenshot_rect": {
                "x": crop["x"],
                "y": crop["y"],
                "w": crop["width"],
                "h": crop["height"],
                "coordinate_space": "host-window-screenshot-pixels",
            },
            "simulator_window_rect_estimate": {
                "x": _display_number(local_x),
                "y": _display_number(local_y),
                "w": crop["width"],
                "h": crop["height"],
                "coordinate_space": "simulator-window-points",
            },
            "native_pixels_to_simulator_window_points": _scale_report(
                "native-device-pixels",
                "simulator-window-points",
                crop["width"] / native["width"],
                crop["height"] / native["height"],
                model="sampled-image-match",
            ),
        },
    }


def _matched_content_rect(content_match):
    if not isinstance(content_match, dict):
        return None
    best = content_match.get("best_match")
    if not isinstance(best, dict):
        return None
    rect = best.get("simulator_window_rect_estimate")
    return rect if isinstance(rect, dict) else None


def _ios_host_window_content_match_probe(xcrun, device_id, window):
    if not window:
        return {"error": "Simulator window is unavailable"}
    if not shutil.which("screencapture"):
        return {"error": "screencapture is not available on the host PATH"}

    native_fd, native_path = tempfile.mkstemp(
        suffix=".png", prefix="simctl_match_screenshot_"
    )
    host_fd, host_path = tempfile.mkstemp(
        suffix=".png", prefix="simulator_window_match_"
    )
    os.close(native_fd)
    os.close(host_fd)
    target_device = device_id or "booted"
    try:
        native_command = [
            xcrun,
            "simctl",
            "io",
            target_device,
            "screenshot",
            "--type=png",
            native_path,
        ]
        host_command = _macos_screencapture_command(
            window["window_id"], host_path
        )
        native_result = _run_probe_command(native_command, timeout=12)
        host_result = _run_probe_command(host_command, timeout=12)
        result = {
            "native_screenshot_command": native_result,
            "host_window_screenshot_command": host_result,
        }
        if not native_result.get("ok"):
            result["error"] = "native simulator screenshot failed"
            return result
        if not host_result.get("ok"):
            result["error"] = "host window screenshot failed"
            return result

        native, native_error = _png_decode_rgb(native_path)
        host, host_error = _png_decode_rgb(host_path)
        if native_error or host_error:
            result["error"] = native_error or host_error
            return result
        result.update(_estimate_ios_host_window_content_match(
            native, host, window
        ))
        return result
    finally:
        for path in (native_path, host_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _run_simctl_screenshot_probe(xcrun, device_id=None):
    fd, tmp_path = tempfile.mkstemp(
        suffix=".png", prefix="simctl_probe_screenshot_"
    )
    os.close(fd)
    target_device = device_id or "booted"
    try:
        result = _run_probe_command(
            [
                xcrun,
                "simctl",
                "io",
                target_device,
                "screenshot",
                "--type=png",
                tmp_path,
            ],
            timeout=12,
        )
        dimensions = _png_dimensions(tmp_path)
        if dimensions:
            result["image"] = dimensions
            try:
                result["image"]["size_bytes"] = os.path.getsize(tmp_path)
            except OSError:
                pass
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _ios_simulator_window_candidates():
    try:
        windows = _macos_coregraphics_windows()
    except OSError as e:
        return {"error": f"failed to query CoreGraphics windows: {e}"}

    candidates = []
    for window in windows:
        owner = str(window.get("owner_name") or "")
        title = str(window.get("name") or "")
        haystack = f"{owner} {title}".lower()
        if "simulator" not in haystack:
            continue
        if window.get("layer") not in (None, 0):
            continue
        if window.get("onscreen") is False:
            continue
        if window.get("alpha", 1) <= 0:
            continue
        bounds = window.get("bounds")
        if not bounds:
            continue
        x, y, width, height = bounds
        if width <= 0 or height <= 0:
            continue
        candidates.append({
            "window_id": window.get("window_id"),
            "pid": window.get("pid"),
            "owner_name": owner,
            "name": title,
            "bounds": {
                "x": _display_number(x),
                "y": _display_number(y),
                "width": _display_number(width),
                "height": _display_number(height),
            },
        })
    candidates.sort(
        key=lambda window: (
            -window["bounds"]["width"] * window["bounds"]["height"],
            window["bounds"]["y"],
            window["bounds"]["x"],
        )
    )
    return {"candidates": candidates[:10], "count": len(candidates)}


def ios_simulator_probe(device_id=None):
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return {
            "available": False,
            "xcrun": None,
            "error": "xcrun is not available on the host PATH",
            "commands": {},
            "features": {
                "simctl_io_subcommand": False,
                "simctl_ui_subcommand": False,
                "mentions_touch_or_tap": False,
                "mentions_keyboard_or_text": False,
            },
            "input_backend": {
                "coordinate_tap": {
                    "viable": False,
                    "reason": "xcrun is unavailable",
                },
                "text_entry": {
                    "viable": False,
                    "reason": "xcrun is unavailable",
                },
            },
        }

    commands = {
        "simctl_help": _run_probe_command([xcrun, "simctl", "help"]),
        "simctl_help_io": _run_probe_command(
            [xcrun, "simctl", "help", "io"]
        ),
        "simctl_io_help": _run_probe_command(
            [xcrun, "simctl", "io", "help"]
        ),
        "simctl_help_ui": _run_probe_command(
            [xcrun, "simctl", "help", "ui"]
        ),
        "simctl_ui_help": _run_probe_command(
            [xcrun, "simctl", "ui", "help"]
        ),
        "booted_devices": _run_probe_command(
            [xcrun, "simctl", "list", "devices", "booted", "--json"],
            timeout=12,
        ),
        "selected_screenshot": _run_simctl_screenshot_probe(
            xcrun, device_id=device_id
        ),
    }
    conclusions = _simctl_input_conclusions(commands)
    return {
        "available": True,
        "xcrun": xcrun,
        "device_id": device_id,
        "commands": commands,
        "simulator_windows": _ios_simulator_window_candidates(),
        **conclusions,
    }


def build_screenshot_status(bridge_status, has_process, device_id, target):
    if not device_id:
        return {
            "supported": None,
            "available": False,
            "method": None,
            "scope": None,
            "supported_targets": {
                "macos": _macos_desktop_capabilities()["screenshot"],
                "ios": _mobile_capabilities()["screenshot"],
                "android": _mobile_capabilities()["screenshot"],
            },
            "reason": (
                "No target device selected; launch or attach to a device "
                "first. Screenshot support depends on the selected target."
            ),
        }

    status = dict(_target_capabilities(target)["screenshot"])
    status["available"] = bool(has_process and status["supported"])
    if status["supported"] and not has_process:
        status["reason"] = "No Flutter app process is running under the bridge"
    return status


def build_ui_automation_status(
    bridge_status, has_process, has_vm_service, device_id, target, tools,
    device_error=None,
):
    backend = target["backend"]
    missing = []
    if device_error and not target.get("device"):
        missing.append(f"device metadata unavailable: {device_error}")
    if backend == "ios-simulator" and not tools.get("xcrun"):
        missing.append("xcrun")
    if backend == "macos-desktop" and not tools.get("osascript"):
        missing.append("osascript")

    if not has_process:
        reason = "No Flutter app process is running under the bridge"
        ready = False
    elif not has_vm_service or bridge_status == "launching":
        reason = "Flutter process exists, but UI automation is not ready yet"
        ready = False
    elif backend == "unsupported":
        reason = "UI automation supports iOS Simulator and macOS desktop only"
        ready = False
    elif missing:
        reason = "Required host UI automation tool is unavailable"
        ready = False
    else:
        # ready=True means infrastructure is in place (process running, tools
        # available, backend classified). It does NOT guarantee every action is
        # implemented. For backends such as ios-simulator, all per-action
        # capabilities may still report supported=False — agents must check
        # actions individually. Using ready=True here (rather than False)
        # ensures ui_action_unavailable_error returns the informative
        # UNSUPPORTED_TARGET error code instead of the misleading UI_NOT_READY.
        reason = "UI automation backend exists, but action support is not verified yet"
        ready = True

    status = {
        "backend": backend,
        "target_platform": target["target_platform"],
        "device_kind": target["device_kind"],
        "ready": ready,
        "coordinate_space": (
            "app-window-points"
            if ready and backend == "macos-desktop"
            else "simulator-window-points"
            if ready and backend == "ios-simulator"
            else None
        ),
        "screen": None,
        "actions": (
            _backend_action_capabilities(backend)
            if ready
            else unsupported_actions(reason)
        ),
        "tools": tools,
        "permissions": backend_permissions(backend),
        "missing": missing,
    }

    if device_id:
        status["device_id"] = device_id
    if target.get("device"):
        status["device"] = target["device"]
    return status


def validate_text_value(value, field="text"):
    if not isinstance(value, str) or value == "":
        return f"'{field}' must be a non-empty string"
    if "\x00" in value:
        return f"'{field}' must not contain null bytes"
    for ch in value:
        code = ord(ch)
        if code < 32 and ch not in ("\n", "\r", "\t"):
            return f"'{field}' contains unsupported control characters"
    return None


def numeric_value(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"'{field}' must be a number"
    if not math.isfinite(value):
        return None, f"'{field}' must be a finite number"
    return value, None


def validate_selector_body(body, *, selector_required=False):
    if not isinstance(body, dict):
        return None, bridge_error(
            "Request body must be a JSON object", "INVALID_BODY"
        )

    text_present = "text" in body
    key_present = "key" in body
    if text_present and key_present:
        return None, bridge_error(
            "'text' and 'key' selectors are mutually exclusive",
            "INVALID_BODY",
        )
    if selector_required and not (text_present or key_present):
        return None, bridge_error(
            "Provide either 'text' or 'key'", "INVALID_BODY"
        )
    if text_present:
        err = validate_text_value(body.get("text"), "text")
        if err:
            return None, bridge_error(err, "INVALID_BODY")
        return {"text": body["text"]}, None
    if key_present:
        err = validate_text_value(body.get("key"), "key")
        if err:
            return None, bridge_error(err, "INVALID_BODY")
        return {"key": body["key"]}, None
    return {}, None


def validate_press_key(value):
    err = validate_text_value(value, "key")
    if err:
        return None, bridge_error(err, "INVALID_BODY")

    key = value.strip().lower()
    if not key:
        return None, bridge_error(
            "'key' must be a non-empty string", "INVALID_BODY"
        )
    parts = [part.strip() for part in key.split("+")]
    if len(parts) == 1:
        part = parts[0]
        if part in BASE_KEYS or (len(part) == 1 and part.isalnum()):
            return part, None
        return None, bridge_error(f"Unknown key: {value}", "UNKNOWN_KEY")

    if any(part == "" for part in parts):
        return None, bridge_error(f"Unknown key: {value}", "UNKNOWN_KEY")
    if not all(part in MODIFIER_KEYS for part in parts[:-1]):
        return None, bridge_error(f"Unknown key: {value}", "UNKNOWN_KEY")
    last = parts[-1]
    if last in MODIFIER_KEYS:
        return None, bridge_error(f"Unknown key: {value}", "UNKNOWN_KEY")
    if last in BASE_KEYS or (len(last) == 1 and last.isalnum()):
        return "+".join(parts), None
    return None, bridge_error(f"Unknown key: {value}", "UNKNOWN_KEY")


def validate_ui_action(action, body):
    body = body or {}
    if not isinstance(body, dict):
        return None, bridge_error(
            "Request body must be a JSON object", "INVALID_BODY"
        )

    if action == "tap":
        has_x = "x" in body
        has_y = "y" in body
        has_coordinates = has_x or has_y
        has_selector = "text" in body or "key" in body
        if has_coordinates and has_selector:
            return None, bridge_error(
                "Coordinates are mutually exclusive with text/key selectors",
                "INVALID_BODY",
            )
        if has_coordinates:
            if not has_x or not has_y:
                return None, bridge_error(
                    "Both 'x' and 'y' are required for coordinate taps",
                    "INVALID_BODY",
                )
            x, err = numeric_value(body["x"], "x")
            if err:
                return None, bridge_error(err, "INVALID_BODY")
            y, err = numeric_value(body["y"], "y")
            if err:
                return None, bridge_error(err, "INVALID_BODY")
            if x < 0 or y < 0:
                return None, bridge_error(
                    "'x' and 'y' must be non-negative", "INVALID_BODY"
                )
            return {"x": x, "y": y}, None
        return validate_selector_body(body, selector_required=True)

    if action == "type":
        err = validate_text_value(body.get("text"), "text")
        if err:
            return None, bridge_error(err, "INVALID_BODY")
        return {"text": body["text"]}, None

    if action == "press":
        return_key, err = validate_press_key(body.get("key"))
        if err:
            return None, err
        return {"key": return_key}, None

    if action == "scroll":
        move = body.get("move")
        if move is None:
            return None, bridge_error(
                "Provide 'move'", "INVALID_BODY"
            )
        if set(body) != {"move"}:
            return None, bridge_error(
                "Only 'move' is accepted for scroll", "INVALID_BODY"
            )
        if move not in ("top", "up", "down"):
            return None, bridge_error(
                "'move' must be one of top, up, down", "INVALID_BODY"
            )
        return {"move": move}, None

    if action == "inspect":
        return validate_selector_body(body, selector_required=False)

    if action == "wait":
        parsed, err = validate_selector_body(body, selector_required=True)
        if err:
            return None, err
        timeout = body.get("timeout_ms", 5000)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or timeout < 1
            or timeout > 60000
        ):
            return None, bridge_error(
                "'timeout_ms' must be an integer from 1 to 60000",
                "INVALID_BODY",
            )
        parsed["timeout_ms"] = timeout
        return parsed, None

    return None, bridge_error(f"Unknown UI action: {action}", "INVALID_BODY")


def _selector_mode(parsed):
    if "key" in parsed:
        return "key"
    if "text" in parsed:
        return "text"
    if "x" in parsed or "y" in parsed:
        return "coordinates"
    return None


def ui_action_unavailable_error(state, action, parsed, automation=None):
    if not state.has_live_process():
        return bridge_error(
            "No Flutter app running under the bridge",
            "NO_APP_RUNNING",
            **parsed,
        ), 409

    automation = automation or state.ui_automation_status()
    if not automation["ready"]:
        code = (
            "UNSUPPORTED_TARGET"
            if automation["backend"] == "unsupported"
            or automation.get("missing")
            else "UI_NOT_READY"
        )
        http_status = 409 if code == "UI_NOT_READY" else 501
        return bridge_error(
            automation["actions"][action]["reason"],
            code,
            **parsed,
        ), http_status

    action_capability = automation["actions"][action]
    if not action_capability.get("supported"):
        return bridge_error(
            action_capability.get(
                "reason", "UI automation action is not supported"
            ),
            "UNSUPPORTED_TARGET",
            **parsed,
        ), 501

    selector_mode = _selector_mode(parsed)
    selectors = action_capability.get("selectors")
    if selector_mode and selectors and selector_mode not in selectors:
        return bridge_error(
            f"Selector '{selector_mode}' is not supported for "
            f"{action} on backend '{automation['backend']}'",
            "UNSUPPORTED_TARGET",
            **parsed,
        ), 501

    return None, None


# ---- Flutter Subprocess Management ----

def _reader_thread(state, proc):
    """Read and buffer stdout from the Flutter subprocess."""
    vm_patterns = [
        re.compile(
            r'(?:A\s+)?(?:Observatory|Dart VM Service|VM Service)'
            r'(?: debugger and profiler)?(?: on .+?)?'
            r' is available at:?\s+(https?://[^\s]+)',
            re.IGNORECASE,
        ),
    ]

    try:
        for line in iter(proc.stdout.readline, ''):
            if state.stop_event.is_set():
                break
            line = line.rstrip('\n\r')
            state.add_log(line)

            if state.vm_service_url is None:
                for pat in vm_patterns:
                    m = pat.search(line)
                    if m:
                        state.vm_service_url = m.group(1)
                        state.add_log(
                            f"[BRIDGE] Detected VM service URL: {state.vm_service_url}"
                        )
                        if state.subprocess_type == "run":
                            state.status = "running"
                            state._status_message = "Flutter run is active"
                        elif state.subprocess_type == "attach":
                            state.status = "attached"
                            state._status_message = "Flutter attach is active"
                        break

        returncode = proc.wait()
        if not state.stop_event.is_set():
            previous_subprocess_type = state.subprocess_type
            state.add_log(
                f"[BRIDGE] Flutter process exited with code {returncode}"
            )
            if returncode == 0:
                state.status = "idle"
                state._status_message = "Flutter process exited"
            else:
                state.status = "error"
                if state.vm_service_url is None:
                    state._status_message = (
                        f"Flutter {previous_subprocess_type or 'process'} "
                        f"exited with code {returncode} before the VM service "
                        "became available. Check flutterctl logs for details."
                    )
                else:
                    state._status_message = (
                        f"Flutter {previous_subprocess_type or 'process'} "
                        f"exited with code {returncode}. Check flutterctl "
                        "logs for details."
                    )
            state.subprocess_type = None
            state.process = None
            state.vm_service_url = None
    except Exception as e:
        if not state.stop_event.is_set():
            state.add_log(f"[BRIDGE] Error reading subprocess output: {e}")
            state.status = "error"
            state._status_message = f"Error reading Flutter process output: {e}"
            state.subprocess_type = None
            state.process = None
            state.vm_service_url = None
    finally:
        with state.subprocess_lock:
            if state.process is not None:
                state.process = None


def start_subprocess(state, mode, device_id):
    """Start a Flutter subprocess in run or attach mode."""
    with state.subprocess_lock:
        if state.process is not None and state.process.poll() is None:
            return {
                "error": f"Flutter app is already {state.subprocess_type or 'running'} "
                f"(status: {state.status}). Detach first."
            }

        if not os.path.isdir(state.project_dir):
            return {
                "error": f"Project directory not found: {state.project_dir}"
            }

        cmd = [state.flutter_path, mode]
        if device_id:
            cmd.extend(["-d", device_id])
        if state.target and mode == "run":
            cmd.extend(["-t", state.target])
        if state.run_args:
            cmd.extend(state.run_args)

        state.add_log(f"[BRIDGE] Running: {' '.join(cmd)}")

        try:
            state.status = "launching"
            state._status_message = (
                f"Flutter {mode} starting for device {device_id or 'default'}"
            )
            state.subprocess_type = mode
            state.device_id = device_id
            state.vm_service_url = None

            proc = subprocess.Popen(
                cmd,
                cwd=state.project_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
            )
            state.process = proc

            reader = threading.Thread(
                target=_reader_thread,
                args=(state, proc),
                daemon=True,
            )
            reader.start()

            return {
                "status": "launching",
                "subprocess_type": mode,
                "message": f"Flutter {mode} started for device {device_id or 'default'}",
            }
        except Exception as e:
            state.status = "error"
            state.subprocess_type = None
            state.vm_service_url = None
            state._status_message = f"Failed to start flutter {mode}: {e}"
            state.add_log(f"[BRIDGE] Failed to start flutter {mode}: {e}")
            return {"error": f"Failed to start flutter {mode}: {e}"}


def stop_subprocess(state):
    """Stop the Flutter subprocess."""
    with state.subprocess_lock:
        if state.process is None:
            return {"status": "idle", "message": "No Flutter process running"}

        state.add_log("[BRIDGE] Stopping Flutter process...")
        state.stop_event.set()

        try:
            if state.process.stdin:
                try:
                    state.process.stdin.write('q\n')
                    state.process.stdin.flush()
                except Exception as e:
                    state.add_log(f"[BRIDGE] Could not send quit command: {e}")

            time.sleep(0.5)

            if state.process.poll() is None:
                try:
                    if hasattr(os, 'killpg') and hasattr(os, 'getpgid'):
                        os.killpg(
                            os.getpgid(state.process.pid), signal.SIGTERM
                        )
                    else:
                        state.process.terminate()
                except (ProcessLookupError, OSError):
                    pass

                try:
                    state.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        if hasattr(os, 'killpg') and hasattr(os, 'getpgid'):
                            os.killpg(
                                os.getpgid(state.process.pid), signal.SIGKILL
                            )
                        else:
                            state.process.kill()
                        state.process.wait(timeout=2)
                    except (subprocess.TimeoutExpired, ProcessLookupError,
                            OSError):
                        pass
        except Exception as e:
            state.add_log(f"[BRIDGE] Error stopping process: {e}")
        finally:
            state.process = None
            state.subprocess_type = None
            state.vm_service_url = None
            state.status = "idle"
            state._status_message = "Flutter process stopped"
            state.stop_event.clear()
            state.add_log("[BRIDGE] Flutter process stopped")

        return {"status": "idle", "message": "Flutter process stopped"}


def send_key_to_subprocess(state, key):
    """Send a key to the Flutter subprocess stdin."""
    with state.subprocess_lock:
        if state.process is None or state.process.poll() is not None:
            return {"error": "No Flutter process running"}

        try:
            state.process.stdin.write(key + '\n')
            state.process.stdin.flush()
            state.add_log(f"[BRIDGE] Sent '{key}' to Flutter process")
            return {"status": state.status, "message": f"Sent '{key}' command"}
        except (BrokenPipeError, OSError) as e:
            return {"error": f"Failed to send command: {e}"}


# ---- HTTP Request Handler ----

class FlutterBridgeHandler(BaseHTTPRequestHandler):

    bridge_state = None

    def log_message(self, format, *args):
        if self.bridge_state:
            self.bridge_state.add_log(
                f"[HTTP] {self.client_address[0]} {format % args}"
            )

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return None
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_binary(self, data, content_type='image/png'):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header(
            'Access-Control-Allow-Methods', 'GET, POST, OPTIONS'
        )
        self.send_header(
            'Access-Control-Allow-Headers',
            'Authorization, Content-Type',
        )
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/health':
            self._send_json({"status": "ok"})
            return

        if not self._authenticate():
            return

        try:
            if path == '/status':
                self._send_json(self.bridge_state.to_status_dict())
            elif path == '/devices':
                self._handle_devices()
            elif path == '/logs':
                self._send_json({"logs": self.bridge_state.get_logs()})
            elif path == '/screenshot':
                self._handle_screenshot()
            elif path == '/ios-simulator-probe':
                self._send_json(
                    ios_simulator_probe(self.bridge_state.device_id)
                )
            elif path == '/ios-coordinate-map':
                metadata = self.bridge_state.active_device_metadata()
                target = classify_device(self.bridge_state.device_id, metadata)
                if target["backend"] != "ios-simulator":
                    self._send_json(
                        bridge_error(
                            "ios-map is only supported for iOS Simulator "
                            "targets. Launch or attach to an iOS Simulator "
                            "device first.",
                            "UNSUPPORTED_TARGET",
                            backend=target["backend"],
                            target_platform=target["target_platform"],
                            device_kind=target["device_kind"],
                        ),
                        501,
                    )
                    return
                device = target.get("device") or {}
                self._send_json(
                    ios_coordinate_map(
                        self.bridge_state.vm_service_url,
                        device_id=self.bridge_state.device_id,
                        device_name=device.get("name"),
                    )
                )
            else:
                self._send_json(
                    {"error": f"Unknown endpoint: {path}"}, 404
                )
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/health':
            if self._authenticate():
                self._send_json({"status": "ok", "authenticated": True})
            return

        if not self._authenticate():
            return

        if path == '/stop':
            self._send_json({"message": "Stopping bridge..."})
            threading.Thread(
                target=self._shutdown_bridge, daemon=True
            ).start()
            return

        if path == '/restart':
            self._send_json({"message": "Restarting bridge..."})
            threading.Thread(
                target=self._restart_bridge, daemon=True
            ).start()
            return

        body = self._read_body()

        try:
            if path == '/launch':
                device = (body or {}).get("device")
                if not device:
                    self._send_json(
                        {
                            "error": "No device specified. Provide 'device' in "
                            "request body."
                        },
                        400,
                    )
                    return
                result = start_subprocess(self.bridge_state, "run", device)
                status = 202 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/attach':
                device = (body or {}).get("device")
                if not device:
                    self._send_json(
                        {
                            "error": "No device specified. Provide 'device' in "
                            "request body."
                        },
                        400,
                    )
                    return
                result = start_subprocess(self.bridge_state, "attach", device)
                status = 202 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/detach':
                result = stop_subprocess(self.bridge_state)
                self._send_json(result)

            elif path == '/hot-reload':
                result = send_key_to_subprocess(self.bridge_state, 'r')
                status = 200 if "error" not in result else 400
                self._send_json(result, status)

            elif path == '/hot-restart':
                result = send_key_to_subprocess(self.bridge_state, 'R')
                status = 200 if "error" not in result else 400
                self._send_json(result, status)

            elif path in (
                '/tap', '/type', '/press', '/scroll', '/inspect', '/wait'
            ):
                self._handle_ui_action(path.lstrip('/'), body)

            else:
                self._send_json(
                    {"error": f"Unknown endpoint: {path}"}, 404
                )
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _authenticate(self):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            self._send_json(
                {"error": "Missing or invalid Authorization header"}, 401
            )
            return False
        token = auth[7:]
        if token != self.bridge_state.token:
            self._send_json({"error": "Invalid bearer token"}, 401)
            return False

        return True

    def _handle_ui_action(self, action, body):
        started = time.time()
        parsed, error = validate_ui_action(action, body)
        if error:
            error["elapsed_ms"] = int((time.time() - started) * 1000)
            self._send_json(error, 400)
            return

        automation = (
            self.bridge_state.ui_automation_status()
            if self.bridge_state.has_live_process()
            else None
        )
        unavailable, status = ui_action_unavailable_error(
            self.bridge_state, action, parsed, automation
        )
        if unavailable:
            unavailable["elapsed_ms"] = int((time.time() - started) * 1000)
            self._send_json(unavailable, status)
            return

        # Dispatch to the appropriate platform backend.
        result, status = dispatch_ui_action(
            self.bridge_state, action, parsed, automation
        )
        result["elapsed_ms"] = int((time.time() - started) * 1000)
        self._send_json(result, status)

    def _handle_devices(self):
        try:
            flutter_path = self.bridge_state.flutter_path
            result = subprocess.run(
                [flutter_path, "devices", "--machine"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self._send_json(
                    {"error": f"flutter devices failed: {result.stderr}"}, 500
                )
                return
            devices = json.loads(result.stdout)
            self.bridge_state.update_devices_cache(devices)
            self._send_json({"devices": devices})
        except json.JSONDecodeError:
            # Fallback: try non-machine output
            try:
                result = subprocess.run(
                    [flutter_path, "devices"],
                    capture_output=True, text=True, timeout=30,
                )
                self._send_json(
                    {
                        "devices": [],
                        "raw_output": result.stdout,
                        "error": "Could not parse machine-readable output",
                    }
                )
            except Exception:
                self._send_json(
                    {"error": "Failed to parse flutter devices output"}, 500
                )
        except subprocess.TimeoutExpired:
            self._send_json({"error": "flutter devices timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_screenshot(self):
        # macOS desktop: use Applescript + screencapture (flutter screenshot
        # is not supported on desktop targets).
        metadata = self.bridge_state.active_device_metadata()
        target = classify_device(self.bridge_state.device_id, metadata)
        if target["backend"] == "macos-desktop":
            self._handle_macos_screenshot()
            return

        fd, tmp_path = tempfile.mkstemp(
            suffix='.png', prefix='flutter_screenshot_'
        )
        os.close(fd)

        try:
            flutter_path = self.bridge_state.flutter_path
            project_dir = self.bridge_state.project_dir

            cmd = [flutter_path, "screenshot"]
            if self.bridge_state.device_id:
                cmd.extend(["-d", self.bridge_state.device_id])
            cmd.extend(["-o", tmp_path])

            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode != 0:
                self._send_json(
                    {"error": f"flutter screenshot failed: {result.stderr}"},
                    500,
                )
                return

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                self._send_json(
                    {"error": "Screenshot file is empty or not found"}, 500
                )
                return

            with open(tmp_path, 'rb') as f:
                data = f.read()
            self._send_binary(data, 'image/png')
        except subprocess.TimeoutExpired:
            self._send_json({"error": "flutter screenshot timed out"}, 500)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _handle_macos_screenshot(self):
        app_name = self.bridge_state.app_name
        window, error = _macos_get_app_window_info(app_name)
        if error:
            self._send_json(
                {"error": f"Failed to get app window: {error}"}, 500
            )
            return

        fd, tmp_path = tempfile.mkstemp(
            suffix='.png', prefix='flutter_screenshot_'
        )
        os.close(fd)

        try:
            result = subprocess.run(
                _macos_screencapture_command(window["window_id"], tmp_path),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                self._send_json(
                    {
                        "error": f"screencapture failed: "
                        f"{result.stderr.strip()}"
                    },
                    500,
                )
                return
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                self._send_json(
                    {"error": "Screenshot file is empty or not found"}, 500
                )
                return
            with open(tmp_path, 'rb') as f:
                data = f.read()
            self._send_binary(data, 'image/png')
        except subprocess.TimeoutExpired:
            self._send_json(
                {"error": "screencapture timed out"}, 500
            )
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _shutdown_bridge(self):
        time.sleep(0.5)
        stop_subprocess(self.bridge_state)
        self.bridge_state.stop_event.set()
        os._exit(0)

    def _restart_bridge(self):
        time.sleep(0.5)
        stop_subprocess(self.bridge_state)
        self.bridge_state.stop_event.set()
        try:
            self.server.server_close()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable, *sys.argv])


# ---- Main ----

def parse_args():
    parser = argparse.ArgumentParser(description="Flutter Host Bridge")
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to listen on"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to"
    )
    parser.add_argument(
        "--project-dir", required=True, help="Flutter project directory"
    )
    parser.add_argument(
        "--target", default="lib/main.dart", help="Flutter target file"
    )
    parser.add_argument(
        "--flutter-path", default="flutter", help="Path to flutter executable"
    )
    parser.add_argument(
        "--token", required=True, help="Bearer token for auth"
    )
    parser.add_argument(
        "--log-file", default="", help="Log file path for bridge output"
    )
    parser.add_argument(
        "--run-args", default="", help="Extra args for flutter run"
    )
    return parser.parse_args()


def parse_run_args(value):
    """Parse optional flutter run args from JSON array or shell-style string."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return shlex.split(value)
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, str):
        return shlex.split(parsed)
    return []


def main():
    args = parse_args()

    if not os.path.isdir(args.project_dir):
        print(
            f"Error: Project directory not found: {args.project_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    state = BridgeState(
        token=args.token,
        project_dir=args.project_dir,
        device_id="",
        target=args.target,
        flutter_path=args.flutter_path,
        run_args=args.run_args,
    )

    def signal_handler(signum, frame):
        print("\nShutting down Flutter bridge...", file=sys.stderr)
        stop_subprocess(state)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.log_file:
        state.add_log(f"[BRIDGE] Logging to {args.log_file}")

    server = ThreadingHTTPServer((args.host, args.port), FlutterBridgeHandler)
    FlutterBridgeHandler.bridge_state = state

    print(
        f"Flutter Bridge running on http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    print(f"Project: {args.project_dir}", file=sys.stderr)
    print(f"App:     {state.app_name}", file=sys.stderr)
    print(
        f"Token: {args.token[:8]}...",
        file=sys.stderr,
    )
    print(
        "Use FLUTTER_BRIDGE_TOKEN in container to authenticate.",
        file=sys.stderr,
    )
    print(file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nCleaning up...", file=sys.stderr)
        stop_subprocess(state)
        server.server_close()


__all__ = [name for name in globals() if not name.startswith("__")]


if __name__ == "__main__":
    main()
