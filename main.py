from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
        <head><title>mobil-xml</title></head>
        <body style="font-family: sans-serif; background-color: #121212; color: #fff; text-align: center; padding-top: 50px;">
            <h1>🚀 Servicio mobil-xml activo</h1>
            <p>La aplicación se ha conectado correctamente.</p>
        </body>
    </html>
    """
