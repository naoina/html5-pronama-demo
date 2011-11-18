# -*- coding: utf-8 -*-

import json
import os
import threading

import tornado.ioloop

from tornado.web import RequestHandler
from tornado.web import Application
from tornado.websocket import WebSocketHandler
from tornado.template import Loader

from pynicolive import nicolive

here = os.path.abspath(os.path.dirname(__file__))
account = eval(open(here + "/account").read())
client = dict()
loader = Loader(here + "/templates")


class HttpViewHandler(RequestHandler):
    def get(self, lvnum):
        template = loader.load('view.html')
        self.write(template.generate())


def getcomments(lvnum, nico):
    for comment in nico:
        if not client[lvnum]:
            break
        if not comment.text:
            continue
        value = json.dumps({'body': comment.text,
                            'no': comment.no,
                            'premium': comment.premium})
        for receiver in client[lvnum]:
            receiver.write_message(value)


class CommentHandler(WebSocketHandler):
    def open(self, lvnum):
        print "peer is join to lv%s" % lvnum
        self.lvnum = lvnum
        if lvnum in client:
            self.nico = client[lvnum][0].nico
            client[lvnum].add(self)
        else:
            try:
                nico = nicolive.Nicolive('lv%s' % lvnum, account['user'],
                        account['pass'])
            except Exception:
                self.write_message('error')
                raise
            else:
                self.nico = nico
            client[lvnum] = set((self,))
            thread = threading.Thread(target=getcomments, args=(lvnum, nico))
            thread.daemon = True
            thread.start()
        print 'all clients are %s' % len(client[lvnum])

    def on_message(self, msg):
        self.nico.postcomment(msg)

    def on_close(self):
        client[self.lvnum].remove(self)
        print "close peer, all clients are %s" % len(client[self.lvnum])
        if not client[self.lvnum]:
            del client[self.lvnum]

app = Application([
    (r"/lv(\d+)", HttpViewHandler),
    (r"/lv(\d+)/comment", CommentHandler),
    ])

if __name__ == '__main__':
    app.listen(9001)
    tornado.ioloop.IOLoop.instance().start()
