# -*- coding: utf-8 -*-

import nicocookie
import re
import socket
import time
from threading import Thread
from io import BytesIO
from urllib2 import (build_opener, HTTPCookieProcessor, quote)
from urlparse import (urljoin, parse_qs)
from cookielib import CookieJar
from xml.etree import ElementTree


__all__ = [
    "Nicolive", "LoginError"
    ]


BASE_LOGIN_URL = "https://secure.nicovideo.jp/secure/"
LOGIN_URL      = urljoin(BASE_LOGIN_URL, "login?site=niconico")
LOGOUT_URL     = urljoin(BASE_LOGIN_URL, "logout")

API_BASE         = "http://live.nicovideo.jp/api/"
PLAYERSTATUS_API = urljoin(API_BASE, "getplayerstatus?v=%(lv)s")
OWNERPOST_API    = urljoin(API_BASE, "broadcast/%(lv)s")
POSTKEY_API      = urljoin(API_BASE, "getpostkey?thread=%(thread)s&block_no=%(block_no)s")
HEARTBEAT_API    = urljoin(API_BASE, "heartbeat?v=%(lv)s")

GET_COMMENT_XML  = '<thread thread="%(thread)s" res_from="-%(res_from)s" version="20061206" />\0'
POST_XML         = '<chat thread="%(thread)s" ticket="%(ticket)s" vpos="%(vpos)s" postkey="%(postkey)s" \
mail="%(mail)s" user_id="%(user_id)s" premium="%(premium)s">%(text)s</chat>\0'

UPDATEINTERVAL = 45 # sec


class ErrorBase(Exception):
    def __str__(self):
        return str(self._msg)


class LoginError(ErrorBase):        _msg = "login incorrect"
class InvalidLiveNumber(ErrorBase): _msg = "invalid live number"
class NotloginError(ErrorBase):     _msg = "not logged in"
class ClosedError(ErrorBase):       _msg = "live stream is closed"
class PostError(ErrorBase):         _msg = "comment post failed"

class UnknownError(ErrorBase):
    def __init__(self, msg):
        self._msg = msg

ERRORS = {
        "notlogin": NotloginError,
        "closed":   ClosedError
    }


class Ms(object):
    def __init__(self, addr, port, thread):
        self.__addr = addr
        self.__port = port
        self.__thread = thread


    @property
    def addr(self): return self.__addr

    @property
    def port(self): return self.__port

    @property
    def thread(self): return self.__thread


class Liveinfo(object):
    def __init__(self, xml):
        self.__xml = xml
        self._parse(self.__xml)


    def _parse(self, xml):
        e = ElementTree.XML(xml)

        if e.get("status") != "ok":
            raise self._error(e.find("error/code").text)

        stream = e.find("stream")
        user   = e.find("user")
        ms     = e.find("ms")

        self.__lv            = stream.find("id").text
        self.__start_time    = int(stream.find("start_time").text)
        self.__room_label = user.find("room_label").text
        self.__seet_no    = int(user.find("room_seetno").text)
        self.__is_premium = bool(user.find("is_premium").text)
        self.__user_id    = user.find("user_id").text
        self.__ms         = Ms(ms.find("addr").text, int(ms.find("port").text), int(ms.find("thread").text))

        self._watch_count   = int(stream.find("watch_count").text)
        self._comment_count = int(stream.find("comment_count").text)


    def _error(self, code):
        return ERRORS[code] if code in ERRORS else UnknownError(code)


    @property
    def elapsed(self): return time.time() - self.__start_time

    @property
    def xml(self): return self.__xml

    @property
    def lv(self): return self.__lv

    @property
    def watch_count(self): return self._watch_count

    @property
    def comment_count(self): return self._comment_count

    @property
    def start_time(self): return self.__start_time

    @property
    def room_label(self): return self.__room_label

    @property
    def seet_no(self): return self.__seet_no

    @property
    def is_premium(self): return self.__is_premium

    @property
    def user_id(self): return self.__user_id

    @property
    def ms(self): return self.__ms


class ThreadInfo(object):
    def __init__(self, xml):
        self.__xml = xml
        e = ElementTree.XML(self.__xml)
        self.__last_res    = int(e.get("last_res", 0))
        self.__resultcoce  = int(e.get("resultcode"))
        self.__revision    = int(e.get("revision"))
        self.__server_time = int(e.get("server_time"))
        self.__thread = int(e.get("thread"))
        self.__ticket = e.get("ticket")


    @property
    def xml(self): return self.__xml

    @property
    def last_res(self): return self.__last_res

    @property
    def resultcode(self): return self.__resultcoce

    @property
    def revision(self): return self.__revision

    @property
    def server_time(self): return self.__server_time

    @property
    def thread(self): return self.__thread

    @property
    def ticket(self): return self.__ticket


