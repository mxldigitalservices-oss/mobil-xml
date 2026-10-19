import random
from typing import Dict, Any

class ProfileManager:
    """
    Gestiona la identidad y el perfil completo de cada cuenta para garantizar
    que tenga un historial, biografía y presencia realista en cualquier plataforma.
    """

    PERFILES_BASE = [
        {
            "username": "carlos_vlogs_rd",
            "nombre_visible": "Carlos M. Santos",
            "bio": "Creador de contenido 🇩🇴 | Amante de la música y la tecnología 🎧 | Moviéndome en el área.",
            "ubicacion": "Santo Domingo, DR",
            "intereses": ["música urbana", "tecnología", "producción"],
            "jerga_region": "DO",
            "foto_avatar_url": "https://storage.googleapis.com/mxl-assets/avatars/user_carlos.jpg",
            "seguidores_simulados": 1240,
            "seguidos_simulados": 890,
            "publicaciones_previas": 45
        },
        {
            "username": "valen_music_co",
            "nombre_visible": "Valentina Ríos",
            "bio": "Melómana de corazón 🇨🇴 | Apoyando el talento emergente ✨ | Medellín / Bogotá",
            "ubicacion": "Medellín, Colombia",
            "intereses": ["salsa", "reggaeton", "marketing digital"],
            "jerga_region": "CO",
            "foto_avatar_url": "https://storage.googleapis.com/mxl-assets/avatars/user_valen.jpg",
            "seguidores_simulados": 2100,
            "seguidos_simulados": 1150,
            "publicaciones_previas": 88
        }
    ]

    @classmethod
    def obtener_perfil_completo(cls, username: str = None) -> Dict[str, Any]:
        """
        Retorna el perfil completo de la cuenta. Si no especifica uno, selecciona un perfil activo.
        """
        if username:
            for perfil in cls.PERFILES_BASE:
                if perfil["username"] == username:
                    return perfil
        return random.choice(cls.PERFILES_BASE)

    @classmethod
    def validar_perfil_humano(cls, perfil: Dict[str, Any]) -> bool:
        """
        Verifica que el perfil tenga los elementos mínimos de una persona real
        antes de permitir cualquier comentario o interacción.
        """
        requisitos = ["username", "nombre_visible", "bio", "foto_avatar_url"]
        return all(perfil.get(req) for req in requisitos)
