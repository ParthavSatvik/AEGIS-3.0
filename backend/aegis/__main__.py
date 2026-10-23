import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("aegis.api:app", host=os.environ.get("AEGIS_HOST", "127.0.0.1"),
                port=int(os.environ.get("AEGIS_PORT", "8000")))
