from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SessionVersionMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if user is not None and user.is_authenticated:
            stored=request.session.get("session_version")
            if stored is None:
                request.session["session_version"]=user.session_version
            elif int(stored)!=int(user.session_version):
                logout(request)
        return self.get_response(request)


class MustChangePasswordMiddleware:
    ALLOWED_PREFIXES=("/static/","/media/","/healthz/")
    ALLOWED_NAMES={
        "accounts:change-password","accounts:logout","accounts:two-factor-challenge",
    }

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if user is not None and user.is_authenticated and user.must_change_password:
            path=request.path
            allowed=any(path.startswith(prefix) for prefix in self.ALLOWED_PREFIXES)
            if not allowed:
                allowed_paths={reverse(name) for name in self.ALLOWED_NAMES}
                if path not in allowed_paths:
                    return redirect("accounts:change-password")
        return self.get_response(request)
