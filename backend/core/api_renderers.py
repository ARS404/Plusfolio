from rest_framework.renderers import JSONRenderer


def versioned_urls(value, field=None):
    """Keep server-provided PDF/TeX/ZIP URLs usable with bearer authentication."""
    if isinstance(value, dict):
        return {key: versioned_urls(item, key) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [versioned_urls(item, field) for item in value]
    is_url = isinstance(field, str) and (field.endswith('_url') or field in {'url','href'})
    if is_url and isinstance(value, str) and value.startswith('/api/') and value != '/api/v1' and not value.startswith(('/api/v1/','/api/v1?')):
        return '/api/v1/' + value[len('/api/'):]
    return value


class VersionedJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        return super().render(versioned_urls(data), accepted_media_type, renderer_context)
