import json
import os
from datetime import datetime
from typing import Dict, Any, List

class MemoryTracker:
    """
    Registra la actividad previa de cada perfil para garantizar consistencia
    léxica y evitar comentarios repetidos o interacciones sospechosas.
    """
    MEMORY_FILE = "engine/memory/profiles_history.json"

    @classmethod
    def _cargar_historial(cls) -> Dict[str, Any]:
        if not os.path.exists(cls.MEMORY_FILE):
            return {}
        try:
            with open(cls.MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def _guardar_historial(cls, data: Dict[str, Any]):
        os.makedirs(os.path.dirname(cls.MEMORY_FILE), exist_ok=True)
        with open(cls.MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    @classmethod
    def registrar_interaccion(cls, username: str, plataforma: str, objetivo_id: str, contenido: str):
        historial = cls._cargar_historial()
        if username not in historial:
            historial[username] = []

        registro = {
            "plataforma": plataforma,
            "objetivo_id": objetivo_id,
            "contenido": contenido,
            "timestamp": datetime.now().isoformat()
        }
        historial[username].append(registro)
        cls._guardar_historial(historial)

    @classmethod
    def ya_interactuo(cls, username: str, objetivo_id: str) -> bool:
        historial = cls._cargar_historial()
        user_history = historial.get(username, [])
        return any(item["objetivo_id"] == objetivo_id for item in user_history)
