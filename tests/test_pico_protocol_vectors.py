"""CRC values calculated independently with binascii.crc_hqx(..., 0xffff)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scr/pico/firmware"))

from protocol import ZERO_SESSION, decode, encode


class ProtocolVectors(unittest.TestCase):
    def test_complete_frames(self):
        session = "a" * 32 + "0000000100000001"
        vectors = (
            ("HELLO", ZERO_SESSION, 0, "a" * 32, "C478"),
            ("READY", session, 0, "DISARMED,30,2000,500", "9B73"),
            ("ARM", session, 1, "-", "2804"),
            ("MOVE", session, 2, "10,-10,250", "29F0"),
            ("ACK", session, 2, "MOVE", "FA57"),
            ("DONE", session, 2, "completed,250", "CC9E"),
            ("STOP", session, 3, "user", "A127"),
            ("STATE", session, 4, "DISARMED,0,0,0,0,none", "FB17"),
        )
        for kind, session_id, seq, payload, check in vectors:
            expected = ("V1|%s|%s|%d|%s|%s\n" %
                        (kind, session_id, seq, payload, check)).encode("ascii")
            self.assertEqual(encode(kind, session_id, seq, payload), expected)
            if kind in ("HELLO", "ARM", "MOVE", "STOP"):
                self.assertEqual(decode(expected), (kind, session_id, seq, payload))

    def test_invalid_numbers_and_crc_are_rejected(self):
        session = "a" * 48
        for payload in ("+1,1,100", "01,1,100", "-0,1,100", "1,1,0"):
            with self.assertRaises(ValueError):
                decode(encode("MOVE", session, 1, payload))
        frame = encode("ARM", session, 1)
        with self.assertRaises(ValueError):
            decode(frame[:-5] + b"0000\n")


if __name__ == "__main__":
    unittest.main()
