from ConfigParser import SafeConfigParser as ConfigParser

from twisted.web import server
from twisted.internet import endpoints, reactor
from twisted.python import filepath
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

def created(path, mask):
    depl.deploy(path)

def removed(path, mask):
    depl.undeploy(path)

@reactor.callWhenRunning
def initial():
    for child in vhosts.children():
        depl.deploy(
            child,
            chroot=config.getboolean('children', 'chroot')
        )

mon.watch(vhosts, [created], mask=monitor.IN_CREATE)
mon.watch(vhosts, [removed], mask=monitor.IN_DELETE)

ports = [
    endpoints.TCP4ServerEndpoint(reactor, config.getint('master', 'port'), interface='127.0.0.1')
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
