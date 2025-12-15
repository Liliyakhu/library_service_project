from drf_spectacular.extensions import OpenApiAuthenticationExtension


class AuthorizeHeaderJWTAuthenticationExtension(OpenApiAuthenticationExtension):
    target_class = "users.authentication.AuthorizeHeaderJWTAuthentication"
    name = "Authorize"  # must match SECURITY_SCHEMES key in settings

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorize",
            "description": (
                "Paste your JWT access token here (without 'Bearer').\n\n"
                "Example:\n\n    Authorize: <your_access_token>"
            ),
        }
