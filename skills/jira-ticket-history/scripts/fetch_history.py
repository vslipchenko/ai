"""Fetch everything Jira knows about one ticket's history into a raw bundle.

Mirrors fetch_history.mjs: same endpoints, same paging rules, same bundle
shape. Read-only -- every request is a GET. Standard library only.

The one rule that matters: page every endpoint to the end and record how far
it got. A history that stops at the first page looks complete and is not.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BUNDLE_VERSION = 1
DEFAULTS = {"page_size": 100, "max_pages": 500, "retries": 4, "max_wait": 60}


class HttpError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


def parse_ticket(value, site=None):
    raw = str(value or "").strip()
    m = re.match(r"^(https?://[^/]+)(?:/.*?)?(?:/browse/|[?&]selectedIssue=)([A-Z][A-Z0-9_]+-\d+)", raw, re.I)
    if m:
        return {"site": m.group(1), "key": m.group(2).upper()}
    if re.match(r"^[A-Z][A-Z0-9_]+-\d+$", raw, re.I):
        return {"site": re.sub(r"/+$", "", site) if site else None, "key": raw.upper()}
    return None


def auth_header(deployment, email, token):
    if deployment == "datacenter":
        return "Bearer %s" % token
    return "Basic " + base64.b64encode(("%s:%s" % (email, token)).encode("utf-8")).decode("ascii")


def _describe(status, text):
    detail = ""
    try:
        j = json.loads(text)
        detail = "; ".join(list(j.get("errorMessages") or []) + [str(v) for v in (j.get("errors") or {}).values()])
    except (ValueError, AttributeError):
        pass
    base = {
        401: "authentication failed (check the email and token)",
        403: "no permission",
        404: "not found, or you have no permission to see it",
        429: "rate limited, retries exhausted",
    }.get(status, "HTTP %d" % status)
    return "%s: %s" % (base, detail) if detail else base


def get_json(url, headers, retries=DEFAULTS["retries"], sleep=time.sleep):
    """GET with retry on 429/503, honouring Retry-After. Returns parsed JSON."""
    attempt = 0
    while True:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                text = res.read().decode("utf-8")
            try:
                return json.loads(text)
            except ValueError:
                raise HttpError(200, "response was not JSON")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                ra = e.headers.get("Retry-After")
                try:
                    wait = min(float(ra), DEFAULTS["max_wait"]) if ra is not None and float(ra) >= 0 else 2 ** attempt
                except ValueError:
                    wait = 2 ** attempt
                e.close()
                sleep(wait)
                attempt += 1
                continue
            body = e.read().decode("utf-8", "replace")
            e.close()
            raise HttpError(e.code, _describe(e.code, body))
        except urllib.error.URLError as e:
            if attempt < retries:
                sleep(2 ** attempt)
                attempt += 1
                continue
            raise HttpError(0, "network error: %s" % e.reason)


def page_all(base, list_key, get, page_size, max_pages):
    """Page a startAt/maxResults endpoint until Jira says it is done."""
    items = []
    start_at, pages, total, complete, capped = 0, 0, None, False, False
    while True:
        if pages >= max_pages:
            capped = True
            break
        sep = "&" if "?" in base else "?"
        body = get("%s%sstartAt=%d&maxResults=%d" % (base, sep, start_at, page_size))
        pages += 1
        page = body.get(list_key) if isinstance(body.get(list_key), list) else []
        items.extend(page)
        if isinstance(body.get("total"), int):
            total = body["total"]
        if body.get("isLast") is True:
            complete = True
            break
        if "isLast" not in body and total is not None and len(items) >= total:
            complete = True
            break
        if not page:
            break  # Jira says there is more but sent nothing: stop, marked incomplete
        start_at += len(page)
    if complete and total is None:
        total = len(items)
    if complete and total is not None and len(items) < total:
        complete = False
    return items, {"got": len(items), "total": total, "pages": pages, "complete": complete}, capped


def fetch_history(site, key, deployment, email, token, page_size=None, max_pages=None, get_impl=None, now=None):
    page_size = page_size or DEFAULTS["page_size"]
    max_pages = max_pages or DEFAULTS["max_pages"]
    root = re.sub(r"/+$", "", site)
    errors = []
    getter_impl = get_impl or get_json

    def getter(d):
        headers = {"Accept": "application/json", "Authorization": auth_header(d, email, token)}
        return lambda url: getter_impl(url, headers)

    dep = deployment
    if not dep or dep == "auto":
        try:
            info = getter("cloud" if email else "datacenter")("%s/rest/api/2/serverInfo" % root)
            dep = "cloud" if info.get("deploymentType") == "Cloud" else "datacenter"
        except HttpError:
            dep = "cloud" if email else "datacenter"
    get = getter(dep)
    api = "%s/rest/api/2/issue/%s" % (root, urllib.parse.quote(key, safe=""))

    issue = get("%s?fields=*all&expand=names,schema" % api)  # fatal if this fails

    completeness = {}
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    bundle = {
        "bundle_version": BUNDLE_VERSION, "site": root, "key": key, "deployment": dep,
        "fetched_at": stamp.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (stamp.microsecond // 1000),
        "issue": {"id": issue.get("id"), "key": issue.get("key"), "fields": issue.get("fields") or {},
                  "names": issue.get("names") or {}, "schema": issue.get("schema") or {}, "description_format": "wiki"},
        "changelog": [], "comments": [], "worklogs": [], "completeness": completeness, "errors": errors,
    }

    # Changelog: the paged endpoint (Cloud, recent Data Center), else expand=changelog.
    try:
        items, info, capped = page_all("%s/changelog" % api, "values", get, page_size, max_pages)
        bundle["changelog"], completeness["changelog"] = items, info
        if capped:
            errors.append({"source": "changelog", "message": "stopped after %d pages" % max_pages})
    except HttpError as e:
        if e.status != 404:
            errors.append({"source": "changelog", "message": str(e)})
            completeness["changelog"] = {"got": 0, "total": None, "pages": 0, "complete": False}
        else:
            try:
                body = get("%s?fields=summary&expand=changelog" % api)
                cl = body.get("changelog") or {}
                bundle["changelog"] = cl.get("histories") or []
                got = len(bundle["changelog"])
                total = cl["total"] if isinstance(cl.get("total"), int) else got
                completeness["changelog"] = {"got": got, "total": total, "pages": 1, "complete": got >= total}
            except HttpError as e2:
                errors.append({"source": "changelog", "message": str(e2)})
                completeness["changelog"] = {"got": 0, "total": None, "pages": 0, "complete": False}

    for source, url, list_key in (
        ("comments", "%s/comment?orderBy=created&expand=renderedBody" % api, "comments"),
        ("worklogs", "%s/worklog" % api, "worklogs"),
    ):
        try:
            items, info, capped = page_all(url, list_key, get, page_size, max_pages)
            bundle[source], completeness[source] = items, info
            if capped:
                errors.append({"source": source, "message": "stopped after %d pages" % max_pages})
        except HttpError as e:
            errors.append({"source": source, "message": str(e)})
            completeness[source] = {"got": 0, "total": None, "pages": 0, "complete": False}
    return bundle


# ----------------------------------------------------------------------- cli --
FLAGS = {"--key": "key", "--site": "site", "--deployment": "deployment", "--email-env": "email_env",
         "--token-env": "token_env", "--out": "out", "--config": "config", "--page-size": "page_size",
         "--max-pages": "max_pages"}


def parse_args(argv):
    a = dict((v, None) for v in FLAGS.values())
    i = 0
    while i < len(argv):
        name = FLAGS.get(argv[i])
        if not name:
            raise ValueError("unknown argument %s" % argv[i])
        if i + 1 >= len(argv):
            raise ValueError("%s needs a value" % argv[i])
        a[name] = argv[i + 1]
        i += 2
    if not a["key"]:
        raise ValueError("--key is required (an issue key or a Jira URL)")
    if a["deployment"] and a["deployment"] not in ("auto", "cloud", "datacenter"):
        raise ValueError("--deployment must be auto, cloud or datacenter")
    for k in ("page_size", "max_pages"):
        if a[k] is not None:
            try:
                n = int(a[k])
            except ValueError:
                n = 0
            if n < 1:
                raise ValueError("--%s must be a positive integer" % k.replace("_", "-"))
            a[k] = n
    return a


def main(argv, env=None):
    env = os.environ if env is None else env
    try:
        a = parse_args(argv)
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1
    cfg = {}
    cfg_path = os.path.expanduser(a["config"] or "~/.jira-ticket-history/config.json")
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        if a["config"]:
            sys.stderr.write("error: cannot read config: %s\n" % e)
            return 1
    auth = cfg.get("auth") or {}
    t = parse_ticket(a["key"], a["site"] or cfg.get("site"))
    if not t:
        sys.stderr.write('error: "%s" is neither an issue key nor a Jira issue URL\n' % a["key"])
        return 1
    if not t["site"]:
        sys.stderr.write('error: no Jira site: pass --site or set "site" in the config\n')
        return 1
    deployment = a["deployment"] or cfg.get("deployment") or "auto"
    email_env = a["email_env"] or auth.get("email_env") or "JIRA_EMAIL"
    token_env = a["token_env"] or auth.get("token_env") or "JIRA_API_TOKEN"
    token, email = env.get(token_env), env.get(email_env)
    if not token:
        sys.stderr.write("error: not configured: the environment variable %s is not set\n" % token_env)
        return 2
    if deployment == "cloud" and not email:
        sys.stderr.write("error: not configured: Jira Cloud needs %s as well as %s\n" % (email_env, token_env))
        return 2
    try:
        bundle = fetch_history(t["site"], t["key"], deployment, email, token, a["page_size"], a["max_pages"])
    except HttpError as e:
        sys.stderr.write("error: could not read %s: %s\n" % (t["key"], e))
        return 3
    out = os.path.expanduser(a["out"]) if a["out"] else "%s-bundle.json" % t["key"]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
    for e in bundle["errors"]:
        sys.stderr.write("warning: %s: %s\n" % (e["source"], e["message"]))
    sys.stdout.write(json.dumps({"out": os.path.abspath(out), "key": t["key"], "deployment": bundle["deployment"],
                                 "completeness": bundle["completeness"], "errors": bundle["errors"]},
                                ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
