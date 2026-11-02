class PrivateAPIMiddleware:
    """Authenticated CRM responses must never be stored in shared/browser caches."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/v1/'):
            response['Cache-Control'] = 'no-store, private'
        return response