class Comment(object):
    def __init__(self, xml):
        parser = {
            "chat": self.__parse_chat,
            "chat_result": self.__parse_chat_result
            }
        self.__xml = xml
        e = ElementTree.XML(self.__xml)
        parser[e.tag](e)


    def __parse_chat(self, e):
        self.__anonymity = bool(e.get("anonymity"))
        self.__date      = int(e.get("date"))
        self.__mail      = e.get("mail") # TODO: separated with a space.
        self.__no        = int(e.get("no", 0))
        self._text      = e.text.encode('utf-8', 'ignore')
        self.__premium   = e.get("premium") # TODO: "1" is premium, "3" is owner or master, and more.
        self.__user_id   = e.get("user_id")

        self._status = 0


    def __parse_chat_result(self, e):
        self._status = int(e.get("status"))
        self._text = None


    def __str__(self):   return self._text
    def __repr__(self):  return self.__xml
    def __eq__(self, s): return self._text == s
    def __ne__(self, s): return not self.__eq__(s)

    @property
    def xml(self): return self.__xml

    @property
    def anonymity(self): return self.__anonymity

    @property
    def date(self): return self.__date

    @property
    def mail(self): return self.__mail

    @property
    def no(self): return self.__no

    @property
    def premium(self): return self.__premium

    @property
    def user_id(self): return self.__user_id

    @property
    def text(self): return self._text


class Nicolive(Liveinfo):
    def __init__(self, lv, mail=None, password=None):
        n = re.match("(lv\d+)$", lv)

        if not n:
            raise InvalidLiveNumber

        if mail != None and password != None:
            self.__opener = self.__login(mail, password)
        else:
            self.__opener = build_opener(HTTPCookieProcessor(nicocookie.getcookie()))

        xml = self.__opener.open(PLAYERSTATUS_API % dict(lv=n.group(1))).read()
        super(Nicolive, self).__init__(xml)

        self.__sock = self._getsock()
        self.__threadinfo = ThreadInfo(self._getelement(self.__sock))
        self.__heartbeat()


    def __iter__(self):
        while True:
            comment = self.recv()

            if self.__closed:
                break

            yield comment


    def __del__(self):
        self.close()


    def _getsock(self):
        sock = socket.create_connection((self.ms.addr, self.ms.port))
        sock.sendall(GET_COMMENT_XML % dict(
            thread=self.ms.thread,
            res_from=self.comment_count+100
            ))

        self.__closed = False

        return sock


    def _getelement(self, sock):
        buf = BytesIO()

        while True:
            c = sock.recv(1)

            if c == "\0":
                buf.seek(0)
                # return buf.read().decode("utf-8", "ignore")
                return buf.read()

            buf.write(c)


    def __login(self, mail, password):
        mail = quote(mail)
        password = quote(password)
        f = build_opener(HTTPCookieProcessor(CookieJar()))
        s = f.open(LOGIN_URL, "mail=%s&password=%s" % (mail, password))

        if s.read().decode("utf-8", "ignore").find(u"エラーメッセージ") != -1:
            raise LoginError

        return f


    def __heartbeat(self):
        hb = Thread(target=self.__updatehb)
        hb.daemon = True
        hb.start()


    def __updatehb(self):
        while True:
            e = ElementTree.parse(self.__opener.open(HEARTBEAT_API % dict(lv=self.lv))).getroot()

            if e.get("status") == "ok":
                self._watch_count   = int(e.find("watchCount").text)
                self._comment_count = int(e.find("commentCount").text)

            time.sleep(UPDATEINTERVAL)


    def recv(self):
        comment = Comment(self._getelement(self.__sock))

        if comment._status != 0:
            raise PostError

        if comment == "/disconnect":
            self.close()

        return comment


    def postcomment(self, comment, cmd="184", owner=False, name=""):
        if owner:
            self._owner_post(comment, cmd, name)
        else:
            self._user_post(comment, cmd)


    def _owner_post(self, comment, cmd, name):
        data = 'mail=%s&body=%s&name=%s' % tuple(*map(quote, [cmd, comment, ""]))
        url = OWNERPOST_API % dict(lv=self.lv)
        res = self.__opener.open(url, data).read().decode("utf-8", "ignore")

        status = res.split("=")[1]
        if status != "ok":
            raise PostError


    def _user_post(self, comment, cmd):
        sock = self._getsock()
        f = self.__opener.open(POSTKEY_API % {
            "thread":   self.ms.thread,
            "block_no": ThreadInfo(self._getelement(sock)).last_res // 100
            })
        self.__sock.sendall(POST_XML % {
            "thread":  self.ms.thread,
            "ticket":  self.__threadinfo.ticket,
            "vpos":    int(self.elapsed * 100),
            "postkey": parse_qs(f.read())["postkey"][0],
            "mail":    cmd,
            "user_id": self.user_id,
            "premium": int(self.is_premium),
            "text":    comment.encode('utf-8'),
            })
        sock.close()


    def close(self):
        if not self.__closed:
            self.__sock.close()
            self.__closed = True


    @property
    def threadinfo(self): return self.__threadinfo

    @property
    def closed(self): return self.__closed
