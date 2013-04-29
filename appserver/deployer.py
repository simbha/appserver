import os

from twisted.python import log, filepath
from twisted.runner import procmon
from twisted.web import vhost
from twisted.application import service

from appserver import proxy


class PortPool(object):
    def __init__(self, ports):
        self.ports = set(ports)
        self.available = set(ports)
        self.used = set()

    def reserve(self):
        port = self.available.pop()
        self.used.add(port)
        return port

    def release(self, port):
        self.used.remove(port)
        self.available.add(port)


class rootUserID(object):
    def __enter__(self):
        self.old_euid = os.geteuid()
        if self.old_euid != 0:
            log.msg("Setting EUID = 0")
            os.seteuid(0)

    def __exit__(self, exc_type, exc_value, traceback):
        if self.old_euid != os.geteuid():
            log.msg("Restoring EUID = {}".format(self.old_euid))
            os.seteuid(self.old_euid)


class chdir(object):
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.curdir = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.curdir)


class TwistdAppDeployer(service.MultiService):
    def __init__(self, reactor, portsPool, setUID, twistdPattern,
                 logfilePattern):
        service.MultiService.__init__(self)
        self.procmon = procmon.ProcessMonitor(reactor)
        self.procmon.setServiceParent(self)
        self.ports = portsPool
        self.root = vhost.NameVirtualHost()
        self.setUID = setUID
        self.twistdPattern = twistdPattern
        self.logfilePattern = logfilePattern
        self.reactor = reactor
        self.applications = {}

    def stopService(self):
        if self.setUID:
            with rootUserID():
                return service.MultiService.stopService(self)
        else:
            return service.MultiService.stopService(self)

    def getLogfile(self, path, name):
        logfile = self.logfilePattern.format(vhost=name)
        logfile = os.path.join(path.path, logfile)
        logfile = filepath.FilePath(logfile)
        if not logfile.parent().exists():
            logfile.parent().makedirs()
            if self.setUID:
                os.chown(logfile.parent().path, path.getUserID(),
                         path.getGroupID())
        return logfile

    def getTwistd(self, path, name):
        twistd = self.twistdPattern.format(vhost=name)
        twistd = os.path.join(path.path, twistd)
        twistd = filepath.FilePath(twistd)
        if not twistd.exists():
            raise RuntimeError('twistd executable not found at \'{}\''
                               .format(twistd.path))
        return twistd


    def deploy(self, path, chroot=False):
        name = path.basename()
        port = self.ports.reserve()

        log.msg('Spawning new vhost: {}:{}'.format(name, port))

        env = {
            'PATH': os.environ['PATH'],
            'PROXY_PORT': str(port),
        }

        logfile = self.getLogfile(path, name)
        twistd = self.getTwistd(path, name)

        command = [
            twistd.path,
            '-n',
            '-y', path.child('app.py').path,
            '--rundir={}'.format(path.path),
            '--pidfile=',
            '--logfile={}'.format(logfile.path),
        ]

        if chroot:
            command += [
                '--chroot',
            ]

        kwargs = {}

        if self.setUID:
            kwargs['uid'] = path.getUserID()
            kwargs['gid'] = path.getGroupID()

        self.procmon.addProcess(name, command, env=env, **kwargs)

        resource = proxy.RewritingReverseProxyResource('localhost', port, '')
        self.root.addHost(name, resource)

        self.applications[name] = path

        log.msg('vhost spawned')

    def undeploy(self, path):
        name = path.basename()
        log.msg('Stopping vhost {}'.format(name))
        if self.setUID:
            with rootUserID():
                self.procmon.removeProcess(name)
        else:
            self.procmon.removeProcess(name)
        self.ports.release(self.root.hosts[name].port)
        self.root.removeHost(name)
        self.applications.pop(name)
