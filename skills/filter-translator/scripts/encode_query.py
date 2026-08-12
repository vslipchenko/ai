"""RFC 3986 query-string percent-encoding for a list of key/value pairs.

The model builds the target format's key/value structure; this script's only
job is correct percent-encoding, spelled out explicitly (not delegated to
urllib.parse.urlencode, which implements application/x-www-form-urlencoded —
a different, often-confused spec that also disagrees with Node's
URLSearchParams on how '~' is handled).
"""

import json
import sys

_UNRESERVED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def percent_encode(s):
    out = []
    for byte in s.encode("utf-8"):
        ch = chr(byte)
        if byte < 128 and ch in _UNRESERVED:
            out.append(ch)
        else:
            out.append("%{:02X}".format(byte))
    return "".join(out)


def encode_pairs(pairs):
    return "&".join(f"{percent_encode(k)}={percent_encode(v)}" for k, v in pairs)


def main(argv):
    if len(argv) != 2:
        sys.exit("Usage: encode_query.py '<json-array-of-[key,value]-pairs>'")
    pairs = [(str(k), str(v)) for k, v in json.loads(argv[1])]
    print(encode_pairs(pairs))


if __name__ == "__main__":
    main(sys.argv)
