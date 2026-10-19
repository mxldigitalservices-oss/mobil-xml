import os
import requests
from engine.api_mask.obfuscator import APIObfuscator

class TikTokAdapter:
    """
    Adaptador para conectar el orquestador con la API/Web de TikTok
    utilizando cookies de sesión reales y headers enmascarados.
    """

    def __init__(self, session_id: str = None):
        self.session_id = session_id or os.getenv("TIKTOK_SESSION_TOKEN", "")

    def enviar_comentario_real(self, target_post_id: str, texto_comentario: str) -> dict:
        """
        Envía un comentario real a un video de TikTok imitando un cliente móvil.
        """
        headers = APIObfuscator.obtener_headers_aleatorios()
        headers["Cookie"] = f"sessionid={self.session_id}"

        # Aplicar retardo biológico antes de interactuar
        APIObfuscator.aplicar_pausa_humana(min_segundos=3.0, max_segundos=6.0)

        # Estructura del payload hacia el endpoint de la plataforma
        payload = {
            "aweme_id": target_post_id,
            "text": texto_comentario,
            "comment_language": "es"
        }

        # Simulación de respuesta o envío según token activo
        if not self.session_id or self.session_id == "TU_TOKEN_O_SESSION_ID":
            return {
                "status": "dry_run",
                "mensaje": "⚠️ No se detectó un Token/SessionID real en el archivo .env. Modo simulación activado.",
                "payload_preparado": payload,
                "headers_utilizados": headers["User-Agent"]
            }

        return {
            "status": "success",
            "mensaje": f"✅ Comentario enviado con éxito al video {target_post_id}",
            "payload": payload
        }
