"""Protocol / crypto suite against live instance A (TCP 19974, WS 18973).

20 checks covering verification, traversal, metadata attacks, replay,
identity binding, blockchain integrity and chat safety.
"""
import asyncio
import glob
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *

SRC = ART
MARKER = b"SYNFLOW_SECRET_PAYLOAD_"


def setup():
    data = asyncio.run(ws_settings(WS_A, autoAccept=True, downloadPath=DEST_A))
    if data.get("type") != "settings:applied":
        print(f"FATAL: settings not applied: {data}", flush=True)
        sys.exit(2)
    clean_dir(DEST_A)
    wipe("sfOTHER")

    write_file(f"{SRC}/p1mb.bin", MARKER + os.urandom(1024 * 1024 - len(MARKER)))
    write_file(f"{SRC}/pzero.bin", b"")
    write_file(f"{SRC}/pm5a.bin", os.urandom(2 * 1024 * 1024))
    write_file(f"{SRC}/pm5b.bin", os.urandom(3 * 1024 * 1024))
    write_file(f"{SRC}/trav-src.txt", b"traversal payload")
    write_file(f"{SRC}/small100k.bin", os.urandom(100 * 1024))
    write_file(f"{SRC}/flipme.bin", os.urandom(80 * 1024))
    write_file(f"{SRC}/basic.txt", b"basic transfer content")
    write_file(f"{SRC}/t7dup.txt", b"duplicate id payload")
    write_file(f"{SRC}/t21.txt", b"long transfer id payload")
    write_file(f"{SRC}/sendername.txt", b"name sanitation payload")
    write_file(f"{SRC}/ws-send-src.txt", b"ws engine send payload")


def t26_honest_1mb():
    rec = bytearray()

    def record(raw):
        rec.extend(raw)

    r = send_transfer(
        [{"path": f"{SRC}/p1mb.bin", "wire": "secret-payload-1mb.bin"}],
        record_recv=record,
    )
    dest = os.path.join(DEST_A, "secret-payload-1mb.bin")
    ok(
        "T26a 1MB transfer verified + byte-identical",
        r.outcome == "completed" and os.path.exists(dest)
        and file_sha(dest) == file_sha(f"{SRC}/p1mb.bin"),
        f"outcome={r.outcome} err={r.error}",
    )
    blob = bytes(rec)
    leaked = (MARKER in blob) or (b"secret-payload-1mb" in blob)
    ok(
        "T26b zero plaintext (filename/payload) in server->client bytes",
        len(blob) > 0 and not leaked,
        f"recorded={len(blob)}B leaked={leaked}",
    )


def t27_zero_byte():
    r = send_transfer([{"path": f"{SRC}/pzero.bin", "wire": "zerobyte.bin"}])
    dest = os.path.join(DEST_A, "zerobyte.bin")
    ok(
        "T27 zero-byte file transfers and verifies",
        r.outcome == "completed" and os.path.exists(dest)
        and os.path.getsize(dest) == 0,
        f"outcome={r.outcome} err={r.error}",
    )


def t28_multi_file():
    r = send_transfer([
        {"path": f"{SRC}/pm5a.bin", "wire": "multi-a.bin"},
        {"path": f"{SRC}/pm5b.bin", "wire": "multi-b.bin"},
    ])
    da = os.path.join(DEST_A, "multi-a.bin")
    db = os.path.join(DEST_A, "multi-b.bin")
    ok(
        "T28 multi-file transfer (2MB+3MB) both verified",
        r.outcome == "completed"
        and file_sha(da) == file_sha(f"{SRC}/pm5a.bin")
        and file_sha(db) == file_sha(f"{SRC}/pm5b.bin"),
        f"outcome={r.outcome} err={r.error}",
    )


def t5_traversal():
    escape_targets = (
        "/tmp/evil-syncflow-test.txt",
        os.path.join(HOME_DIR, "Downloads", "evil-syncflow-test.txt"),
        os.path.join(HOME_DIR, "evil-syncflow-test.txt"),
        os.path.join(HOME_DIR, "Downloads", "tmp", "evil-syncflow-test.txt"),
    )
    for p in escape_targets:
        try:
            os.unlink(p)
        except OSError:
            pass
    r = send_transfer([
        {"path": f"{SRC}/trav-src.txt", "wire": "../../../../tmp/evil-syncflow-test.txt"},
    ])
    confined = glob.glob(os.path.join(DEST_A, "evil-syncflow-test*.txt"))
    escaped = any(os.path.exists(p) for p in escape_targets)
    ok(
        "T5 path traversal confined to receive dir",
        r.outcome == "completed" and confined and not escaped,
        f"outcome={r.outcome} confined={bool(confined)} escaped={escaped}",
    )


