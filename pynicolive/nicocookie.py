import sqlite3
import os
import os.path
from io import StringIO
from cookielib import MozillaCookieJar


__all__ = [
        "getcookie", "NotFountError"
    ]


HOME = os.environ["HOME"]


class NotFountError(Exception):
    def __str__(self):
        return "Cookie file not found"


def firefoxcookiefile():
    pass # TODO


def chromecookiefile():
    return os.path.join(HOME, ".config", "chromium", "Default", "Cookies")


cookieinfo = {
        "firefox": {"file": firefoxcookiefile(),
                    "columns": "host, path, isSecure, expiry, name, value",
                    "table": "moz_cookies"},
        "chrome":  {"file": chromecookiefile(),
                    "columns": "host_key, path, secure, expires_utc, name, value",
                    "table": "cookies"}
    }


def getcookie():
    for type in cookieinfo:
        try:
            info = cookieinfo[type]
        except KeyError:
            continue

        with sqlite3.connect(info["file"]) as conn:
            conn.text_factory = lambda s: str(s, "utf-8", "ignore")
            cur = conn.cursor()
            cur.execute(" ".join(["SELECT", info["columns"], "FROM", info["table"]]))

            ftstr = ["FALSE", "TRUE"]
            s = StringIO()
            s.write("# Netscape HTTP Cookie File")

            for i in cur.fetchall():
                s.write("\t".join([i[0], ftstr[i[0].startswith(".")], i[1],
                                   ftstr[i[2]], str(i[3]), i[4], i[5]]) + "\n")

            s.seek(0)

            cj = MozillaCookieJar()
            cj._really_load(s, '', True, True)

            return cj

    raise NotFountError
