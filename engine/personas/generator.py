import random
import uuid
import httpx
from engine.personas.modismos_db import GestorModismos

OLLAMA_URL = "http://localhost:11434/api/generate"

DISPOSITIVOS_MOVIL = [
    {"tipo": "mobile", "brand": "Samsung", "model": "Galaxy A52", "screen": "1080x2400"},
    {"tipo": "mobile", "brand": "Xiaomi", "model": "Redmi Note 11", "screen": "1080x2400"},
    {"tipo": "tablet", "brand": "Lenovo", "model": "Tab M10", "screen": "1200x2000"},
    {"tipo": "mobile", "brand": "Motorola", "model": "Moto G30", "screen": "720x1600"}
]

PAISES_SOPORTADOS = ["CO", "DO", "MX", "CL"]

class GeneradorMultiperfil:
    @staticmethod
    def crear_perfil() -> dict:
        disp = random.choice(DISPOSITIVOS_MOVIL)
        pais = random.choice(PAISES_SOPORTADOS)
        modismo_base = GestorModismos.obtener_modismo(pais)
        
        perfil = {
            "profile_id": f"usr-{uuid.uuid4().hex[:8]}",
            "pais": pais,
            "dispositivo": disp,
            "huella_digital": {
                "user_agent": f"Mozilla/5.0 (Linux; Android 12; {disp['model']}) AppleWebKit/537.36",
                "resolucion": disp["screen"],
                "bias_typo": round(random.uniform(0.1, 0.3), 2)
            },
            "modismo_asignado": modismo_base
        }
        return perfil

    @staticmethod
    async def generar_comentario_con_ollama(contexto: str, pais: str) -> str:
        modismo_local = GestorModismos.obtener_modismo(pais)
        prompt = f"""
        Actúa como un usuario real de redes sociales en {pais}. 
        Tema o video: "{contexto}".
        Usa un tono natural de celular, sin formalismos robóticos. 
        Puedes incluir sutilmente esta jerga o estilo: "{modismo_local}".
        Escribe corto, máximo 1 o 2 frases, con ligeras imperfecciones humanas o sin tildes si es muy casual.
        """
        
        payload = {
            "model": "mistral",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.8}
        }
        
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(OLLAMA_URL, json=payload)
                if res.status_code == 200:
                    return res.json().get("response", "").strip()
        except Exception:
            pass
            
        return modismo_local
