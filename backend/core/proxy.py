"""Accept only the last proxy-appended address, only in the private-proxy deployment."""
import ipaddress
from django.conf import settings

class ClientIPMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if getattr(settings,'TRUST_PROXY_CLIENT_IP',False):
            candidate=request.META.get('HTTP_X_FORWARDED_FOR','').split(',')[-1].strip()
            try:request.META['REMOTE_ADDR']=str(ipaddress.ip_address(candidate))
            except ValueError:pass
        return self.get_response(request)
