from rest_framework_simplejwt.authentication import JWTAuthentication


class AuthorizeHeaderJWTAuthentication(JWTAuthentication):
    """
    Custom authentication class that looks for the token in the `Authorize` header
    instead of the default `Authorization`.
    Example request:
        Authorize: <your_access_token>
    """

    def get_header(self, request):
        header = request.META.get("HTTP_AUTHORIZE")  # Django converts headers to HTTP_<NAME>
        if isinstance(header, str):
            header = header.encode("iso-8859-1")  # ensure it's bytes
        return header

    def get_raw_token(self, header):
        if header is None:
            return None
        return header.decode("utf-8").strip()
