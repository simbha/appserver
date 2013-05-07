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

ports = [
    endpoints.TCP4ServerEndpoint(reactor, config.getint('master', 'port'))
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
