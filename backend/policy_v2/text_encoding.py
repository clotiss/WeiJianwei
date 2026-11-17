"""PDF glyph maps may yield lone UTF-16 surrogates; original bytes stay unchanged."""
from starlette.responses import JSONResponse


def unicode_text(value):
    return value.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')


def unicode_json(value):
    if isinstance(value, str):
        return unicode_text(value)
    if isinstance(value, list):
        return [unicode_json(item) for item in value]
    if isinstance(value, dict):
        return {key: unicode_json(item) for key, item in value.items()}
    return value


class UTF8JSONResponse(JSONResponse):
    def render(self, content):
        try:
            return super().render(content)
        except UnicodeEncodeError:
            # Also protect legacy stored JSON that predates extraction validation.
            return super().render(unicode_json(content))