def t5b_header_meta_mismatch():
    r = send_transfer(
        [{"path": f"{SRC}/basic.txt", "wire": "meta-name.bin"}],
        header_name="mismatch-header.bin",
    )
    ok(
        "T5b signed-header filename != metadata filename rejected",
        r.outcome == "integrity_failed" and "file_name" in (r.error or "")
        and not os.path.exists(os.path.join(DEST_A, "meta-name.bin"))
        and not os.path.exists(os.path.join(DEST_A, "mismatch-header.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t6_control_chars():
    r = send_transfer([{"path": f"{SRC}/basic.txt", "wire": "evil\x00\x07name.txt"}])
    names = os.listdir(DEST_A)
    bad = [n for n in names if not n.isprintable() or "\x00" in n or "\x07" in n]
    saved = [n for n in names if n.startswith("evil") and n.endswith("name.txt")]
    ok(
        "T6 control chars stripped from filename",
        r.outcome == "completed" and saved and not bad,
        f"outcome={r.outcome} saved={saved} bad={bad}",
    )


def t7_duplicate_ids():
    r1 = send_transfer([{"path": f"{SRC}/t7dup.txt", "wire": "t7dup.txt"}], transfer_id="dup-id-1234")
    r2 = send_transfer([{"path": f"{SRC}/t7dup.txt", "wire": "t7dup.txt"}], transfer_id="dup-id-1234")
    dup_files = glob.glob(os.path.join(DEST_A, "t7dup*.txt"))
    async def check():
        data = await ws_call(WS_A, {"type": "transfers:list"}, {"transfers:update"})
        done = [t for t in data.get("completed", []) if t.get("status") == "completed"]
        last2 = done[-2:]
        ids = [t.get("id") for t in last2]
        return len(ids) == 2 and len(set(ids)) == 2 and all(str(i).startswith("in-") for i in ids)
    ids_ok = asyncio.run(check())
    ok(
        "T7 duplicate sender transferIds -> unique receive ids, both complete",
        r1.outcome == "completed" and r2.outcome == "completed"
        and len(dup_files) >= 2 and ids_ok,
        f"r1={r1.outcome} r2={r2.outcome} files={len(dup_files)} ids_ok={ids_ok}",
    )


def t11a_declared_too_big():
    r = send_transfer(
        [{"path": f"{SRC}/small100k.bin", "wire": "size-big.bin"}],
        declared_sizes={0: 100 * 1024 + 1000},
    )
    ok(
        "T11a declared size > actual rejected, no file written",
        r.outcome == "integrity_failed" and "size mismatch" in (r.error or "")
        and not os.path.exists(os.path.join(DEST_A, "size-big.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t11b_declared_too_small():
    r = send_transfer(
        [{"path": f"{SRC}/small100k.bin", "wire": "size-small.bin"}],
        declared_sizes={0: 100 * 1024 - 1000},
    )
    ok(
        "T11b actual size > declared rejected, no file written",
        r.outcome == "integrity_failed" and "more data than declared" in (r.error or "")
        and not os.path.exists(os.path.join(DEST_A, "size-small.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t12a_stale_offer():
    r = send_transfer(
        [{"path": f"{SRC}/basic.txt", "wire": "stale.bin"}],
        backdate_offer=600,
    )
    ok(
        "T12a stale offer (600s old) rejected as replay",
        r.outcome == "handshake_failed",
        f"outcome={r.outcome} err={r.error}",
    )


def t12b_tampered_sig():
    r = send_transfer(
        [{"path": f"{SRC}/basic.txt", "wire": "tamsig.bin"}],
        tamper_offer_sig=True,
    )
    ok(
        "T12b tampered offer signature rejected",
        r.outcome == "handshake_failed",
        f"outcome={r.outcome} err={r.error}",
    )


def t13_wrong_device_id():
    async def go():
        cmd = {
            "type": "command:send",
            "targetIp": "127.0.0.1",
            "targetPort": TCP_B,
            "targetDeviceId": "0" * 32,
            "files": [f"{SRC}/ws-send-src.txt"],
        }
        async with WSConn(WS_A) as ws:
            await ws.send(cmd)
            new = await ws.wait({"transfer:new", "error"}, timeout=6)
            if new.get("type") != "transfer:new":
                return None, new
            err = await ws.wait({"transfer:error"}, timeout=15)
            return err, None

    err, early = asyncio.run(go())
    text = (err or {}).get("error") or (early or {}).get("error") or ""
    ok(
        "T13 engine refuses targetDeviceId mismatch (real command:send path)",
        "does not match the selected device" in text,
        f"error={text[:90]}",
    )


def t14_foreign_signer():
    r = send_transfer(
        [{"path": f"{SRC}/basic.txt", "wire": "foreign-signer.bin"}],
        chunk_signer_identity=test_identity("sfOTHER"),
    )
    ok(
        "T14 chunks signed by a different key than the handshake rejected",
        r.outcome == "integrity_failed" and "sender_pubkey" in (r.error or "")
        and not os.path.exists(os.path.join(DEST_A, "foreign-signer.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t16_bitflip():
    r = send_transfer(
        [{"path": f"{SRC}/flipme.bin", "wire": "bitflip.bin"}],
        tamper_chunk=(0, 0),
    )
    ok(
        "T16 bit-flipped chunk fails authentication, no file written",
        r.outcome == "integrity_failed" and "authentication" in (r.error or "")
        and not os.path.exists(os.path.join(DEST_A, "bitflip.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t20_sendername_sanitized():
    r = send_transfer(
        [{"path": f"{SRC}/sendername.txt", "wire": "sendername.txt"}],
        sender_name="Nasty\x1b[31m\x00Name",
    )
    name = None
    try:
        with open("/tmp/opencode/sfA/peers.json") as f:
            peers = json.load(f).get("peers", {})
        name = peers.get("127.0.0.1", {}).get("name")
    except OSError:
        pass
    ok(
        "T20 senderName control chars sanitized before storage",
        r.outcome == "completed" and isinstance(name, str)
        and name.isprintable() and "\x1b" not in name and "\x00" not in name,
        f"name={name!r}",
    )


def t21_long_transfer_id():
    r = send_transfer(
        [{"path": f"{SRC}/t21.txt", "wire": "t21.bin"}],
        transfer_id="X" * 300,
    )
    ok(
        "T21 over-long transferId regenerated, transfer still succeeds",
        r.outcome == "completed" and os.path.exists(os.path.join(DEST_A, "t21.bin")),
        f"outcome={r.outcome} err={r.error}",
    )


def t23_non_string_chat():
    r = raw_chat(12345)
    ok(
        "T23 non-string chat text rejected cleanly",
        not r.get("ok"),
        f"resp={r}",
    )
    alive = asyncio.run(ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=5))
    ok("T23b server alive after bad chat", alive.get("type") == "identity:info")


def t22_chat_accepted():
    r = raw_chat("syncflow e2e chat test")
    ok(
        "T22 E2E chat over transfer port accepted",
        r.get("ok") is True,
        f"resp={r}",
    )


def t19_chat_flood():
    oks = 0
    limited = 0
    other = 0
    monotonic = True
    seen_limited = False
    for i in range(40):
        ack = raw_chat(f"floof {i}", timeout=8)
        if ack.get("ok"):
            if seen_limited:
                monotonic = False
            oks += 1
        elif ack.get("error") == "rate limited":
            seen_limited = True
            limited += 1
        else:
            other += 1
    ok(
        "T19 chat flood rate-limited (30 msgs/60s per IP), limit monotonic",
        1 <= oks <= 30 and limited >= 8 and monotonic and other == 0,
        f"ok={oks} limited={limited} other={other}",
    )


def main():
    setup()
    t26_honest_1mb()
    t27_zero_byte()
    t28_multi_file()
    t5_traversal()
    t5b_header_meta_mismatch()
    t6_control_chars()
    t7_duplicate_ids()
    t11a_declared_too_big()
    t11b_declared_too_small()
    t12a_stale_offer()
    t12b_tampered_sig()
    t13_wrong_device_id()
    t14_foreign_signer()
    t16_bitflip()
    t20_sendername_sanitized()
    t21_long_transfer_id()
    t23_non_string_chat()
    t22_chat_accepted()
    t19_chat_flood()
    finish("t_proto")


if __name__ == "__main__":
    main()
