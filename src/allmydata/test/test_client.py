
import os
from twisted.trial import unittest
from twisted.application import service
from twisted.internet import reactor, defer

import allmydata
from allmydata import client, introducer
from allmydata.util import version_class, idlib
from foolscap.eventual import flushEventualQueue

class MyIntroducerClient(introducer.IntroducerClient):
    def __init__(self):
        self.connections = {}

def permute(c, key):
    return [ y for x, y, z in c.get_permuted_peers(key) ]

class Basic(unittest.TestCase):
    def test_loadable(self):
        basedir = "test_client.Basic.test_loadable"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        c = client.Client(basedir)

    def test_loadable_without_vdrive(self):
        basedir = "test_client.Basic.test_loadable_without_vdrive"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        c = client.Client(basedir)

    def test_secrets(self):
        basedir = "test_client.Basic.test_secrets"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        c = client.Client(basedir)
        secret_file = os.path.join(basedir, "secret")
        self.failUnless(os.path.exists(secret_file))
        renew_secret = c.get_renewal_secret()
        self.failUnless(idlib.b2a(renew_secret))
        cancel_secret = c.get_cancel_secret()
        self.failUnless(idlib.b2a(cancel_secret))

    def test_sizelimit_1(self):
        basedir = "client.Basic.test_sizelimit_1"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        open(os.path.join(basedir, "sizelimit"), "w").write("1000")
        c = client.Client(basedir)
        self.failUnlessEqual(c.getServiceNamed("storageserver").sizelimit,
                             1000)

    def test_sizelimit_2(self):
        basedir = "client.Basic.test_sizelimit_2"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        open(os.path.join(basedir, "sizelimit"), "w").write("10K")
        c = client.Client(basedir)
        self.failUnlessEqual(c.getServiceNamed("storageserver").sizelimit,
                             10*1000)

    def test_sizelimit_3(self):
        basedir = "client.Basic.test_sizelimit_3"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        open(os.path.join(basedir, "sizelimit"), "w").write("5mB")
        c = client.Client(basedir)
        self.failUnlessEqual(c.getServiceNamed("storageserver").sizelimit,
                             5*1000*1000)

    def test_sizelimit_4(self):
        basedir = "client.Basic.test_sizelimit_4"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        open(os.path.join(basedir, "sizelimit"), "w").write("78Gb")
        c = client.Client(basedir)
        self.failUnlessEqual(c.getServiceNamed("storageserver").sizelimit,
                             78*1000*1000*1000)

    def test_sizelimit_bad(self):
        basedir = "client.Basic.test_sizelimit_bad"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        open(os.path.join(basedir, "sizelimit"), "w").write("bogus")
        c = client.Client(basedir)
        self.failUnlessEqual(c.getServiceNamed("storageserver").sizelimit,
                             None)

    def test_permute(self):
        basedir = "test_client.Basic.test_permute"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        c = client.Client(basedir)
        c.introducer_client = MyIntroducerClient()
        for k in ["%d" % i for i in range(5)]:
            c.introducer_client.connections[k] = None
        self.failUnlessEqual(permute(c, "one"), ['3','1','0','4','2'])
        self.failUnlessEqual(permute(c, "two"), ['0','4','2','1','3'])
        c.introducer_client.connections.clear()
        self.failUnlessEqual(permute(c, "one"), [])

        c2 = client.Client(basedir)
        c2.introducer_client = MyIntroducerClient()
        for k in ["%d" % i for i in range(5)]:
            c2.introducer_client.connections[k] = None
        self.failUnlessEqual(permute(c2, "one"), ['3','1','0','4','2'])

    def test_versions(self):
        basedir = "test_client.Basic.test_versions"
        os.mkdir(basedir)
        open(os.path.join(basedir, "introducer.furl"), "w").write("")
        open(os.path.join(basedir, "vdrive.furl"), "w").write("")
        c = client.Client(basedir)
        mine, oldest = c.remote_get_versions()
        self.failUnlessEqual(version_class.Version(mine), allmydata.__version__)

def flush_but_dont_ignore(res):
    d = flushEventualQueue()
    def _done(ignored):
        return res
    d.addCallback(_done)
    return d

class Run(unittest.TestCase):

    def setUp(self):
        self.sparent = service.MultiService()
        self.sparent.startService()
    def tearDown(self):
        d = self.sparent.stopService()
        d.addBoth(flush_but_dont_ignore)
        return d

    def test_loadable(self):
        basedir = "test_client.Run.test_loadable"
        os.mkdir(basedir)
        dummy = "pb://wl74cyahejagspqgy4x5ukrvfnevlknt@127.0.0.1:58889/bogus"
        open(os.path.join(basedir, "introducer.furl"), "w").write(dummy)
        open(os.path.join(basedir, "suicide_prevention_hotline"), "w")
        c = client.Client(basedir)

    def stall(self, res=None, delay=1):
        d = defer.Deferred()
        reactor.callLater(delay, d.callback, res)
        return d

    def test_reloadable(self):
        basedir = "test_client.Run.test_reloadable"
        os.mkdir(basedir)
        dummy = "pb://wl74cyahejagspqgy4x5ukrvfnevlknt@127.0.0.1:58889/bogus"
        open(os.path.join(basedir, "introducer.furl"), "w").write(dummy)
        c1 = client.Client(basedir)
        c1.setServiceParent(self.sparent)

        # the cygwin buildslave seems to need more time to let the old
        # service completely shut down. When delay=0.1, I saw this test fail,
        # probably due to the logport trying to reclaim the old socket
        # number.
        d = self.stall(delay=2.0)
        d.addCallback(lambda res: c1.disownServiceParent())
        def _restart(res):
            # TODO: pause for slightly over one second, to let
            # Client._check_hotline poll the file once. That will exercise
            # another few lines. Then add another test in which we don't
            # update the file at all, and watch to see the node shutdown. (to
            # do this, use a modified node which overrides Node.shutdown(),
            # also change _check_hotline to use it instead of a raw
            # reactor.stop, also instrument the shutdown event in an
            # attribute that we can check)
            c2 = client.Client(basedir)
            c2.setServiceParent(self.sparent)
            return c2.disownServiceParent()
        d.addCallback(_restart)
        return d

