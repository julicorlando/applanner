from django.contrib.auth import logout


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
