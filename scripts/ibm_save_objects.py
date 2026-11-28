"""Identify early IBM save-stream object headers in expanded data."""

import re

NAME = re.compile(r"[A-Z0-9_$#@.]{1,10} *\Z")
TYPES = {
    "0201": "*PGM",
    "0401": "*LIB",
    "0e03": "*MSGF",
    "0e08": "*RCT",
    "1001": "*DEVD",
    "1101": "*LIND",
    "1201": "*CTLD",
    "1901": "*FILE",
    "1905": "*CMD",
    "190a": "*DTAARA",
    "1915": "*PNLGRP",
    "1916": "*MENU",
}
DESCRIPTOR = "OBJECT DESCRIPTOR".encode("cp037")


def headers(data, base=0, aligned=True):
    """Yield header candidates. Offsets refer to the caller's expanded coordinate space."""
    start = 0
    while (offset := data.find(b"\xff" * 4, start)) >= 0:
        start = offset + 1
        if aligned and (offset + base) % 512:
            continue
        if offset + 180 > len(data):
            continue
        name = data[offset + 4 : offset + 14].decode("cp037")
        if not NAME.fullmatch(name) or data[offset + 14 : offset + 26] != b"\x40" * 12:
            continue
        type_code = data[offset + 34 : offset + 36].hex()
        yield {
            "at": offset + base,
            "name": name.strip(),
            "type_code": type_code,
            "object_type": TYPES.get(type_code),
            "descriptor": data[offset + 154 : offset + 171] == DESCRIPTOR,
            "following_word": data[offset + 36 : offset + 40].hex(),
        }
