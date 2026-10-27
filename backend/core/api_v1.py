"""Stable versioned aliases reuse the browser API's domain and permission checks."""
from django.urls import path
from rest_framework.authentication import SessionAuthentication
from . import api, automation, api_reference, search_api, tex_api, catalogue_search_api
from .api_contract import ROUTES
from .api_renderers import VersionedJSONRenderer
from .authentication import BearerAuthentication

MODULES = {'api':api, 'automation':automation, 'api_reference':api_reference, 'search_api':search_api, 'tex_api':tex_api, 'catalogue_search_api':catalogue_search_api}


def versioned_view(view, *, credential_exchange=False):
    kwargs = {'renderer_classes':[VersionedJSONRenderer]}
    if not credential_exchange:
        kwargs['authentication_classes'] = [BearerAuthentication, SessionAuthentication]
    return view.cls.as_view(**kwargs)


urlpatterns = [path(pattern, versioned_view(getattr(MODULES[module], name), credential_exchange=pattern=='auth/token'))
               for pattern, view, _ in ROUTES for module, name in [view.split('.')]]
