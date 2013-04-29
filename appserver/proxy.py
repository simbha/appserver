import urlparse
from urllib import quote as urlquote

from twisted.web import proxy


class RewritingProxyClient(proxy.ProxyClient):
    def rewriteHeader_LOCATION(self, value):
        parsed = urlparse.urlparse(value)
        if parsed.netloc == self.father.received_headers['host']:
            parsed = list(parsed)
            parsed[1] = self.father.originHost
            value = urlparse.urlunparse(parsed)
        return value

    def handleHeader(self, key, value):
        rewriteFunc = 'rewriteHeader_{}'.format(key.upper())
        rewriteFunc = getattr(self, rewriteFunc, None)

        if callable(rewriteFunc):
            value = rewriteFunc(value)

        return proxy.ProxyClient.handleHeader(self, key, value)


class RewritingProxyClientFactory(proxy.ProxyClientFactory):
    noisy = False
    protocol = RewritingProxyClient


class RewritingReverseProxyResource(proxy.ReverseProxyResource):
    proxyClientFactoryClass = RewritingProxyClientFactory

    def getChild(self, path, request):
        return RewritingReverseProxyResource(
            self.host, self.port, self.path + '/' + urlquote(path, safe=""))

    def render(self, request):
        # Save the host on which the request was first received
        request.originHost = request.received_headers['host']
        return proxy.ReverseProxyResource.render(self, request)
