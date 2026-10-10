"""
Absolute media URLs that stay correct behind a path-prefixing proxy/tunnel.

`request.build_absolute_uri('/media/x.jpg')` only fills in scheme + host —
the path itself is already root-relative, so a reverse proxy that mounts the
whole app under e.g. /app/ (common for hosted dev-preview tunnels) leaves
every generated link one segment short. Setting PUBLIC_URL_PREFIX makes every
link built through here correct for that case, while a normal deployment
(no such prefix, the default) is untouched.
"""
from django.conf import settings


def absolute_media_url(request, path_or_url):
    """`path_or_url` is a MEDIA_URL-relative path or a FieldFile's `.url`
    (both already start with '/'). Returns an absolute URL, or '' if empty."""
    if not path_or_url:
        return ''
    prefix = getattr(settings, 'PUBLIC_URL_PREFIX', '') or ''
    return request.build_absolute_uri(prefix + str(path_or_url))
