from twisted.python import log
from twisted.web import resource, server


class RestartProcess(resource.Resource):
    isLeaf = True

    def __init__(self, procmon, procname):
        self.procmon = procmon
        self.procname = procname

    def getChild(self, name, request):
        return self

    def render_GET(self, request):
        log.msg('Restarting {}'.format(self.procname))
        self.procmon.stopProcess(self.procname)
        return 'Restarting service {}'.format(self.procname)


class VhostListing(resource.Resource):
    isLeaf = True

    def __init__(self, deployer):
        self.deployer = deployer

    def getChild(self, name, request):
        return self

    def render_GET(self, request):
        try:
            _, port = request.received_headers['host'].split(':')
            port = ':' + port
        except ValueError:
            port = ''

        request.write('<h1>Available applications</h1>')
        request.write('<ul>')
        for app in self.deployer.applications:
            request.write('<li><a href="//{0}{1}">{0}{1}</a></li>'.format(
                app, port
            ))
        request.write('</ul>')
        request.finish()
        return server.NOT_DONE_YET
