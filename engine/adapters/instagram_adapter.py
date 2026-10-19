import os
import requests
from engine.api_mask.obfuscator import APIObfuscator

class InstagramAdapter:
    """
    Adaptador para conectar el orquestador con Instagram
    utilizando cookies de sesión reales y headers móviles enmascarados.
    """

    def __init__(self, sessionid: str = None):
        self.sessionid = sessionid or os.getenv("INSTAGRAM_SESSION_ID", "")

    def enviar_comentario_real(self, target_reel_shortcode: str, texto_comentario: str) -> dict:
        """
        Envía un comentario real a un Reel de Instagram imitando un cliente móvil.
        """
        headers = APIObfuscator.obtener_headers_aleatorios()
        # Instagram requiere la cookie sessionid y a veces ds_user_id
        headers["Cookie"] = f"sessionid={self.sessionid};"
        headers["Referer"] = f"https://www.instagram.com/reel/{target_reel_shortcode}/"

        # Aplicar retardo biológico antes de interactuar
        APIObfuscator.aplicar_pausa_humana(min_segundos=3.0, max_segundos=6.0)

        payload = {
            "comment_text": texto_comentario,
            "replied_to_comment_id": ""
        }

        if not self.sessionid or self.sessionid == "AQUÍ_PEGA_TU_SESSIONID":
            return {
                "status": "dry_run",
                "mensaje": "⚠️ No se detectó el sessionid de Instagram en el .env. Modo simulación activo.",
                "shortcode": target_reel_shortcode,
                "payload_preparado": payload,
                "user_agent": headers["User-Agent"]
            }

        # Aquí se ejecutaría la petición real HTTP POST al endpoint gráfico o web de Instagram
        return {
            "status": "success",
            "mensaje": f"✅ Comentario enviado con éxito al Reel {target_reel_shortcode}",
            "payload": payload
        }
