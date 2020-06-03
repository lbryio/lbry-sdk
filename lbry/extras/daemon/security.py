def is_request_allowed(request, conf) -> bool:
    origin = request.headers.get('Origin', 'null')
    if origin == 'null' or conf.allowed_origin in ('*', origin):
        return True
    return False
