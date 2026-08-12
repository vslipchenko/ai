// RFC 3986 query-string percent-encoding for a list of key/value pairs.
// Mirrors encode_query.py's explicit unreserved-char table byte-for-byte —
// intentionally NOT using URLSearchParams (application/x-www-form-urlencoded,
// a different spec that also escapes '~' unlike Python's urlencode).
import { pathToFileURL } from "node:url";

const UNRESERVED = new Set(
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
);

export function percentEncode(s) {
  const bytes = new TextEncoder().encode(s);
  let out = "";
  for (const byte of bytes) {
    const ch = String.fromCharCode(byte);
    if (byte < 128 && UNRESERVED.has(ch)) {
      out += ch;
    } else {
      out += "%" + byte.toString(16).toUpperCase().padStart(2, "0");
    }
  }
  return out;
}

export function encodePairs(pairs) {
  return pairs.map(([k, v]) => `${percentEncode(k)}=${percentEncode(v)}`).join("&");
}

export function main(argv) {
  if (argv.length !== 1) {
    console.error("Usage: encode_query.mjs '<json-array-of-[key,value]-pairs>'");
    process.exit(1);
  }
  console.log(encodePairs(JSON.parse(argv[0])));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
