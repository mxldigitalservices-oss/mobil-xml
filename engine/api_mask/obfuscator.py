import random
import time

# Lista de User-Agents de aplicaciones móviles reales y navegadores móviles legítimos
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.55 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Xiaomi 23117RK66C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
]

class APIObfuscator:
    @staticmethod
    def obtener_headers_aleatorios() -> dict:
        """Genera cabeceras HTTP que imitan un dispositivo real para evadir bloqueos de API."""
        ua = random.choice(MOBILE_USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(["es-ES,es;q=0.9,en;q=0.8", "es-419,es;q=0.9", "es-DO;q=0.8,es;q=0.7"]),
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Upgrade-Insecure-Requests": "1"
        }

    @staticmethod
    def aplicar_pausa_humana(min_segundos: float = 1.5, max_segundos: float = 4.5):
        """Introduce una pausa gaussiana/aleatoria para romper patrones de tiempo en las peticiones."""
        retardo = random.uniform(min_segundos, max_segundos)
        time.sleep(retardo)
