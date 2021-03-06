from ConfigParser import SafeConfigParser as ConfigParser

from twisted.web import server
from twisted.internet import endpoints, reactor, ssl
from twisted.python import filepath, log
from twisted.application import service
from twisted.application.internet import StreamServerEndpointService

from appserver import monitor, deployer, resources

config = ConfigParser()
config.read(['./conf.ini'])

vhosts = filepath.FilePath(config.get('master', 'base-directory'))
ports = config.get('children', 'port-range').split('-')

depl = deployer.TwistdAppDeployer(
    reactor,
    deployer.PortPool(range(int(ports[0]), int(ports[1]))),
    setUID=config.getboolean('children', 'change-permissions'),
    twistdPattern=config.get('children', 'twistd'),
    logfilePattern=config.get('children', 'logfile'),
)
mon = monitor.DirectoryMonitor(reactor)


def file_created(path, mask):
    if path.isfile() and path.basename() == 'app.py':
        depl.deploy(path.parent())

def file_removed(path, mask):
    if path.basename() == 'app.py':
        depl.undeploy(path.parent())

def dir_created(path, mask):
    mon.watch(path, [file_created], mask=monitor.IN_CREATE)
    mon.watch(path, [file_removed], mask=monitor.IN_DELETE)

mon.watch(vhosts, [dir_created], mask=monitor.IN_CREATE)


@reactor.callWhenRunning
def initial():
    for child in vhosts.children():
        mon.watch(child, [file_created], mask=monitor.IN_CREATE)
        mon.watch(child, [file_removed], mask=monitor.IN_DELETE)
        app = child.child('app.py')
        if app.exists() and app.isfile():
            depl.deploy(
                child,
                chroot=config.getboolean('children', 'chroot')
            )


class SNIContextFactory(ssl.ContextFactory):
    def __init__(self, deployer, config):
        self._deployer = deployer
        self._context = self._buildGenericContext()
        self._config = config
        self._contexts = {}

    def _buildGenericContext(self):
        from OpenSSL import SSL
        ctx = SSL.Context(SSL.SSLv23_METHOD)
        ctx.set_options(SSL.OP_NO_SSLv2)
        ctx.set_tlsext_servername_callback(self._gotServerName)
        return ctx

    def setContextFactory(self, serverName, connection):
        # TODO: Rearchitecture everything here
        if serverName not in self._contexts:
            try:
                base = self._deployer.applications[serverName]
            except KeyError:
                log.err('Unknown host {}'.format(serverName))
                connection.shutdown()
                return

            key = base.preauthChild(self._config.get('children', 'privatekey')
                                    .format(vhost=serverName))

            cert = base.preauthChild(self._config.get('children', 'certificate')
                                    .format(vhost=serverName))

            if not key.exists() or not cert.exists():
                log.err('SSL not supported for {} (key or cert not found)'
                        .format(serverName))
                connection.shutdown()
                return

            self._contexts[serverName] = ssl.DefaultOpenSSLContextFactory(
                privateKeyFileName=key.path,
                certificateFileName=cert.path,
            )

        connection.set_context(self._contexts[serverName].getContext())

    def _gotServerName(self, connection):
        name = connection.get_servername()
        if name:
            self.setContextFactory(name, connection)
        else:
            log.msg('SNI not provided, closing SSL connection')
            connection.shutdown()

    def getContext(self):
        return self._context


sslContext = SNIContextFactory(depl, config)

ports = [
    endpoints.TCP4ServerEndpoint(reactor, config.getint('master', 'port')),
    endpoints.SSL4ServerEndpoint(reactor, config.getint('master', 'sslport'),
                                 sslContext),
]

logfile = filepath.FilePath(config.get('master', 'http_logfile'))
if not logfile.parent().exists():
    logfile.parent().makedirs()

depl.root.putChild('_admin', resources.VhostListing(depl))
site = server.Site(depl.root, logPath=logfile.path)

application = service.Application('appserver')
depl.setServiceParent(application)

for port in ports:
    svc = StreamServerEndpointService(port, site)
    svc.setServiceParent(application)
