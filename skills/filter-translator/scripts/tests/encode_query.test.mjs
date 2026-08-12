import test from "node:test";
import assert from "node:assert/strict";
import { percentEncode, encodePairs } from "../encode_query.mjs";

test("unreserved chars untouched", () => {
  assert.equal(percentEncode("Abc123-._~"), "Abc123-._~");
});

test("space becomes %20 not +", () => {
  assert.equal(percentEncode("a b"), "a%20b");
});

test("tilde is never escaped", () => {
  assert.equal(percentEncode("a~b"), "a~b");
});

test("reserved ASCII punctuation escaped, uppercase hex", () => {
  assert.equal(percentEncode("a&b=c?d#e%f"), "a%26b%3Dc%3Fd%23e%25f");
});

test("unicode encoded as UTF-8 bytes", () => {
  assert.equal(percentEncode("café"), "caf%C3%A9");
});

test("empty string", () => {
  assert.equal(percentEncode(""), "");
});

test("single pair", () => {
  assert.equal(encodePairs([["status", "Done"]]), "status=Done");
});

test("multiple pairs joined with & in order", () => {
  assert.equal(encodePairs([["a", "1"], ["b", "2 3"]]), "a=1&b=2%203");
});

test("pair with reserved and unicode", () => {
  assert.equal(
    encodePairs([["$filter", "name eq 'café'"]]),
    "%24filter=name%20eq%20%27caf%C3%A9%27"
  );
});
