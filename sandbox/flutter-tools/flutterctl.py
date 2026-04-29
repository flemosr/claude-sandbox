#!/usr/bin/env python3
"""
Flutter control utility for connecting to the Flutter host bridge.

Usage:
    from flutterctl import FlutterCtl

    ctl = FlutterCtl()
    ctl.test()
    ctl.status()
    ctl.devices()
    ctl.launch(device="ios")
    ctl.logs()
    ctl.screenshot("screen.png")
    ctl.hot_reload()
    ctl.tap(x=100, y=200)
    ctl.type_text("hello")
    ctl.press("enter")
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


class FlutterCtl:
    """Flutter bridge control client."""

    DEFAULT_BRIDGE_URL = "http://host.docker.internal:8765"

    @staticmethod
    def _load_config_file():
        """Load bridge config from .workcell/flutter-config.json.

        Returns a dict with keys token, port, or empty dict if
        the file is not found or unparseable.
        """
        search_paths = [
            os.path.join(os.getcwd(), ".workcell", "flutter-config.json"),
        ]
        for path in search_paths:
            try:
                with open(path) as f:
                    config = json.load(f)
                if isinstance(config, dict) and "port" in config:
                    return config
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
        return {}

    def __init__(self, bridge_url=None):
        file_config = self._load_config_file()

        self.bridge_url = (
            bridge_url
            or os.environ.get("FLUTTER_BRIDGE_URL")
            or (f"http://host.docker.internal:{file_config['port']}" if "port" in file_config else None)
            or self.DEFAULT_BRIDGE_URL
        )
        self.token = (
            os.environ.get("FLUTTER_BRIDGE_TOKEN")
            or file_config.get("token", "")
        )

    def _request(self, method, path, body=None, accept_binary=False, timeout=30):
        url = f"{self.bridge_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if accept_binary:
                    return resp.read()
                content = resp.read().decode()
                if not content:
                    return {}
                return json.loads(content)
        except urllib.error.HTTPError as e:
            err_body = b""
            try:
                err_body = e.read()
            except Exception:
                pass
            try:
                return json.loads(err_body.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise RuntimeError(
                    f"Bridge error ({e.code}): {err_body.decode(errors='replace')}"
                ) from e
        except urllib.error.URLError:
            raise ConnectionError(
                f"Cannot reach Flutter bridge at {self.bridge_url}. "
                "Is the host bridge running?"
            )

    def test(self):
        """Test connection to the Flutter bridge."""
        try:
            result = self._request("POST", "/health", timeout=5)
            return result.get("status") == "ok"
        except ConnectionError:
            return False

    def status(self):
        """Get bridge status."""
        return self._request("GET", "/status")

    def devices(self):
        """List available Flutter devices."""
        return self._request("GET", "/devices")

    def launch(self, device=None):
        """Launch the Flutter app on a device."""
        body = {"device": device} if device else None
        return self._request("POST", "/launch", body=body, timeout=60)

    def attach(self, device=None):
        """Attach to a running Flutter app on a device."""
        body = {"device": device} if device else None
        return self._request("POST", "/attach", body=body, timeout=60)

    def detach(self):
        """Detach/stop the Flutter app."""
        return self._request("POST", "/detach")

    def hot_reload(self):
        """Trigger hot reload."""
        return self._request("POST", "/hot-reload", timeout=60)

    def hot_restart(self):
        """Trigger hot restart."""
        return self._request("POST", "/hot-restart", timeout=60)

    def logs(self):
        """Get recent log lines from the Flutter app."""
        return self._request("GET", "/logs")

    def screenshot(self, output_path):
        """Take a screenshot and save to output_path."""
        data = self._request(
            "GET", "/screenshot", accept_binary=True, timeout=30
        )
        if isinstance(data, dict):
            return data
        with open(output_path, "wb") as f:
            f.write(data)
        return {"path": output_path, "size": len(data)}

    def tap(self, x=None, y=None, text=None, key=None):
        """Tap coordinates or an element selected by text/key."""
        body = {}
        if x is not None or y is not None:
            if x is None or y is None:
                raise ValueError("Coordinate taps require both --x and --y")
            body["x"] = x
            body["y"] = y
        if text is not None:
            body["text"] = text
        if key is not None:
            body["key"] = key
        return self._request("POST", "/tap", body=body)

    def type_text(self, text):
        """Type text into the currently focused input."""
        return self._request("POST", "/type", body={"text": text})

    def press(self, key):
        """Press a named key or key combination."""
        return self._request("POST", "/press", body={"key": key})

    def scroll(self, dx=None, dy=None, edge=None):
        """Scroll by delta or to an edge."""
        body = {}
        if dx is not None:
            body["dx"] = dx
        if dy is not None:
            body["dy"] = dy
        if edge is not None:
            body["edge"] = edge
        return self._request("POST", "/scroll", body=body)

    def inspect(self, text=None, key=None):
        """Inspect the current UI automation tree or selector match."""
        body = {}
        if text is not None:
            body["text"] = text
        if key is not None:
            body["key"] = key
        return self._request("POST", "/inspect", body=body)

    def wait(self, text=None, key=None, timeout_ms=5000):
        """Wait for an element matching text/key."""
        body = {"timeout_ms": timeout_ms}
        if text is not None:
            body["text"] = text
        if key is not None:
            body["key"] = key
        return self._request("POST", "/wait", body=body)


def print_json_result(result, *, error_exit=True):
    if "error" in result:
        print(json.dumps(result, indent=2), file=sys.stderr)
        if error_exit:
            sys.exit(1)
    else:
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Flutter bridge control (from inside the workcell)"
    )
    parser.add_argument(
        "--bridge-url",
        default=None,
        help=(
            "Flutter bridge URL (default: FLUTTER_BRIDGE_URL env var, "
            f"then {FlutterCtl.DEFAULT_BRIDGE_URL})"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("test", help="Test connection to Flutter bridge")

    subparsers.add_parser("status", help="Get bridge status")

    subparsers.add_parser("devices", help="List available Flutter devices")

    launch_parser = subparsers.add_parser("launch", help="Launch Flutter app")
    launch_parser.add_argument("--device", "-d", help="Target device ID")

    attach_parser = subparsers.add_parser(
        "attach", help="Attach to running Flutter app"
    )
    attach_parser.add_argument("--device", "-d", help="Target device ID")

    subparsers.add_parser("detach", help="Detach/stop Flutter app")

    subparsers.add_parser("hot-reload", help="Hot reload the Flutter app")

    subparsers.add_parser("hot-restart", help="Hot restart the Flutter app")

    subparsers.add_parser("logs", help="Get recent Flutter logs")

    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="Take a screenshot; macOS desktop captures the app window only",
    )
    screenshot_parser.add_argument(
        "--output", "-o", required=True, help="Output file path"
    )

    tap_parser = subparsers.add_parser(
        "tap", help="Tap coordinates or an element selected by text/key"
    )
    tap_parser.add_argument(
        "--x", type=float, help="X coordinate in the active coordinate space"
    )
    tap_parser.add_argument(
        "--y", type=float, help="Y coordinate in the active coordinate space"
    )
    tap_parser.add_argument("--text", help="Text selector")
    tap_parser.add_argument("--key", help="Key selector")

    type_parser = subparsers.add_parser(
        "type", help="Type text into the currently focused input"
    )
    type_parser.add_argument("text", help="Text to type")

    press_parser = subparsers.add_parser(
        "press", help="Press a named key or key combination"
    )
    press_parser.add_argument("key", help="Key name, e.g. enter or command+r")

    scroll_parser = subparsers.add_parser(
        "scroll", help="Scroll by delta or to an edge"
    )
    scroll_parser.add_argument("--dx", type=float, help="Horizontal delta")
    scroll_parser.add_argument("--dy", type=float, help="Vertical delta")
    scroll_parser.add_argument(
        "--edge", choices=["top", "bottom", "left", "right"],
        help="Scroll to an edge",
    )

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect the current UI automation tree or selector"
    )
    inspect_parser.add_argument("--text", help="Text selector")
    inspect_parser.add_argument("--key", help="Key selector")

    wait_parser = subparsers.add_parser(
        "wait", help="Wait for an element matching text/key"
    )
    wait_parser.add_argument("--text", help="Text selector")
    wait_parser.add_argument("--key", help="Key selector")
    wait_parser.add_argument(
        "--timeout", type=int, default=5000,
        help="Timeout in milliseconds",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        ctl = FlutterCtl(bridge_url=args.bridge_url)

        if args.command == "test":
            if ctl.test():
                print("Flutter bridge is reachable")
            else:
                print(
                    "Flutter bridge is NOT reachable. "
                    "Ensure the host bridge is running and FLUTTER_BRIDGE_TOKEN is set."
                )
                sys.exit(1)

        elif args.command == "status":
            result = ctl.status()
            print(json.dumps(result, indent=2))

        elif args.command == "devices":
            result = ctl.devices()
            if "devices" in result:
                print(json.dumps(result["devices"], indent=2))
            else:
                print(json.dumps(result, indent=2))

        elif args.command == "launch":
            result = ctl.launch(device=args.device)
            if "error" in result:
                print(f"Error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(result, indent=2))

        elif args.command == "attach":
            result = ctl.attach(device=args.device)
            if "error" in result:
                print(f"Error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(result, indent=2))

        elif args.command == "detach":
            result = ctl.detach()
            print(json.dumps(result, indent=2))

        elif args.command == "hot-reload":
            result = ctl.hot_reload()
            if "error" in result:
                print(f"Error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(result.get("message", json.dumps(result, indent=2)))

        elif args.command == "hot-restart":
            result = ctl.hot_restart()
            if "error" in result:
                print(f"Error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(result.get("message", json.dumps(result, indent=2)))

        elif args.command == "logs":
            result = ctl.logs()
            if "logs" in result:
                for line in result["logs"]:
                    print(line)
            else:
                print(json.dumps(result, indent=2))

        elif args.command == "screenshot":
            result = ctl.screenshot(args.output)
            if "error" in result:
                print(f"Error: {result['error']}", file=sys.stderr)
                sys.exit(1)
            print(f"Screenshot saved to {result['path']} ({result['size']} bytes)")

        elif args.command == "tap":
            result = ctl.tap(
                x=args.x, y=args.y, text=args.text, key=args.key
            )
            print_json_result(result)

        elif args.command == "type":
            result = ctl.type_text(args.text)
            print_json_result(result)

        elif args.command == "press":
            result = ctl.press(args.key)
            print_json_result(result)

        elif args.command == "scroll":
            result = ctl.scroll(dx=args.dx, dy=args.dy, edge=args.edge)
            print_json_result(result)

        elif args.command == "inspect":
            result = ctl.inspect(text=args.text, key=args.key)
            print_json_result(result)

        elif args.command == "wait":
            result = ctl.wait(
                text=args.text, key=args.key, timeout_ms=args.timeout
            )
            print_json_result(result)

    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
