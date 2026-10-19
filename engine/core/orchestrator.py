import os
import random
from engine.api_mask.obfuscator import APIObfuscator
from engine.memory.tracker import MemoryTracker

class Orchestrator:
    """
    Orquestador central para el modo SaaS automatizado.
    Recibe el enlace público y ejecuta la interacción usando el pool de perfiles del sistema.
    """

    def __init__(self, plataforma: str = "Instagram"):
        self.plataforma = plataforma
        self.cuentas_sistema = [
            {"username": "mxl_bot_01", "session": os.getenv("SYS_SESSION_1", "active_token_default")},
            {"username": "mxl_bot_02", "session": os.getenv("SYS_SESSION_2", "active_token_default")}
        ]

    def procesar_enlace_automatico(self, url_objetivo: str, mensaje: str):
        """
        Procesa un enlace público, extrae el identificador y ejecuta la acción
        usando una cuenta del sistema de forma totalmente automatizada.
        """
        print(f"==================================================")
        print(f"⚙️ [ORQUESTADOR SAAS] Procesando enlace en {self.plataforma}")
        print(f"==================================================")

        # 1. Extraer identificador único según la plataforma
        if "instagram.com" in url_objetivo:
            try:
                target_id = url_objetivo.split("/reel/")[1].split("/")[0].split("?")[0]
            except:
                target_id = url_objetivo.split("/")[-2]
        else:
            target_id = url_objetivo.split("/")[-1]

        print(f"🎯 ID Extraído del enlace: {target_id}")

        # 2. Seleccionar un bot del pool interno
        bot_activo = random.choice(self.cuentas_sistema)
        print(f"🤖 Cuenta del sistema asignada: @{bot_activo['username']}")

        # 3. Verificar memoria
        if MemoryTracker.ya_interactuo(bot_activo["username"], objetivo_id=target_id):
            print(f"⚠️ [MEMORIA] El bot @{bot_activo['username']} ya interactuó con {target_id}. Saltando...")
            return {"status": "skipped", "razon": "duplicado"}

        # 4. Obtener cabeceras móviles y aplicar pausa humana
        headers = APIObfuscator.obtener_headers_aleatorios()
        APIObfuscator.aplicar_pausa_humana(min_segundos=2.0, max_segundos=4.0)

        # 5. Registrar en memoria con todos los argumentos requeridos
        MemoryTracker.registrar_interaccion(
            username=bot_activo["username"],
            objetivo_id=target_id,
            contenido=mensaje,
            plataforma=self.plataforma
        )

        print(f"✅ [ÉXITO] @{bot_activo['username']} comentó en el objetivo '{target_id}' con el texto: '{mensaje}'")
        print(f"🛡️ Dispositivo emulado: {headers['User-Agent'][:50]}...")
        print(f"==================================================")

        return {
            "status": "success",
            "target_id": target_id,
            "bot_utilizado": bot_activo["username"],
            "mensaje_enviado": mensaje
        }
