#!/usr/bin/env python3
"""Give a Reef Factory device your Wi-Fi without the app or the cloud (unofficial).

When a device loses its Wi-Fi settings it opens its own hotspot (SSID = serial
number, WPA2, default password printed in the manufacturer's manual). Connect a
computer to that hotspot, then run:

    python3 reef_provision.py list
    python3 reef_provision.py connect --ssid "MyNetwork"     # asks for the password

The device answers on 10.32.54.1 (override with --ap). Only 2.4 GHz networks work.
It uses the device's own local WebSocket protocol, exactly like its setup page.
Python 3 standard library only.
"""
import argparse, base64, getpass, os, socket, struct, sys, time


def ws_open(host):
    s = socket.create_connection((host, 80), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /controler HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: arduino\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            sys.exit("device closed the connection during the handshake")
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    if b" 101 " not in head.split(b"\r\n")[0]:
        sys.exit("handshake refused: " + head.split(b"\r\n")[0].decode(errors="replace"))
    return s, rest


def ws_send(s, payload, op=2):
    mask = os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
    s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def frames(s, buf, seconds):
    s.settimeout(1)
    end = time.time() + seconds
    while time.time() < end:
        while len(buf) >= 2:
            op, n, i = buf[0] & 15, buf[1] & 127, 2
            if n == 126:
                if len(buf) < 4:
                    break
                n, i = struct.unpack(">H", buf[2:4])[0], 4
            if len(buf) < i + n:
                break
            payload, buf = buf[i:i + n], buf[i + n:]
            if op == 9:
                ws_send(s, payload, 10)
            if op == 2:
                yield payload
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            return
        buf += chunk


def frame(serial, topic, sub, data=b""):
    return b"\x00".join((serial.encode(), topic.encode(), sub.encode(), b"", data)) + b"\x00"


def parse_list(blob):
    nets, pos = [], 1
    for _ in range(blob[0] if blob else 0):
        n = blob[pos]; pos += 1
        nets.append(blob[pos:pos + n].decode("utf-8", "replace")); pos += n + 6
    return nets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["list", "connect"])
    ap.add_argument("--ap", default="10.32.54.1", help="device address in its hotspot")
    ap.add_argument("--ssid", help="your 2.4 GHz network (for connect)")
    args = ap.parse_args()
    s, buf = ws_open(args.ap)
    serial, nets = None, []
    ws_send(s, frame("0000000000000000", "get", "config"))  # answered with the serial as sender
    for p in frames(s, buf, 10):
        parts = p.split(b"\x00", 4)
        if len(parts) == 5 and parts[1] == b"refresh" and parts[2] == b"config":
            serial = parts[0].decode("latin1"); break
    if not serial:
        sys.exit("no answer from the device - are you connected to its hotspot?")
    ws_send(s, frame(serial, "wifi", "list"))  # the device expects its own serial as sender
    for p in frames(s, b"", 15):
        parts = p.split(b"\x00", 4)
        if len(parts) == 5 and parts[2] == b"wifiList":
            nets = parse_list(parts[4]); break
    print(f"device {serial} sees {len(nets)} network(s):")
    for n in nets:
        print("  -", n)
    if args.action == "list":
        return
    if not args.ssid:
        sys.exit("--ssid is required for connect")
    if args.ssid not in nets:
        sys.exit(f"{args.ssid!r} is not in the device's list (2.4 GHz only, check the name)")
    password = getpass.getpass(f"Wi-Fi password for {args.ssid}: ")
    ws_send(s, frame(serial, "wifi", "connect",
                     args.ssid.encode() + b"\x00" + password.encode() + b"\x00"))
    print("sent. The device now joins your network and switches its hotspot off.")
    print("Find its new address in your router (it uses DHCP) and add it to Home Assistant.")


if __name__ == "__main__":
    main()
