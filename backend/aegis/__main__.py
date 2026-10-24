import uvicorn

from .settings import settings

if __name__ == "__main__":
    uvicorn.run("aegis.api:app", host=settings.host, port=settings.port, proxy_headers=True,
                forwarded_allow_ips="*" if settings.production else "127.0.0.1")
